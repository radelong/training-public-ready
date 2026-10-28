"""Local class authoring, immutable releases, protected content and exam grading."""
import csv
import hashlib
import io
import json
import re
import random
import time
import unicodedata
from pathlib import Path
from typing import Literal
from urllib.parse import unquote
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, model_validator, ValidationError
from sqlalchemy import select, func
from .db import (Course, CourseVersion, ContentAsset, CourseProgress, ModuleQuizAttempt, ProgressTestAttempt, ExamAttempt,
                 AcademyAssessmentAttempt, AcademyAssessmentQuestion, ExamReset, Lab, LearningGame, User, Audit,
                 allocation_lock, uid)

MAX_PDF = 50 * 1024 * 1024
Identifier = str


def normalized_question_prompt(prompt):
    text = unicodedata.normalize("NFKC", str(prompt)).casefold()
    return " ".join(re.findall(r"\w+", text, flags=re.UNICODE))


class Module(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=10000)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    topics: list[str] = Field(default_factory=list, max_length=20)
    asset_id: str | None = Field(default=None, max_length=36)
    lab_id: str | None = Field(default=None, max_length=64)
    quiz: list[dict] = Field(default_factory=list, max_length=100)
    required: bool = True

    @model_validator(mode="after")
    def validate_topics(self):
        if any(not topic.strip() or len(topic) > 120 for topic in self.topics):
            raise ValueError("Module topics must be non-empty and at most 120 characters")
        questions = []
        seen = set()
        for raw in self.quiz:
            question = Question.model_validate(raw)
            if question.type == "written":
                raise ValueError("Module quizzes support only automatically graded objective questions")
            if question.id in seen:
                raise ValueError("Module quiz question IDs must be unique")
            seen.add(question.id)
            questions.append(question.model_dump())
        self.quiz = questions
        return self


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
    estimated_minutes: int | None = Field(default=None, ge=1, le=600)
    passing_score: int = Field(default=80, ge=1, le=100)
    max_attempts: int = Field(default=3, ge=1, le=20)
    require_modules: bool = True
    feedback: Literal["score_only", "after_pass"] = "after_pass"
    questions: list[Question] = Field(default_factory=list, max_length=200)


class CourseContent(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=10000)
    category: Literal["Networking", "Security", "Linux", "Programming", "Cloud", "AI", "Other"] | None = None
    modules: list[Module] = Field(default_factory=list, max_length=100)
    progress_test_enabled: bool = False
    exam: Exam = Field(default_factory=Exam)

    @model_validator(mode="after")
    def unique_ids(self):
        for collection in (self.modules, self.exam.questions):
            if len({v.id for v in collection}) != len(collection):
                raise ValueError("Module and question IDs must be unique within their lists")
        progress_questions = [q for module in self.modules for q in module.quiz]
        if self.progress_test_enabled:
            if len({q["id"] for q in progress_questions}) != len(progress_questions):
                raise ValueError("Pretest question IDs must be unique across the class")
            exam_prompts = {" ".join(q.prompt.casefold().split()) for q in self.exam.questions}
            if any(" ".join(q["prompt"].casefold().split()) in exam_prompts for q in progress_questions):
                raise ValueError("Pretest questions must differ from final exam questions")
            if any(len(module.quiz) < 8 for module in self.modules):
                raise ValueError("Add at least eight pretest questions to every module")
            if len(progress_questions) > 200:
                raise ValueError("A class pretest can contain at most 200 questions")
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


class ExamResetWrite(BaseModel):
    scope: str = Field(min_length=1, max_length=180)


class GradeWrite(BaseModel):
    marks: dict = Field(max_length=200)
    feedback: str = Field(default="", max_length=10000)


class AnswerKeyImport(BaseModel):
    csv: str = Field(max_length=1024 * 1024)
    questions: list[dict] = Field(min_length=1, max_length=200)


class AcademyAssessmentQuestionWrite(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["overall", "graduation"]
    area: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=10000)
    choices: list[str] = Field(min_length=2, max_length=8)
    correct: int = Field(ge=0, le=7)
    points: int = Field(default=1, ge=1, le=100)
    explanation: str = Field(min_length=1, max_length=10000)
    choice_explanations: list[str] = Field(default_factory=list, max_length=8)
    course_categories: list[str] = Field(default_factory=list, max_length=8)
    lab_kinds: list[str] = Field(default_factory=list, max_length=8)
    topics: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_assessment_item(self):
        if self.correct >= len(self.choices) or any(not choice.strip() for choice in self.choices):
            raise ValueError("Choose a valid answer from at least two non-empty options")
        if len({choice.casefold().strip() for choice in self.choices}) != len(self.choices):
            raise ValueError("Answer choices must be distinct")
        if self.choice_explanations and len(self.choice_explanations) != len(self.choices):
            raise ValueError("Choice explanations must match the answer options")
        if any(not value.strip() for value in (self.area, self.prompt, self.explanation, *self.topics)):
            raise ValueError("Area, prompt, explanation and topics must be non-empty")
        return self


class AcademyAssessmentBankWrite(BaseModel):
    questions: list[AcademyAssessmentQuestionWrite] = Field(min_length=1, max_length=200)


class NewLab(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    title: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=10000)
    kind: Literal["netlab", "linux", "networking", "security", "cloud", "programming", "callback", "custom"] = "custom"
    template_id: int = Field(ge=100, le=999999999)
    secondary_template_id: int | None = Field(default=None, ge=100, le=999999999)
    cores: int = Field(default=2, ge=1, le=16)
    memory: int = Field(default=2048, ge=1024, le=32768)
    drills: list[dict] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def valid_drills(self):
        if self.secondary_template_id == self.template_id:
            raise ValueError("Sender and Listener require separate templates")
        if self.kind == "callback" and self.secondary_template_id is None:
            raise ValueError("The callback lab requires separate Sender and Listener templates")
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
    schema_version: Literal[1, 2]
    package_format: Literal["academy-lab-package-v1", "academy-lab-package-v2"]
    disk_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    secondary_disk_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    activate: bool = False

    @model_validator(mode="after")
    def valid_package_version(self):
        paired = self.secondary_template_id is not None
        if (self.schema_version == 2) != (self.package_format == "academy-lab-package-v2"):
            raise ValueError("Package schema and format version must match")
        if paired != (self.secondary_disk_sha256 is not None):
            raise ValueError("Paired packages require a secondary image checksum")
        if paired and self.schema_version != 2:
            raise ValueError("Paired packages require schema version 2")
        return self


