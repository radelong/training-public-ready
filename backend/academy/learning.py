"""Local class authoring, immutable releases, protected content and exam grading."""
import csv
import hashlib
import io
import json
import re
import random
import time
from pathlib import Path
from typing import Literal
from urllib.parse import unquote
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator, ValidationError
from sqlalchemy import select, func
from .db import (Course, CourseVersion, ContentAsset, CourseProgress, ExamAttempt,
                 Lab, User, Audit, allocation_lock, uid)

MAX_PDF = 50 * 1024 * 1024
Identifier = str


class Module(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=10000)
    asset_id: str | None = Field(default=None, max_length=36)
    lab_id: str | None = Field(default=None, max_length=64)
    required: bool = True


class Question(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    type: Literal["multiple_choice", "true_false", "written"]
    prompt: str = Field(min_length=1, max_length=10000)
    choices: list[str] = Field(default_factory=list, max_length=8)
    correct: int | None = Field(default=None, ge=0, le=7)
    points: int = Field(default=1, ge=1, le=100)
    rubric: str = Field(default="", max_length=10000)
    explanation: str = Field(default="", max_length=10000)
    choice_explanations: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def valid_answer(self):
        if self.type == "true_false":
            self.choices = ["True", "False"]
        if self.type == "written":
            self.choices, self.correct = [], None
            self.choice_explanations = []
            if not self.rubric.strip():
                raise ValueError("Written questions require an instructor rubric")
        elif (len(self.choices) < 2 or self.correct is None or self.correct >= len(self.choices)
              or any(not c.strip() or len(c) > 2000 for c in self.choices)):
            raise ValueError("Choose a valid answer from at least two non-empty options")
        if self.choice_explanations and (len(self.choice_explanations) != len(self.choices)
                or any(len(v) > 10000 for v in self.choice_explanations)):
            raise ValueError("Choice explanations must match the answer options")
        return self


class Exam(BaseModel):
    instructions: str = Field(default="", max_length=10000)
    passing_score: int = Field(default=80, ge=1, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    require_modules: bool = True
    feedback: Literal["score_only", "after_pass"] = "after_pass"
    questions: list[Question] = Field(default_factory=list, max_length=200)


class CourseContent(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=10000)
    modules: list[Module] = Field(default_factory=list, max_length=100)
    exam: Exam = Field(default_factory=Exam)

    @model_validator(mode="after")
    def unique_ids(self):
        for collection in (self.modules, self.exam.questions):
            if len({v.id for v in collection}) != len(collection):
                raise ValueError("Module and question IDs must be unique within their lists")
        if not self.title.strip():
            raise ValueError("A class title is required")
        return self


class DraftWrite(BaseModel):
    revision: int = Field(ge=1)
    content: CourseContent


class ProgressWrite(BaseModel):
    module_id: str = Field(max_length=64)
    complete: bool = False


class AnswerWrite(BaseModel):
    # Values are validated against the version's question types below.
    answers: dict = Field(max_length=200)


class GradeWrite(BaseModel):
    marks: dict = Field(max_length=200)
    feedback: str = Field(default="", max_length=10000)


class AnswerKeyImport(BaseModel):
    csv: str = Field(max_length=1024 * 1024)
    questions: list[dict] = Field(min_length=1, max_length=200)


class NewLab(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=10000)
    kind: Literal["netlab", "linux", "custom"] = "custom"
    template_id: int = Field(ge=100, le=999999999)
    cores: int = Field(default=2, ge=1, le=16)
    memory: int = Field(default=2048, ge=1024, le=32768)
    drills: list[dict] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def valid_drills(self):
        seen = set()
        for drill in self.drills:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(drill.get("id", ""))) or drill["id"] in seen:
                raise ValueError("Each exercise needs a unique safe ID")
            seen.add(drill["id"])
            for field in ("title", "brief", "goal", "tools", "time", "level"):
                if not isinstance(drill.get(field), str) or len(drill[field]) > 10000:
                    raise ValueError(f"Each exercise needs a text {field}")
        return self


class LabPackageReceipt(NewLab):
    schema_version: Literal[1]
    package_format: Literal["academy-lab-package-v1"]
    disk_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    activate: bool = False


def learner_content(content):
    # Explicit allowlist: answer keys and rubrics never travel in learner lessons.
    content = json.loads(json.dumps(content))
    content["exam"]["questions"] = [
        {k: q[k] for k in ("id", "type", "prompt", "choices", "points")}
        for q in content["exam"]["questions"]]
    return content


def mount_learning(app, factory, settings, identity, administrator, get_db):
    folder = Path(settings.content_dir)

    def audit(db, user, action, target):
        db.add(Audit(user_id=user.id, action=action, target=target))

    def course(db, cid):
        value = db.get(Course, cid)
        if not value:
            raise HTTPException(404, "Class not found")
        return value

    def progress(db, vid, user):
        return db.scalars(select(CourseProgress).where(
            CourseProgress.version_id == vid, CourseProgress.user_id == user.id)).first()

    def version(db, vid, user):
        value = db.get(CourseVersion, vid)
        if not value:
            raise HTTPException(404, "Class version not found")
        c = course(db, value.course_id)
        if user.role != "admin" and c.published_id != vid and not progress(db, vid, user):
            raise HTTPException(404, "Class version not available")
        return value

    def attempt(db, aid, user):
        value = db.get(ExamAttempt, aid)
        if not value or (value.user_id != user.id and user.role != "admin"):
            raise HTTPException(404, "Exam attempt not found")
        return value

    def content_of(v):
        return json.loads(v.content_json)

    def validate_references(db, content, publishing=False):
        for module in content.modules:
            if publishing and not module.asset_id and not module.lab_id:
                raise HTTPException(422, "Each published module needs a slide PDF or a lab")
            if module.asset_id:
                asset = db.get(ContentAsset, module.asset_id)
                if not asset or not (folder / (asset.id + ".pdf")).is_file():
                    raise HTTPException(422, "A module PDF is missing; upload it again")
            if module.lab_id and not db.get(Lab, module.lab_id):
                raise HTTPException(422, "A linked lab does not exist")
            if publishing and module.required and module.lab_id and not db.get(Lab, module.lab_id).enabled:
                raise HTTPException(422, "Activate required linked labs before publishing")
        if publishing and (not content.modules or not content.exam.questions):
            raise HTTPException(422, "Publishing requires at least one module and one final exam question")
        if publishing and any(q.type != 'written' and not q.explanation.strip() for q in content.exam.questions):
            raise HTTPException(422, "Add an explanation for every objective question before publishing")

    def draft_view(c):
        return {"id": c.id, "revision": c.revision, "published_id": c.published_id,
                "content": json.loads(c.draft_json)}

    def attempt_view(db, a, user):
        content = content_of(db.get(CourseVersion, a.version_id))
        reviewing = user.role == "admin" and user.id != a.user_id
        reveal = a.status != "in_progress"
        result = {"id": a.id, "version_id": a.version_id, "title": content["title"],
                  "instructions": content["exam"].get("instructions", ""),
                  "status": a.status, "score": a.score, "passed": a.passed,
                  "created": a.created, "submitted": a.submitted,
                  "answers": json.loads(a.answers_json), "feedback": a.feedback if reviewing or reveal else "",
                  "passing_score": content["exam"]["passing_score"],
                  "questions": learner_content(content)["exam"]["questions"]}
        if a.status != "in_progress" and (reviewing or reveal):
            result["marks"] = json.loads(a.marks_json)
        if reviewing:
            result["questions"] = content["exam"]["questions"]
            result["username"] = db.get(User, a.user_id).username
        elif reveal:
            result["correct_answers"] = {q["id"]: q["correct"] for q in content["exam"]["questions"]
                                         if q["type"] != "written"}
            for question in result['questions']:
                original = next(q for q in content['exam']['questions'] if q['id'] == question['id'])
                question['explanation'] = original.get('explanation', '')
                options = original.get('choice_explanations', [])
                selected = result['answers'].get(question['id'])
                question['selected_explanation'] = options[selected] if type(selected) is int and selected < len(options) else ''
        order = json.loads(a.question_order_json)
        positions = {qid: i for i, qid in enumerate(order)}
        result['questions'].sort(key=lambda q: positions.get(q['id'], len(positions)))
        return result

    @app.get("/api/courses")
    def classes(auth=Depends(identity), db=Depends(get_db)):
        result = []
        for c in db.scalars(select(Course).where(Course.published_id.is_not(None)).order_by(Course.created.desc())):
            v = db.get(CourseVersion, c.published_id)
            data = content_of(v)
            p = progress(db, v.id, auth[0])
            result.append({"id": c.id, "version_id": v.id, "number": v.number, "title": data["title"],
                           "description": data["description"], "module_count": len(data["modules"]),
                           "completed": len(json.loads(p.completed_json)) if p else 0})
        return result

    @app.get("/api/admin/courses")
    def drafts(auth=Depends(administrator), db=Depends(get_db)):
        return [draft_view(c) for c in db.scalars(select(Course).order_by(Course.created.desc()))]

    @app.post("/api/admin/courses")
    def create_class(body: CourseContent, auth=Depends(administrator), db=Depends(get_db)):
        validate_references(db, body)
        c = Course(draft_json=body.model_dump_json())
        db.add(c); db.flush()
        audit(db, auth[0], "create_class", c.id); db.commit()
        return draft_view(c)

    @app.get("/api/admin/courses/{cid}")
    def get_draft(cid: str, auth=Depends(administrator), db=Depends(get_db)):
        return draft_view(course(db, cid))

    @app.put("/api/admin/courses/{cid}")
    def save_draft(cid: str, body: DraftWrite, auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        c = course(db, cid)
        if c.revision != body.revision:
            raise HTTPException(409, "Another administrator changed this draft. Reopen it before saving.")
        validate_references(db, body.content)
        c.draft_json, c.revision = body.content.model_dump_json(), c.revision + 1
        audit(db, auth[0], "save_class", c.id); db.commit()
        return draft_view(c)

    @app.post("/api/admin/courses/{cid}/publish")
    def publish(cid: str, body: dict, auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        c = course(db, cid)
        if body.get("revision") != c.revision:
            raise HTTPException(409, "Save and reload the latest draft before publishing")
        data = CourseContent.model_validate_json(c.draft_json)
        validate_references(db, data, True)
        number = (db.scalar(select(func.max(CourseVersion.number)).where(CourseVersion.course_id == cid)) or 0) + 1
        v = CourseVersion(course_id=cid, number=number, content_json=data.model_dump_json())
        db.add(v); db.flush(); c.published_id = v.id
        audit(db, auth[0], "publish_class", v.id); db.commit()
        return {"id": v.id, "number": v.number}

    @app.post("/api/admin/courses/{cid}/unpublish")
    def unpublish(cid: str, auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        c = course(db, cid); c.published_id = None
        audit(db, auth[0], "unpublish_class", cid); db.commit()
        return {"message": "Removed from catalog. Existing enrollments and results remain available."}

    @app.post("/api/admin/content")
    async def upload_pdf(request: Request, auth=Depends(administrator), db=Depends(get_db)):
        if request.headers.get("content-type", "").split(";")[0] != "application/pdf":
            raise HTTPException(415, "Upload a PDF exported from your slide deck")
        folder.mkdir(parents=True, exist_ok=True)
        aid = uid(); path = folder / (aid + ".pdf")
        size = 0; digest = hashlib.sha256()
        try:
            with path.open("xb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_PDF:
                        raise HTTPException(413, "Each PDF must be 50 MB or smaller")
                    output.write(chunk); digest.update(chunk)
            with path.open("rb") as source:
                if source.read(5) != b"%PDF-":
                    raise HTTPException(415, "The file is not a PDF")
            filename = unquote(request.headers.get("X-File-Name", "Slides.pdf"))
            filename = re.sub(r"[\x00-\x1f\x7f/\\]", "_", filename)[:180]
            asset = ContentAsset(id=aid, filename=filename, size=size, sha256=digest.hexdigest())
            db.add(asset); audit(db, auth[0], "upload_slides", aid); db.commit()
            return {"id": aid, "filename": filename, "size": size}
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @app.get("/api/content/{aid}")
    def pdf(aid: str, auth=Depends(identity), db=Depends(get_db)):
        asset = db.get(ContentAsset, aid)
        if not asset:
            raise HTTPException(404, "Slides not found")
        if auth[0].role != "admin":
            allowed = False
            for v in db.scalars(select(CourseVersion)):
                if any(m["asset_id"] == aid for m in content_of(v)["modules"]):
                    c = course(db, v.course_id)
                    if c.published_id == v.id or progress(db, v.id, auth[0]):
                        allowed = True; break
            if not allowed:
                raise HTTPException(404, "Slides not available")
        path = folder / (asset.id + ".pdf")
        if not path.is_file():
            raise HTTPException(404, "Slide file is missing; contact your administrator")
        return FileResponse(path, media_type="application/pdf", filename=asset.filename,
                            content_disposition_type="inline")

    @app.get("/api/course-versions/{vid}")
    def lesson(vid: str, auth=Depends(identity), db=Depends(get_db)):
        v = version(db, vid, auth[0]); p = progress(db, vid, auth[0])
        return {"id": v.id, "course_id": v.course_id, "number": v.number,
                "content": learner_content(content_of(v)),
                "completed": json.loads(p.completed_json) if p else [],
                "current_module": p.current_module if p else "",
                "attempts": [attempt_view(db, a, auth[0]) for a in db.scalars(select(ExamAttempt).where(
                    ExamAttempt.version_id == vid, ExamAttempt.user_id == auth[0].id).order_by(ExamAttempt.created.desc()))]}

    @app.post("/api/course-versions/{vid}/enroll")
    def enroll(vid: str, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db); version(db, vid, auth[0])
        if not progress(db, vid, auth[0]):
            db.add(CourseProgress(version_id=vid, user_id=auth[0].id))
            audit(db, auth[0], "enroll_class", vid)
        db.commit(); return {"message": "Progress will be saved"}

    @app.put("/api/course-versions/{vid}/progress")
    def save_progress(vid: str, body: ProgressWrite, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db); v = version(db, vid, auth[0]); p = progress(db, vid, auth[0])
        if not p:
            raise HTTPException(409, "Open the class before recording progress")
        if body.module_id not in {m["id"] for m in content_of(v)["modules"]}:
            raise HTTPException(422, "Module not found")
        completed = set(json.loads(p.completed_json))
        if body.complete: completed.add(body.module_id)
        p.completed_json, p.current_module = json.dumps(sorted(completed)), body.module_id
        db.commit(); return {"completed": sorted(completed), "current_module": p.current_module}

    @app.post("/api/course-versions/{vid}/attempts")
    def begin_exam(vid: str, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db); v = version(db, vid, auth[0]); p = progress(db, vid, auth[0])
        data = content_of(v)
        if not p or (data["exam"]["require_modules"] and not {m["id"] for m in data["modules"] if m["required"]}
                      .issubset(set(json.loads(p.completed_json)))):
            raise HTTPException(409, "Complete the required modules before the final exam")
        existing = list(db.scalars(select(ExamAttempt).where(ExamAttempt.version_id == vid,
                        ExamAttempt.user_id == auth[0].id)))
        current = next((a for a in existing if a.status == "in_progress"), None)
        if current: return attempt_view(db, current, auth[0])
        if any(a.status == "awaiting_review" for a in existing):
            raise HTTPException(409, "Wait for instructor grading before another attempt")
        if len(existing) >= data["exam"]["max_attempts"]:
            raise HTTPException(409, "All permitted exam attempts have been used")
        order = [q['id'] for q in data['exam']['questions']]
        previous = max(existing, key=lambda a: a.created) if existing else None
        previous_order = json.loads(previous.question_order_json) if previous else None
        if previous and not previous_order: previous_order = list(order)
        random.SystemRandom().shuffle(order)
        while len(order) > 1 and order == previous_order:
            random.SystemRandom().shuffle(order)
        a = ExamAttempt(version_id=vid, user_id=auth[0].id, question_order_json=json.dumps(order))
        db.add(a); db.flush(); audit(db, auth[0], "start_exam", a.id); db.commit()
        return attempt_view(db, a, auth[0])

    def validated_answers(questions, answers, submitting=False):
        if set(answers) - {q["id"] for q in questions}:
            raise HTTPException(422, "Answer contains an unknown question")
        for q in questions:
            value = answers.get(q["id"])
            if value is None or value == "":
                if submitting: raise HTTPException(422, "Answer every question before submitting")
                continue
            if q["type"] == "written":
                if not isinstance(value, str) or not value.strip() or len(value) > 20000:
                    raise HTTPException(422, "Written answers must contain 1–20000 characters")
            elif type(value) is not int or not 0 <= value < len(q["choices"]):
                raise HTTPException(422, "Choose a valid answer option")
        return answers

    def score_attempt(a, questions, marks, exam):
        a.marks_json = json.dumps(marks)
        if any(q["id"] not in marks for q in questions):
            a.status, a.score, a.passed = "awaiting_review", None, None
        else:
            a.status = "graded"
            a.score = round(sum(marks.values()) * 100 / sum(q["points"] for q in questions), 2)
            a.passed = a.score >= exam["passing_score"]

    @app.get("/api/exam-attempts/{aid}")
    def read_attempt(aid: str, auth=Depends(identity), db=Depends(get_db)):
        return attempt_view(db, attempt(db, aid, auth[0]), auth[0])

    def write_answers(aid, body, auth, db, submit=False):
        allocation_lock(db); a = attempt(db, aid, auth[0])
        if a.user_id != auth[0].id or a.status != "in_progress":
            raise HTTPException(409, "This attempt can no longer be edited")
        content = content_of(db.get(CourseVersion, a.version_id)); exam = content["exam"]
        answers = validated_answers(exam["questions"], body.answers, submit)
        a.answers_json = json.dumps(answers)
        if submit:
            marks = {q["id"]: q["points"] if answers[q["id"]] == q["correct"] else 0
                     for q in exam["questions"] if q["type"] != "written"}
            a.submitted = time.time(); score_attempt(a, exam["questions"], marks, exam)
            audit(db, auth[0], "submit_exam", a.id)
        db.commit(); return attempt_view(db, a, auth[0])

    @app.put("/api/exam-attempts/{aid}")
    def save_answers(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        return write_answers(aid, body, auth, db)

    @app.post("/api/exam-attempts/{aid}/submit")
    def submit_exam(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        return write_answers(aid, body, auth, db, True)

    @app.get("/api/class-results")
    def my_class_results(auth=Depends(identity), db=Depends(get_db)):
        return {"enrollments": [{"version_id": p.version_id,
                 "title": content_of(db.get(CourseVersion, p.version_id))["title"],
                 "completed": len(json.loads(p.completed_json)),
                 "module_count": len(content_of(db.get(CourseVersion, p.version_id))["modules"])}
                 for p in db.scalars(select(CourseProgress).where(CourseProgress.user_id == auth[0].id))],
                "attempts": [attempt_view(db, a, auth[0]) for a in db.scalars(select(ExamAttempt).where(
                    ExamAttempt.user_id == auth[0].id).order_by(ExamAttempt.created.desc()))]}

    @app.get("/api/admin/exam-attempts")
    def grading_queue(auth=Depends(administrator), db=Depends(get_db)):
        return [attempt_view(db, a, auth[0]) for a in db.scalars(select(ExamAttempt).where(
            ExamAttempt.status == "awaiting_review").order_by(ExamAttempt.submitted))]

    @app.post("/api/admin/exam-attempts/{aid}/grade")
    def grade(aid: str, body: GradeWrite, auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db); a = attempt(db, aid, auth[0])
        if a.status != "awaiting_review":
            raise HTTPException(409, "This exam is not awaiting review")
        if a.user_id == auth[0].id:
            raise HTTPException(409, "Another administrator must grade your own written exam")
        exam = content_of(db.get(CourseVersion, a.version_id))["exam"]
        written = {q["id"]: q for q in exam["questions"] if q["type"] == "written"}
        if set(body.marks) != set(written):
            raise HTTPException(422, "Enter a score for every written answer")
        for qid, mark in body.marks.items():
            if type(mark) not in (int, float) or not 0 <= mark <= written[qid]["points"]:
                raise HTTPException(422, "Each awarded score must be between zero and the question's points")
        marks = {**json.loads(a.marks_json), **body.marks}
        score_attempt(a, exam["questions"], marks, exam)
        a.feedback, a.reviewer_id = body.feedback, auth[0].id
        audit(db, auth[0], "grade_exam", a.id); db.commit()
        return attempt_view(db, a, auth[0])

    @app.post("/api/admin/answer-key-import")
    def import_answer_key(body: AnswerKeyImport, auth=Depends(administrator)):
        reader = csv.DictReader(io.StringIO(body.csv.lstrip("\ufeff")))
        if not {'id', 'correct_answer'}.issubset(set(reader.fieldnames or [])):
            raise HTTPException(422, "Answer-key CSV requires id and correct_answer columns")
        questions = {q.get('id'): dict(q) for q in body.questions}
        if len(questions) != len(body.questions):
            raise HTTPException(422, "Question IDs must be unique")
        seen = set()
        for row in reader:
            qid = (row.get('id') or '').strip()
            if qid not in questions or qid in seen:
                raise HTTPException(422, "Each answer-key ID must match one exam question exactly once")
            seen.add(qid); q = questions[qid]
            key = (row.get('correct_answer') or '').strip().upper()
            if q.get('type') == 'multiple_choice':
                if key not in 'ABCDEFGH' or len(key) != 1:
                    raise HTTPException(422, "Multiple-choice keys must be A–H")
                q['correct'] = ord(key) - ord('A')
            elif q.get('type') == 'true_false':
                if key not in ('TRUE', 'FALSE', 'T', 'F'):
                    raise HTTPException(422, "True/false keys must be True or False")
                q['correct'] = 0 if key in ('TRUE', 'T') else 1
            elif q.get('type') == 'written':
                q['rubric'] = (row.get('rubric') or '').strip()
            if (row.get('points') or '').strip():
                try: q['points'] = int(row['points'])
                except ValueError: raise HTTPException(422, "Points must be a whole number") from None
            if 'explanation' in row: q['explanation'] = row.get('explanation') or ''
            if any('explanation_' + letter in row for letter in 'abcdefgh'):
                q['choice_explanations'] = [row.get('explanation_' + letter) or ''
                                           for letter in 'abcdefgh'[:len(q.get('choices', []))]]
        if seen != set(questions):
            raise HTTPException(422, "Include an answer-key row for every exam question")
        try:
            return {'questions': [Question.model_validate(questions[q['id']]).model_dump() for q in body.questions]}
        except (ValidationError, KeyError, TypeError):
            raise HTTPException(422, "Review answer options, keys, points and written-answer rubrics") from None

    @app.get("/api/admin/exam-import-template.csv")
    def csv_template(auth=Depends(administrator)):
        data = io.StringIO(); writer = csv.writer(data)
        writer.writerow(["id", "type", "prompt", "option_a", "option_b", "option_c", "option_d", "correct_answer", "points", "rubric", "explanation", "explanation_a", "explanation_b", "explanation_c", "explanation_d"])
        writer.writerow(["q1", "multiple_choice", "Which command shows routes?", "ip route", "pwd", "", "", "A", 1, "", "The route table describes available network paths.", "ip route displays the route table.", "pwd displays the current directory, not network routes.", "", ""])
        writer.writerow(["q2", "true_false", "A default route can provide a path beyond the local subnet.", "", "", "", "", "True", 1, "", "The default route is used when no more specific route matches.", "", "", "", ""])
        writer.writerow(["q3", "written", "Explain your troubleshooting approach.", "", "", "", "", "", 5, "Award points for a logical sequence supported by evidence.", "", "", "", "", ""])
        return Response(data.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="exam-question-template.csv"'})

    @app.post("/api/admin/exam-import")
    async def import_exam(request: Request, auth=Depends(administrator)):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1024 * 1024:
                raise HTTPException(413, "Question CSV must be 1 MB or smaller")
        questions = []
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            for row in reader:
                if len(questions) >= 200: raise ValueError("Maximum 200 questions")
                kind = row["type"].strip()
                answer = row["correct_answer"].strip()
                choices = [row.get("option_" + c, "").strip() for c in "abcd"]
                while choices and not choices[-1]: choices.pop()
                correct = None if kind == "written" else (["true", "false"].index(answer.lower())
                          if kind == "true_false" else "ABCD".index(answer.upper()))
                questions.append(Question(id=row["id"].strip(), type=kind, prompt=row["prompt"],
                    choices=choices, correct=correct, points=int(row.get("points") or 1),
                    rubric=row.get("rubric", ""), explanation=row.get('explanation', ''),
                    choice_explanations=[row.get('explanation_' + c, '') for c in 'abcd'[:len(choices)]] if kind == 'multiple_choice' else []).model_dump())
            if not questions or len({q["id"] for q in questions}) != len(questions):
                raise ValueError("Use at least one question with unique IDs")
        except (KeyError, ValueError, UnicodeError, csv.Error, ValidationError):
            raise HTTPException(422, "Check the CSV template, question types, IDs, answer letters and rubrics")
        return {"questions": questions}

    @app.post("/api/admin/labs")
    def add_lab(body: NewLab, auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        if db.get(Lab, body.id):
            raise HTTPException(409, "That lab ID already exists; configure its existing entry")
        values = body.model_dump(); drills = values.pop("drills")
        lab = Lab(**values, enabled=False, drills_json=json.dumps(drills))
        db.add(lab); audit(db, auth[0], "create_lab", lab.id); db.commit()
        return {"id": lab.id, "message": "Lab added inactive. Register and validate its template before activation."}

    @app.post("/api/admin/lab-packages/import")
    def import_lab_package(body: LabPackageReceipt, auth=Depends(administrator), db=Depends(get_db)):
        """Register a receipt produced by the root-only Proxmox package installer."""
        from .proxmox import Proxmox
        adapter = app.state.provider or Proxmox(settings)
        candidate = Lab(template_id=body.template_id)
        try:
            adapter.template_ready(candidate)
        except Exception:
            raise HTTPException(409, "The package template is not available to the Academy on Proxmox")
        allocation_lock(db)
        lab = db.get(Lab, body.id)
        if lab and lab.enabled:
            raise HTTPException(409, "Deactivate the existing lab before replacing it from a package")
        values = body.model_dump(exclude={"schema_version", "package_format", "disk_sha256", "activate", "drills"})
        if not lab:
            lab = Lab(id=body.id, enabled=body.activate)
            db.add(lab)
        for key, value in values.items():
            if key != "id": setattr(lab, key, value)
        lab.drills_json = json.dumps(body.drills)
        lab.enabled = body.activate
        audit(db, auth[0], "import_lab_package", f"{lab.id}:{body.disk_sha256}")
        db.commit()
        return {"id": lab.id, "enabled": lab.enabled, "template_id": lab.template_id,
                "message": "Lab package registered and activated" if lab.enabled else
                           "Lab package registered inactive; activate it after acceptance testing"}