def learner_content(content):
    # Explicit allowlist: answer keys and rubrics never travel in learner lessons.
    content = json.loads(json.dumps(content))
    for module in content["modules"]:
        module["quiz"] = [
            {k: q[k] for k in ("id", "type", "prompt", "choices", "points")}
            for q in module.get("quiz", [])]
    content["exam"]["questions"] = [
        {k: q[k] for k in ("id", "type", "prompt", "choices", "points")}
        for q in content["exam"]["questions"]]
    return content


def mount_learning(app, factory, settings, identity, administrator, get_db):
    folder = Path(settings.content_dir)

    def audit(db, user, action, target):
        db.add(Audit(user_id=user.id, action=action, target=target))

    def reset_cutoff(db, user_id, scope):
        return db.scalar(select(func.max(ExamReset.created)).where(
            ExamReset.user_id == user_id, ExamReset.scope.in_(("all", scope)))) or 0

    def reset_is_current(db, item, scope):
        return item.created > reset_cutoff(db, item.user_id, scope)

    def pending_pretest_reset(db, user_id, vid):
        marker = db.scalars(select(ExamReset).where(
            ExamReset.user_id == user_id, ExamReset.scope == f"pretest:{vid}")
            .order_by(ExamReset.created.desc())).first()
        if not marker or marker.consumed:
            return None
        latest = db.scalar(select(func.max(ProgressTestAttempt.created)).where(
            ProgressTestAttempt.user_id == user_id, ProgressTestAttempt.version_id == vid)) or 0
        return marker if marker.created > latest else None

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

    def assessment_area(content, module, lab=None, question=None):
        title = str(content.get("title") or "").casefold()
        for terms, area in (
            (("active directory",), "Active Directory"),
            (("python",), "Python"),
            (("prompt engineering",), "AI and prompt engineering"),
            (("kubernetes", "netlab", "network"), "Networking"),
            (("linux",), "Linux"),
            (("security",), "Security"),
        ):
            if any(term in title for term in terms):
                return area
        text = " ".join(str(value or "") for value in (
            content.get("title"), content.get("category"), module.get("title"),
            " ".join(module.get("topics", [])), module.get("description"),
            lab.title if lab else "", lab.kind if lab else "",
            " ".join(item.get("title", "") for item in json.loads(lab.drills_json)) if lab else "",
            question.get("prompt") if question else "")).casefold()
        if any(term in text for term in ("kubernetes", "k8s", "container", "netlab")):
            return "Networking"
        if any(term in text for term in ("active directory", "windows domain", "domain controller", "group policy")):
            return "Active Directory"
        if any(term in text for term in ("security", "siem", "incident", "threat")):
            return "Security"
        if any(term in text for term in ("aws", "azure", "cloud", "vpc", "vnet", "ec2")):
            return "Cloud"
        if any(term in text for term in ("vmware", "virtualization", "hypervisor", "proxmox")):
            return "Virtualization"
        if any(term in text for term in ("terraform", "ansible", "automation", "infrastructure as code")):
            return "Automation and infrastructure as code"
        if any(term in text for term in ("linux", "ubuntu", "shell", "bash", "systemd")):
            return "Linux"
        if "python" in text:
            return "Python"
        if any(term in text for term in ("network", "routing", "switch", "firewall", "tcp", "dns", "dhcp")):
            return "Networking"
        category = str(content.get("category") or "").strip()
        return {"AI": "AI and prompt engineering", "Cloud": "Cloud", "Security": "Security",
                "Linux": "Linux", "Networking": "Networking", "Programming": "Python"}.get(category, "IT fundamentals")

    def assessment_bank(db, kind=None):
        query = select(AcademyAssessmentQuestion)
        if kind:
            query = query.where(AcademyAssessmentQuestion.kind == kind)
        return [{"id": row.id, "kind": row.kind, "area": row.area, "prompt": row.prompt,
            "choices": json.loads(row.choices_json), "correct": row.correct, "points": row.points,
            "explanation": row.explanation, "choice_explanations": json.loads(row.choice_explanations_json),
            "course_categories": json.loads(row.course_categories_json), "lab_kinds": json.loads(row.lab_kinds_json),
            "topics": json.loads(row.topics_json)}
            for row in db.scalars(query.order_by(AcademyAssessmentQuestion.area, AcademyAssessmentQuestion.id))]

    def select_assessment_questions(bank):
        rng = random.SystemRandom()
        selected = []
        for source in bank:
            question = source.copy()
            choices = list(question["choices"])
            explanations = list(question.get("choice_explanations", []))
            indices = list(range(len(choices)))
            rng.shuffle(indices)
            question["choices"] = [choices[index] for index in indices]
            question["correct"] = indices.index(source["correct"])
            if explanations:
                question["choice_explanations"] = [explanations[index] for index in indices]
            selected.append(question)
        rng.shuffle(selected)
        return selected

    def assessment_recommendations(db, area_scores):
        weak_areas = [area for area, score in sorted(area_scores.items(), key=lambda pair: (pair[1]["score"], pair[0]))
                      if score["score"] < 80]
        if not weak_areas and area_scores:
            weak_areas = [area for area, _ in sorted(area_scores.items(), key=lambda pair: (pair[1]["score"], pair[0]))[:2]]
        available = []
        for course_row in db.scalars(select(Course).where(Course.published_id.is_not(None))):
            version_row = db.get(CourseVersion, course_row.published_id)
            if version_row:
                available.append((course_row, content_of(version_row)))
        def course_rank(item):
            title = item[1]["title"].casefold()
            return (0 if any(word in title for word in ("beginner", "foundation", "fundamentals", "introduction", "101"))
                    else 2 if any(word in title for word in ("advanced", "expert")) else 1, title)
        recommendations, added = [], set()
        for area in weak_areas:
            area_detail = area_scores[area]
            course_categories = set(area_detail.get("course_categories", []))
            lab_kinds = set(area_detail.get("lab_kinds", []))
            matching = []
            for course_row, content in available:
                module_areas = [assessment_area(content, module,
                    db.get(Lab, module.get("lab_id")) if module.get("lab_id") else None) for module in content.get("modules", [])]
                if content.get("category") in course_categories or assessment_area(content, {"title": "", "topics": []}) == area or area in module_areas:
                    matching.append((course_row, content))
            for course_row, content in sorted(matching, key=course_rank):
                key = ("class", course_row.id)
                if key not in added:
                    recommendations.append({"type": "class", "id": course_row.published_id, "title": content["title"],
                        "area": area, "area_score": area_detail["score"],
                        "reason": "Strengthen this area with the published class and its ordered modules."})
                    added.add(key)
                for module in content.get("modules", []):
                    lab = db.get(Lab, module.get("lab_id")) if module.get("lab_id") else None
                    if not lab or lab.id in added:
                        continue
                    if lab.kind in lab_kinds or assessment_area(content, module, lab) == area or assessment_area({"title": lab.title}, {"title": "", "topics": []}, lab) == area:
                        recommendations.append({"type": "lab", "id": lab.id, "title": lab.title, "area": area,
                            "area_score": area_detail["score"], "available": lab.enabled,
                            "reason": "Take this hands-on lab after the related class."})
                        added.add(lab.id)
            for lab in db.scalars(select(Lab)):
                if (lab.kind in lab_kinds or assessment_area({"title": lab.title}, {"title": "", "topics": []}, lab) == area) and lab.id not in added:
                    recommendations.append({"type": "lab", "id": lab.id, "title": lab.title, "area": area,
                        "area_score": area_detail["score"], "available": lab.enabled,
                        "reason": "Practice this area in the hands-on lab after the recommended class."})
                    added.add(lab.id)
            for game in db.scalars(select(LearningGame)):
                game_area = assessment_area({"title": game.title, "category": game.category},
                                            {"title": game.description, "topics": []})
                key = ("game", game.id)
                if game_area == area and key not in added:
                    recommendations.append({"type": "game", "id": game.id, "title": game.title, "area": area,
                        "area_score": area_detail["score"],
                        "reason": "Practice this area with this interactive learning game."})
                    added.add(key)
        return recommendations

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
        if publishing and any(not module.quiz for module in content.modules):
            raise HTTPException(422, "Add at least one module knowledge-check question to every module before publishing")
        if publishing and any(q.type != 'written' and not q.explanation.strip() for q in content.exam.questions):
            raise HTTPException(422, "Add an explanation for every objective question before publishing")
        if publishing and any(not question.get("explanation", "").strip()
                              for module in content.modules for question in module.quiz):
            raise HTTPException(422, "Add an explanation for every module question before publishing")
        if publishing and content.progress_test_enabled and any(len(module.quiz) < 8 for module in content.modules):
            raise HTTPException(422, "Add at least eight pretest questions to every module before publishing")

    def draft_view(c):
        return {"id": c.id, "revision": c.revision, "published_id": c.published_id,
                "content": json.loads(c.draft_json)}

    def attempt_view(db, a, user):
        content = content_of(db.get(CourseVersion, a.version_id))
        reviewing = user.role == "admin" and user.id != a.user_id
        reveal = a.status != "in_progress"
        display_status = ("closed" if a.status == "in_progress" and not reset_is_current(
            db, a, f"final:{a.version_id}") else a.status)
        result = {"id": a.id, "version_id": a.version_id, "title": content["title"],
                  "instructions": content["exam"].get("instructions", ""),
                  "status": display_status, "score": a.score, "passed": a.passed,
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

    def module_quiz_attempt(db, aid, user):
        value = db.get(ModuleQuizAttempt, aid)
        if not value or value.user_id != user.id:
            raise HTTPException(404, "Module quiz attempt not found")
        return value

    def progress_test_attempt(db, aid, user):
        value = db.get(ProgressTestAttempt, aid)
        if not value or value.user_id != user.id:
            raise HTTPException(404, "Progress test attempt not found")
        return value

    def academy_assessment_attempt(db, aid, user):
        value = db.get(AcademyAssessmentAttempt, aid)
        if not value or (value.user_id != user.id and user.role != "admin"):
            raise HTTPException(404, "Academy assessment attempt not found")
        return value

    def academy_assessment_view(attempt, reveal=False, include_user=None, db=None):
        snapshot = json.loads(attempt.question_snapshot_json)
        order = json.loads(attempt.question_order_json)
        positions = {qid: index for index, qid in enumerate(order)}
        answers = json.loads(attempt.answers_json)
        questions = []
        for question in sorted(snapshot, key=lambda item: positions.get(item["id"], len(positions))):
            public = {key: question[key] for key in ("id", "prompt", "choices", "points")}
            if reveal:
                selected = answers.get(question["id"])
                choices = question.get("choice_explanations", [])
                public.update({"area": question["area"], "topics": question.get("topics", []),
                    "explanation": question.get("explanation", ""),
                    "selected_explanation": choices[selected] if type(selected) is int and selected < len(choices) else ""})
            questions.append(public)
        result = {"id": attempt.id, "kind": attempt.kind, "status": attempt.status,
            "score": attempt.score, "passed": attempt.passed, "created": attempt.created,
            "submitted": attempt.submitted, "answers": answers, "questions": questions,
            "area_scores": json.loads(attempt.area_scores_json),
            "recommendations": json.loads(attempt.recommendations_json) if reveal else []}
        if reveal and db is not None and attempt.kind == "overall" and result["area_scores"]:
            # Use the current published catalog for both new and earlier results.
            result["recommendations"] = assessment_recommendations(db, result["area_scores"])
        if reveal:
            result["marks"] = json.loads(attempt.marks_json)
            result["correct_answers"] = {item["id"]: item["correct"] for item in snapshot}
        if include_user is not None:
            result["username"] = include_user
        return result

    def assessment_summary(attempt):
        return {"id": attempt.id, "kind": attempt.kind, "status": attempt.status,
            "score": attempt.score, "passed": attempt.passed, "created": attempt.created,
            "submitted": attempt.submitted, "area_scores": json.loads(attempt.area_scores_json),
            "recommendations": json.loads(attempt.recommendations_json)}

    def progress_questions(content):
        return [(module, question) for module in content["modules"]
                for question in module.get("quiz", [])]

    def progress_test_view(db, attempt):
        content = content_of(db.get(CourseVersion, attempt.version_id))
        pairs = progress_questions(content)
        questions = [{**{k: q[k] for k in ("id", "type", "prompt", "choices", "points")},
                      "module_id": module["id"], "module_title": module["title"]}
                     for module, q in pairs]
        result = {"id": attempt.id, "version_id": attempt.version_id, "status": attempt.status,
                  "score": attempt.score, "answers": json.loads(attempt.answers_json),
                  "questions": questions}
        if attempt.status != "in_progress":
            result["marks"] = json.loads(attempt.marks_json)
            result["module_results"] = json.loads(attempt.module_results_json)
            result["correct_answers"] = {q["id"]: q["correct"] for _, q in pairs}
            answers = json.loads(attempt.answers_json)
            for question, (_, original) in zip(questions, pairs):
                selected = answers.get(question["id"])
                options = original.get("choice_explanations", [])
                question["explanation"] = original.get("explanation", "")
                question["selected_explanation"] = (options[selected] if type(selected) is int
                                                       and selected < len(options) else "")
        positions = {qid: i for i, qid in enumerate(json.loads(attempt.question_order_json))}
        result["questions"].sort(key=lambda q: positions.get(q["id"], len(positions)))
        return result

    def module_quiz_view(db, attempt, user):
        content = content_of(db.get(CourseVersion, attempt.version_id))
        module = next((m for m in content["modules"] if m["id"] == attempt.module_id), None)
        if not module:
            raise HTTPException(404, "Module quiz not found")
        questions = module.get("quiz", [])
        result = {"id": attempt.id, "version_id": attempt.version_id,
                  "module_id": attempt.module_id, "module_title": module["title"],
                  "status": attempt.status, "score": attempt.score, "passed": attempt.passed,
                  "passing_score": 80, "answers": json.loads(attempt.answers_json),
                  "questions": [{k: q[k] for k in ("id", "type", "prompt", "choices", "points")}
                                 for q in questions]}
        if attempt.status != "in_progress":
            answers = json.loads(attempt.answers_json)
            result["marks"] = json.loads(attempt.marks_json)
            result["correct_answers"] = {q["id"]: q["correct"] for q in questions}
            for question in result["questions"]:
                original = next(q for q in questions if q["id"] == question["id"])
                selected = answers.get(question["id"])
                options = original.get("choice_explanations", [])
                question["explanation"] = original.get("explanation", "")
                question["selected_explanation"] = (options[selected] if type(selected) is int
                                                       and selected < len(options) else "")
        order = json.loads(attempt.question_order_json)
        positions = {qid: i for i, qid in enumerate(order)}
        result["questions"].sort(key=lambda q: positions.get(q["id"], len(positions)))
        return result

    @app.get("/api/courses")
    def classes(auth=Depends(identity), db=Depends(get_db)):
        result = []
        for c in db.scalars(select(Course).where(Course.published_id.is_not(None)).order_by(Course.created.desc())):
            v = db.get(CourseVersion, c.published_id)
            data = content_of(v)
            p = progress(db, v.id, auth[0])
            category = data.get("category") or next(
                (name for name in ("Networking", "Security", "Linux", "Programming", "Cloud", "AI")
                 if name.casefold() in data["title"].casefold()), "Other")
            if category == "Other" and "python" in data["title"].casefold():
                category = "Programming"
            module_durations = [module.get("estimated_minutes") for module in data["modules"]]
            exam_duration = data["exam"].get("estimated_minutes")
            expected_minutes = (sum(module_durations) + exam_duration
                                if exam_duration is not None and all(value is not None for value in module_durations)
                                else None)
            topics = sorted({topic.strip() for module in data["modules"]
                             for topic in module.get("topics", []) if topic.strip()})
            result.append({"id": c.id, "version_id": v.id, "number": v.number, "title": data["title"],
                           "category": category,
                           "description": data["description"], "module_count": len(data["modules"]),
                           "pretest_enabled": bool(data.get("progress_test_enabled")),
                           "estimated_minutes": expected_minutes, "key_topics": topics,
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
        quiz_results = {}
        for attempt in db.scalars(select(ModuleQuizAttempt).where(
                ModuleQuizAttempt.version_id == vid, ModuleQuizAttempt.user_id == auth[0].id)
                .order_by(ModuleQuizAttempt.created.desc())):
            if not reset_is_current(db, attempt, f"quiz:{vid}:{attempt.module_id}"):
                continue
            if attempt.module_id not in quiz_results:
                quiz_results[attempt.module_id] = {"attempt_id": attempt.id, "status": attempt.status,
                                                   "score": attempt.score, "passed": bool(attempt.passed),
                                                   "best_score": attempt.score}
            else:
                item = quiz_results[attempt.module_id]
                item["passed"] = item["passed"] or bool(attempt.passed)
                if attempt.score is not None:
                    item["best_score"] = max(item["best_score"] or 0, attempt.score)
        progress_attempts = list(db.scalars(select(ProgressTestAttempt).where(
            ProgressTestAttempt.version_id == vid, ProgressTestAttempt.user_id == auth[0].id)
            .order_by(ProgressTestAttempt.created.desc())))
        current_progress_attempts = [item for item in progress_attempts
                                     if reset_is_current(db, item, f"pretest:{vid}")]
        pretest_reopened = pending_pretest_reset(db, auth[0].id, vid) is not None
        return {"id": v.id, "course_id": v.course_id, "number": v.number,
                "content": learner_content(content_of(v)),
                "completed": json.loads(p.completed_json) if p else [],
                "current_module": p.current_module if p else "",
                "module_quiz_results": quiz_results,
                "pretest_available": bool(content_of(v).get("progress_test_enabled") and
                    (not p.current_module or pretest_reopened)),
                "progress_test_attempt": progress_test_view(db, current_progress_attempts[0])
                    if current_progress_attempts else None,
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
        module = next((m for m in content_of(v)["modules"] if m["id"] == body.module_id), None)
        if not module:
            raise HTTPException(422, "Module not found")
        content = content_of(v)
        completed = set(json.loads(p.completed_json))
        if not earlier_required_modules_complete(content, completed, body.module_id):
            raise HTTPException(409, "Complete earlier required modules before advancing")
        passed_quiz = any(item.passed and reset_is_current(db, item, f"quiz:{vid}:{body.module_id}")
                          for item in db.scalars(select(ModuleQuizAttempt).where(
                              ModuleQuizAttempt.version_id == vid, ModuleQuizAttempt.module_id == body.module_id,
                              ModuleQuizAttempt.user_id == auth[0].id)))
        if body.complete and module.get("quiz") and body.module_id not in completed and not passed_quiz:
            raise HTTPException(409, "Pass this module's quiz before marking it complete")
        if body.complete: completed.add(body.module_id)
        p.completed_json, p.current_module = json.dumps(sorted(completed)), body.module_id
        pending = pending_pretest_reset(db, auth[0].id, vid)
        if pending:
            pending.consumed = True
            audit(db, auth[0], "skip_reset_pretest", vid)
        db.commit(); return {"completed": sorted(completed), "current_module": p.current_module}

    @app.post("/api/course-versions/{vid}/attempts")
    def begin_exam(vid: str, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db); v = version(db, vid, auth[0]); p = progress(db, vid, auth[0])
        data = content_of(v)
        if not p or (data["exam"]["require_modules"] and not {m["id"] for m in data["modules"] if m["required"]}
                      .issubset(set(json.loads(p.completed_json)))):
            raise HTTPException(409, "Complete the required modules before the final exam")
        existing = [item for item in db.scalars(select(ExamAttempt).where(
            ExamAttempt.version_id == vid, ExamAttempt.user_id == auth[0].id))
            if reset_is_current(db, item, f"final:{vid}")]
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

    def module_quiz_questions(db, vid, module_id, user):
        v = version(db, vid, user)
        module = next((m for m in content_of(v)["modules"] if m["id"] == module_id), None)
        if not module or not module.get("quiz"):
            raise HTTPException(404, "Module quiz not found")
        return module["quiz"]

    def earlier_required_modules_complete(content, completed, module_id):
        modules = content["modules"]
        index = next((i for i, item in enumerate(modules) if item["id"] == module_id), None)
        return index is not None and all(not item["required"] or item["id"] in completed
                                         for item in modules[:index])

    @app.post("/api/course-versions/{vid}/modules/{module_id}/quiz-attempts")
    def begin_module_quiz(vid: str, module_id: str, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db)
        enrollment = progress(db, vid, auth[0])
        if not enrollment:
            raise HTTPException(409, "Open the class before starting a module quiz")
        content = content_of(version(db, vid, auth[0]))
        completed = set(json.loads(enrollment.completed_json))
        if not earlier_required_modules_complete(content, completed, module_id):
            raise HTTPException(409, "Complete earlier required modules before taking this quiz")
        questions = module_quiz_questions(db, vid, module_id, auth[0])
        existing = [item for item in db.scalars(select(ModuleQuizAttempt).where(
            ModuleQuizAttempt.version_id == vid, ModuleQuizAttempt.module_id == module_id,
            ModuleQuizAttempt.user_id == auth[0].id).order_by(ModuleQuizAttempt.created.desc()))
            if reset_is_current(db, item, f"quiz:{vid}:{module_id}")]
        current = next((item for item in existing if item.status == "in_progress"), None)
        if current:
            return module_quiz_view(db, current, auth[0])
        order = [q["id"] for q in questions]
        previous_order = json.loads(existing[0].question_order_json) if existing else None
        random.SystemRandom().shuffle(order)
        if len(order) > 1 and order == previous_order:
            order = order[1:] + order[:1]
        attempt = ModuleQuizAttempt(version_id=vid, module_id=module_id, user_id=auth[0].id,
                                    question_order_json=json.dumps(order))
        db.add(attempt); db.flush(); audit(db, auth[0], "start_module_quiz", attempt.id); db.commit()
        return module_quiz_view(db, attempt, auth[0])

    @app.get("/api/module-quiz-attempts/{aid}")
    def read_module_quiz(aid: str, auth=Depends(identity), db=Depends(get_db)):
        item = module_quiz_attempt(db, aid, auth[0])
        if item.status == "in_progress" and not reset_is_current(db, item,
                f"quiz:{item.version_id}:{item.module_id}"):
            raise HTTPException(409, "This attempt was closed by an administrator reset")
        return module_quiz_view(db, item, auth[0])

    def write_module_quiz(aid, body, auth, db, submit=False):
        allocation_lock(db)
        attempt = module_quiz_attempt(db, aid, auth[0])
        if attempt.status != "in_progress" or not reset_is_current(db, attempt,
                f"quiz:{attempt.version_id}:{attempt.module_id}"):
            raise HTTPException(409, "This module quiz attempt is already submitted")
        questions = module_quiz_questions(db, attempt.version_id, attempt.module_id, auth[0])
        answers = validated_answers(questions, body.answers, submit)
        attempt.answers_json = json.dumps(answers)
        if submit:
            marks = {q["id"]: q["points"] if answers[q["id"]] == q["correct"] else 0
                     for q in questions}
            attempt.marks_json = json.dumps(marks)
            attempt.score = round(sum(marks.values()) * 100 / sum(q["points"] for q in questions), 2)
            attempt.passed = attempt.score >= 80
            attempt.status, attempt.submitted = "graded", time.time()
            audit(db, auth[0], "submit_module_quiz", attempt.id)
            if attempt.passed:
                enrollment = progress(db, attempt.version_id, auth[0])
                completed = set(json.loads(enrollment.completed_json))
                completed.add(attempt.module_id)
                enrollment.completed_json = json.dumps(sorted(completed))
                enrollment.current_module = attempt.module_id
        db.commit()
        return module_quiz_view(db, attempt, auth[0])

    @app.put("/api/module-quiz-attempts/{aid}")
    def save_module_quiz(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        return write_module_quiz(aid, body, auth, db)

    @app.post("/api/module-quiz-attempts/{aid}/submit")
    def submit_module_quiz(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        return write_module_quiz(aid, body, auth, db, True)

    @app.post("/api/course-versions/{vid}/progress-test-attempts")
    def begin_progress_test(vid: str, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db)
        v = version(db, vid, auth[0]); p = progress(db, vid, auth[0]); content = content_of(v)
        if not p:
            raise HTTPException(409, "Open the class before starting its pretest")
        if not content.get("progress_test_enabled"):
            raise HTTPException(404, "This class has no pretest")
        pairs = progress_questions(content)
        if not pairs or any(len(module.get("quiz", [])) < 8 for module in content["modules"]):
            raise HTTPException(409, "The class pretest is not configured for every module")
        attempts = [item for item in db.scalars(select(ProgressTestAttempt).where(
            ProgressTestAttempt.version_id == vid, ProgressTestAttempt.user_id == auth[0].id)
            .order_by(ProgressTestAttempt.created.desc()))
            if reset_is_current(db, item, f"pretest:{vid}")]
        current = next((item for item in attempts if item.status == "in_progress"), None)
        if current:
            db.commit()
            return progress_test_view(db, current)
        if p.current_module and not pending_pretest_reset(db, auth[0].id, vid):
            raise HTTPException(409, "The class pretest is only available when the class first opens")
        p.current_module = content["modules"][0]["id"]
        order = [q["id"] for _, q in pairs]
        previous_order = json.loads(attempts[0].question_order_json) if attempts else None
        random.SystemRandom().shuffle(order)
        if len(order) > 1 and order == previous_order:
            order = order[1:] + order[:1]
        attempt = ProgressTestAttempt(version_id=vid, user_id=auth[0].id,
                                      question_order_json=json.dumps(order))
        db.add(attempt); db.flush(); audit(db, auth[0], "start_progress_test", attempt.id); db.commit()
        return progress_test_view(db, attempt)

    @app.post("/api/progress-test-attempts/{aid}/submit")
    def submit_progress_test(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db)
        attempt = progress_test_attempt(db, aid, auth[0])
        if attempt.status != "in_progress" or not reset_is_current(db, attempt,
                f"pretest:{attempt.version_id}"):
            raise HTTPException(409, "This pretest attempt is already submitted")
        version_row = db.get(CourseVersion, attempt.version_id); content = content_of(version_row)
        pairs = progress_questions(content)
        questions = [question for _, question in pairs]
        answers = validated_answers(questions, body.answers, True)
        marks = {q["id"]: q["points"] if answers[q["id"]] == q["correct"] else 0 for q in questions}
        module_results = {}
        completed = set(json.loads(progress(db, attempt.version_id, auth[0]).completed_json))
        for module in content["modules"]:
            module_questions = module["quiz"]
            earned = sum(marks[q["id"]] for q in module_questions)
            possible = sum(q["points"] for q in module_questions)
            perfect = earned == possible
            module_results[module["id"]] = {"score": round(earned * 100 / possible, 2),
                                             "question_count": len(module_questions), "perfect": perfect}
            if perfect:
                completed.add(module["id"])
        p = progress(db, attempt.version_id, auth[0])
        p.completed_json = json.dumps(sorted(completed))
        attempt.answers_json = json.dumps(answers); attempt.marks_json = json.dumps(marks)
        attempt.module_results_json = json.dumps(module_results)
        attempt.score = round(sum(marks.values()) * 100 / sum(q["points"] for q in questions), 2)
        attempt.status = "graded"; attempt.submitted = time.time()
        audit(db, auth[0], "submit_progress_test", attempt.id)
        db.commit()
        return progress_test_view(db, attempt)

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
        if a.user_id != auth[0].id or a.status != "in_progress" or not reset_is_current(
                db, a, f"final:{a.version_id}"):
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
        quiz_attempts = []
        for item in db.scalars(select(ModuleQuizAttempt).where(
                ModuleQuizAttempt.user_id == auth[0].id).order_by(ModuleQuizAttempt.created.desc())):
            content = content_of(db.get(CourseVersion, item.version_id))
            module = next((m for m in content["modules"] if m["id"] == item.module_id), None)
            if module:
                quiz_attempts.append({"id": item.id, "version_id": item.version_id,
                    "class_title": content["title"], "module_id": item.module_id,
                    "module_title": module["title"], "status": "closed" if item.status == "in_progress"
                    and not reset_is_current(db, item, f"quiz:{item.version_id}:{item.module_id}")
                    else item.status,
                    "score": item.score, "passed": item.passed, "created": item.created})
        pretest_attempts = []
        for item in db.scalars(select(ProgressTestAttempt).where(
                ProgressTestAttempt.user_id == auth[0].id).order_by(ProgressTestAttempt.created.desc())):
            content = content_of(db.get(CourseVersion, item.version_id))
            pretest_attempts.append({"id": item.id, "version_id": item.version_id,
                "class_title": content["title"], "status": "closed" if item.status == "in_progress"
                and not reset_is_current(db, item, f"pretest:{item.version_id}") else item.status,
                "score": item.score, "created": item.created})
        return {"enrollments": [{"version_id": p.version_id,
                 "title": content_of(db.get(CourseVersion, p.version_id))["title"],
                 "completed": len(json.loads(p.completed_json)),
                 "module_count": len(content_of(db.get(CourseVersion, p.version_id))["modules"])}
                 for p in db.scalars(select(CourseProgress).where(CourseProgress.user_id == auth[0].id))],
                "module_quiz_attempts": quiz_attempts,
                "pretest_attempts": pretest_attempts,
                "attempts": [attempt_view(db, a, auth[0]) for a in db.scalars(select(ExamAttempt).where(
                    ExamAttempt.user_id == auth[0].id).order_by(ExamAttempt.created.desc()))]}

    @app.get("/api/academy-assessments")
    def academy_assessment_catalog(auth=Depends(identity), db=Depends(get_db)):
        bank = assessment_bank(db)
        area_counts, total_counts = {}, {"overall": 0, "graduation": 0}
        for question in bank:
            total_counts[question["kind"]] += 1
            area_counts.setdefault(question["kind"], {})
            area_counts[question["kind"]][question["area"]] = area_counts[question["kind"]].get(question["area"], 0) + 1
        attempts = list(db.scalars(select(AcademyAssessmentAttempt).where(
            AcademyAssessmentAttempt.user_id == auth[0].id).order_by(AcademyAssessmentAttempt.created.desc())))
        return {"max_questions": 100, "passing_score": 80,
                "assessments": {kind: {"question_count": total_counts[kind], "area_count": len(area_counts.get(kind, {}))}
                                for kind in ("overall", "graduation")},
                "attempts": [{**assessment_summary(item), "status": "closed" if
                    item.status == "in_progress" and not reset_is_current(db, item,
                    f"assessment:{item.kind}") else item.status} for item in attempts]}

    @app.post("/api/academy-assessments/{kind}/attempts")
    def begin_academy_assessment(kind: str, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db)
        if kind not in ("overall", "graduation"):
            raise HTTPException(404, "Academy assessment not found")
        existing = [item for item in db.scalars(select(AcademyAssessmentAttempt).where(
            AcademyAssessmentAttempt.user_id == auth[0].id,
            AcademyAssessmentAttempt.kind == kind).order_by(AcademyAssessmentAttempt.created.desc()))
            if reset_is_current(db, item, f"assessment:{kind}")]
        current = next((item for item in existing if item.status == "in_progress"), None)
        if current:
            return academy_assessment_view(current)
        selected = select_assessment_questions(assessment_bank(db, kind))
        if not selected:
            raise HTTPException(409, "The administrator has not loaded the separate Academy assessment question bank yet")
        order = [item["id"] for item in selected]
        previous_order = json.loads(existing[0].question_order_json) if existing else []
        if len(order) > 1 and order == previous_order:
            order.reverse()
        attempt = AcademyAssessmentAttempt(user_id=auth[0].id, kind=kind,
            question_snapshot_json=json.dumps(selected), question_order_json=json.dumps(order))
        db.add(attempt); db.flush(); audit(db, auth[0], "start_academy_assessment", f"{kind}:{attempt.id}")
        db.commit()
        return academy_assessment_view(attempt)

    def write_academy_assessment(aid, body, auth, db, submit=False):
        allocation_lock(db)
        attempt = academy_assessment_attempt(db, aid, auth[0])
        if attempt.user_id != auth[0].id or attempt.status != "in_progress" or not reset_is_current(
                db, attempt, f"assessment:{attempt.kind}"):
            raise HTTPException(409, "This assessment attempt can no longer be edited")
        snapshot = json.loads(attempt.question_snapshot_json)
        question_ids = {question["id"] for question in snapshot}
        answers = body.answers
        if set(answers) - question_ids:
            raise HTTPException(422, "Answer contains an unknown question")
        for question in snapshot:
            answer = answers.get(question["id"])
            if answer is None:
                if submit:
                    raise HTTPException(422, "Answer every question before submitting")
            elif type(answer) is not int or not 0 <= answer < len(question["choices"]):
                raise HTTPException(422, "Choose a valid answer option")
        attempt.answers_json = json.dumps(answers)
        if submit:
            marks = {question["id"]: question["points"] if answers[question["id"]] == question["correct"] else 0
                     for question in snapshot}
            area_scores = {}
            for question in snapshot:
                area = area_scores.setdefault(question["area"], {"earned": 0, "possible": 0, "correct": 0,
                    "question_count": 0, "course_categories": [], "lab_kinds": [], "topics": []})
                area["earned"] += marks[question["id"]]
                area["possible"] += question["points"]
                area["correct"] += int(marks[question["id"]] > 0)
                area["question_count"] += 1
                for field in ("course_categories", "lab_kinds", "topics"):
                    area[field] = sorted(set(area[field]) | set(question.get(field, [])))
            for value in area_scores.values():
                value["score"] = round(value["earned"] * 100 / value["possible"], 2)
            total_possible = sum(question["points"] for question in snapshot)
            attempt.score = round(sum(marks.values()) * 100 / total_possible, 2)
            attempt.passed = attempt.score >= 80 if attempt.kind == "graduation" else None
            attempt.marks_json = json.dumps(marks)
            attempt.area_scores_json = json.dumps(area_scores)
            attempt.recommendations_json = json.dumps(assessment_recommendations(
                db, area_scores) if attempt.kind == "overall" else [])
            attempt.status, attempt.submitted = "graded", time.time()
            audit(db, auth[0], "submit_academy_assessment", f"{attempt.kind}:{attempt.id}")
        db.commit()
        return academy_assessment_view(attempt, reveal=submit or attempt.status == "graded", db=db)

    @app.get("/api/academy-assessments/attempts/{aid}")
    def read_academy_assessment(aid: str, auth=Depends(identity), db=Depends(get_db)):
        item = academy_assessment_attempt(db, aid, auth[0])
        if item.status == "in_progress" and not reset_is_current(db, item,
                f"assessment:{item.kind}"):
            raise HTTPException(409, "This attempt was closed by an administrator reset")
        owner = db.get(User, item.user_id) if auth[0].role == "admin" and item.user_id != auth[0].id else None
        return academy_assessment_view(item, reveal=item.status == "graded",
                                       include_user=owner.username if owner else None, db=db)

    @app.put("/api/academy-assessments/attempts/{aid}")
    def save_academy_assessment(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        return write_academy_assessment(aid, body, auth, db)

    @app.post("/api/academy-assessments/attempts/{aid}/submit")
    def submit_academy_assessment(aid: str, body: AnswerWrite, auth=Depends(identity), db=Depends(get_db)):
        return write_academy_assessment(aid, body, auth, db, True)

    @app.get("/api/admin/academy-assessment-results")
    def admin_academy_assessment_results(auth=Depends(administrator), db=Depends(get_db)):
        rows = list(db.scalars(select(AcademyAssessmentAttempt).order_by(AcademyAssessmentAttempt.created)))
        previous, results = {}, []
        for item in rows:
            username = db.get(User, item.user_id).username
            key = (item.user_id, item.kind)
            prior = previous.setdefault(key, {})
            area_scores = json.loads(item.area_scores_json)
            growth = {area: None if area not in prior else round(value["score"] - prior[area], 2)
                      for area, value in area_scores.items()}
            previous[key] = {area: value["score"] for area, value in area_scores.items()}
            results.append({**assessment_summary(item), "username": username, "area_growth": growth})
        return list(reversed(results))

    def exam_reset_options(db, user_id):
        options = [
            {"scope": f"assessment:{kind}", "label": label}
            for kind, label in (("overall", "Academy Overall assessment"),
                                ("graduation", "Academy Graduation assessment"))]
        version_ids = {item.version_id for item in db.scalars(select(CourseProgress).where(
            CourseProgress.user_id == user_id))}
        for model in (ExamAttempt, ProgressTestAttempt, ModuleQuizAttempt):
            version_ids.update(item.version_id for item in db.scalars(select(model).where(
                model.user_id == user_id)))
        for vid in sorted(version_ids):
            row = db.get(CourseVersion, vid)
            if not row:
                continue
            content = content_of(row)
            name = f"{content['title']} (version {row.number})"
            if content.get("progress_test_enabled"):
                options.append({"scope": f"pretest:{vid}", "label": f"{name} · opening pretest"})
            else:
                for module in content["modules"]:
                    if module.get("quiz"):
                        options.append({"scope": f"quiz:{vid}:{module['id']}",
                                        "label": f"{name} · {module['title']} quiz"})
            options.append({"scope": f"final:{vid}", "label": f"{name} · final exam"})
        return options

    @app.get("/api/admin/users/{user_id}/exam-resets")
    def admin_exam_reset_catalog(user_id: str, auth=Depends(administrator), db=Depends(get_db)):
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Account not found")
        return {"username": user.username, "options": exam_reset_options(db, user_id)}

    @app.post("/api/admin/users/{user_id}/exam-resets")
    def admin_reset_exam(user_id: str, body: ExamResetWrite,
                         auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Account not found")
        options = exam_reset_options(db, user_id)
        if body.scope != "all" and body.scope not in {item["scope"] for item in options}:
            raise HTTPException(422, "Select an available exam")
        marker = ExamReset(user_id=user_id, scope=body.scope, created=time.time())
        db.add(marker)
        db.flush()
        if body.scope == "all":
            for option in options:
                if option["scope"].startswith("pretest:"):
                    db.add(ExamReset(user_id=user_id, scope=option["scope"],
                                     created=time.time()))
        audit(db, auth[0], "reset_exam_attempts", marker.id)
        db.commit()
        return {"message": "Exam retake opened. Past results and class progress were retained.",
                "scope": body.scope, "reset_id": marker.id}

    @app.put("/api/admin/academy-assessments/bank")
    def replace_academy_assessment_bank(body: AcademyAssessmentBankWrite,
                                        auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        counts = {"overall": 0, "graduation": 0}
        areas_by_kind = {"overall": set(), "graduation": set()}
        seen_ids, seen_prompts = set(), set()
        prompts_from_classes = set()
        for course_row in db.scalars(select(Course)):
            content_versions = [json.loads(course_row.draft_json)]
            content_versions.extend(content_of(version_row) for version_row in db.scalars(
                select(CourseVersion).where(CourseVersion.course_id == course_row.id)))
            for content in content_versions:
                source_questions = [question for module in content.get("modules", [])
                                    for question in module.get("quiz", [])]
                source_questions.extend(content.get("exam", {}).get("questions", []))
                prompts_from_classes.update(normalized_question_prompt(question.get("prompt", ""))
                                            for question in source_questions if question.get("prompt"))
        for question in body.questions:
            if question.id in seen_ids:
                raise HTTPException(422, "Assessment question IDs must be unique")
            seen_ids.add(question.id)
            prompt = normalized_question_prompt(question.prompt)
            if prompt in seen_prompts:
                raise HTTPException(422, "Academy-wide assessments cannot repeat a question prompt")
            if prompt in prompts_from_classes:
                raise HTTPException(422, "Assessment questions cannot repeat module quiz or class exam prompts")
            seen_prompts.add(prompt)
            counts[question.kind] += 1
            areas_by_kind[question.kind].add(question.area.strip())
        if any(count > 100 for count in counts.values()):
            raise HTTPException(422, "Each Academy assessment may contain no more than 100 questions")
        if any(count == 0 for count in counts.values()):
            raise HTTPException(422, "Load separate overall and graduation question sets")
        if areas_by_kind["overall"] != areas_by_kind["graduation"]:
            raise HTTPException(422, "Overall and graduation question sets must cover the same knowledge areas")
        for old in db.scalars(select(AcademyAssessmentQuestion)):
            db.delete(old)
        db.flush()
        for question in body.questions:
            db.add(AcademyAssessmentQuestion(id=question.id, kind=question.kind, area=question.area.strip(),
                prompt=question.prompt.strip(), choices_json=json.dumps(question.choices), correct=question.correct,
                points=question.points, explanation=question.explanation.strip(),
                choice_explanations_json=json.dumps(question.choice_explanations),
                course_categories_json=json.dumps(question.course_categories),
                lab_kinds_json=json.dumps(question.lab_kinds), topics_json=json.dumps(question.topics)))
        audit(db, auth[0], "replace_academy_assessment_bank", f"overall:{counts['overall']}:graduation:{counts['graduation']}")
        db.commit()
        return {"counts": counts, "areas": sorted({question.area for question in body.questions})}

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
            if body.secondary_template_id is not None:
                adapter.template_ready(Lab(template_id=body.secondary_template_id))
        except Exception:
            raise HTTPException(409, "The package template is not available to the Academy on Proxmox")
        allocation_lock(db)
        lab = db.get(Lab, body.id)
        if lab and lab.enabled:
            raise HTTPException(409, "Deactivate the existing lab before replacing it from a package")
        values = body.model_dump(exclude={"schema_version", "package_format", "disk_sha256",
                                         "secondary_disk_sha256", "activate", "drills"})
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
