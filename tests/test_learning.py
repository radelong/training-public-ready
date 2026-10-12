import copy
import json
from pathlib import Path
from test_academy import system, user_client


def definition(pdf=None, written=False, require=True, attempts=2):
    questions = [{"id": "q1", "type": "multiple_choice", "prompt": "Which command displays routes?",
                  "choices": ["pwd", "ip route"], "correct": 1, "points": 2,
                  "explanation": "The route table describes network paths.",
                  "choice_explanations": ["pwd shows the current directory.", "ip route displays routes."]}]
    if written:
        questions.append({"id": "q2", "type": "written", "prompt": "Explain the evidence.",
                          "points": 2, "rubric": "Two points for a justified diagnosis."})
    return {"title": "Routing class", "description": "Local slides and practice.",
            "modules": [{"id": "module1", "title": "Routing", "asset_id": pdf,
                         "lab_id": None if pdf else "netlab", "required": True}],
            "exam": {"passing_score": 75, "max_attempts": attempts, "require_modules": require,
                     "feedback": "after_pass", "questions": questions}}


def publish(admin, data):
    response = admin.post('/api/admin/courses', json=data)
    assert response.status_code == 200, response.text
    c = response.json()
    response = admin.post('/api/admin/courses/' + c['id'] + '/publish', json={"revision": c['revision']})
    assert response.status_code == 200, response.text
    return c, response.json()['id']


def test_roles_keys_prerequisites_and_grading(system):
    admin = system[1]; learner = user_client(system, 'student-one')
    c, vid = publish(admin, definition())
    for method, path, body in [('get', '/api/admin/courses', None),
                               ('post', '/api/admin/courses', definition()),
                               ('post', '/api/admin/labs', {"id": "extra", "title": "Lab", "template_id": 9990})]:
        response = getattr(learner, method)(path, **({"json": body} if body else {}))
        assert response.status_code == 403
    lesson = learner.get('/api/course-versions/' + vid)
    assert lesson.status_code == 200
    assert 'correct' not in lesson.json()['content']['exam']['questions'][0]
    assert 'rubric' not in lesson.json()['content']['exam']['questions'][0]
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code == 409
    assert learner.post(f'/api/course-versions/{vid}/enroll').status_code == 200
    assert learner.put(f'/api/course-versions/{vid}/progress', json={"module_id": "module1", "complete": True}).status_code == 200
    attempt = learner.post(f'/api/course-versions/{vid}/attempts').json()
    aid = attempt['id']
    assert 'correct_answers' not in attempt
    assert learner.post(f'/api/course-versions/{vid}/attempts').json()['id'] == aid
    assert learner.post(f'/api/exam-attempts/{aid}/submit', json={"answers": {"q1": True}}).status_code == 422
    assert learner.post(f'/api/exam-attempts/{aid}/submit', json={"answers": {}}).status_code == 422
    assert learner.put(f'/api/exam-attempts/{aid}', json={"answers": {"q1": 1}}).json()['status'] == 'in_progress'
    result = learner.post(f'/api/exam-attempts/{aid}/submit', json={"answers": {"q1": 1}}).json()
    assert result['score'] == 100 and result['passed'] is True
    assert result['correct_answers'] == {"q1": 1}
    assert learner.put(f'/api/exam-attempts/{aid}', json={"answers": {"q1": 0}}).status_code == 409
    other = user_client(system, 'student-two')
    assert other.get(f'/api/exam-attempts/{aid}').status_code == 404
    assert other.get('/api/class-results').json()['attempts'] == []


def test_failed_attempt_limits_and_score_only(system):
    admin = system[1]; learner = user_client(system, 'student-one')
    data = definition(require=False, attempts=1); data['exam']['feedback'] = 'score_only'
    _, vid = publish(admin, data)
    learner.post(f'/api/course-versions/{vid}/enroll')
    aid = learner.post(f'/api/course-versions/{vid}/attempts').json()['id']
    result = learner.post(f'/api/exam-attempts/{aid}/submit', json={"answers": {"q1": 0}}).json()
    assert result['score'] == 0 and not result['passed']
    assert result['correct_answers'] == {'q1': 1}
    assert result['marks'] == {'q1': 0}
    assert result['questions'][0]['selected_explanation'] == 'pwd shows the current directory.'
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code == 409


def test_written_review_and_original_version_retained(system):
    admin = system[1]; learner = user_client(system, 'student-one')
    c, vid = publish(admin, definition(written=True, require=False))
    learner.post(f'/api/course-versions/{vid}/enroll')
    aid = learner.post(f'/api/course-versions/{vid}/attempts').json()['id']
    result = learner.post(f'/api/exam-attempts/{aid}/submit', json={"answers": {"q1": 1, "q2": "The route is absent."}}).json()
    assert result['status'] == 'awaiting_review' and result['score'] is None
    assert result['marks'] == {'q1': 2}
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code == 409
    assert learner.post(f'/api/admin/exam-attempts/{aid}/grade', json={"marks": {"q2": 2}}).status_code == 403
    draft = copy.deepcopy(c['content']); draft['exam']['questions'][0]['correct'] = 0
    response = admin.put('/api/admin/courses/' + c['id'], json={"revision": c['revision'], "content": draft})
    assert response.status_code == 200
    newer = admin.post('/api/admin/courses/' + c['id'] + '/publish', json={"revision": response.json()['revision']}).json()['id']
    assert newer != vid
    assert learner.get('/api/course-versions/' + vid).status_code == 200
    outsider = user_client(system, 'student-two')
    assert outsider.get('/api/course-versions/' + vid).status_code == 404
    assert next(q for q in admin.get('/api/admin/exam-attempts').json()[0]['questions'] if q['id']=='q2')['rubric']
    assert admin.post(f'/api/admin/exam-attempts/{aid}/grade', json={"marks": {"q2": 9}}).status_code == 422
    result = admin.post(f'/api/admin/exam-attempts/{aid}/grade', json={"marks": {"q2": 1}, "feedback": "Good evidence."}).json()
    assert result['score'] == 75 and result['passed'] is True
    assert learner.get(f'/api/exam-attempts/{aid}').json()['correct_answers'] == {"q1": 1}
    admin.post('/api/admin/courses/' + c['id'] + '/unpublish')
    assert learner.get('/api/courses').json() == []
    assert learner.get('/api/course-versions/' + vid).status_code == 200


def test_pdf_upload_private_access_and_draft_concurrency(system):
    admin = system[1]; learner = user_client(system, 'student-one')
    response = admin.post('/api/admin/content', content=b'not pdf', headers={"Content-Type": "application/pdf"})
    assert response.status_code == 415
    response = admin.post('/api/admin/content', content=b'%PDF-1.4\ntraining\n%%EOF',
                          headers={"Content-Type": "application/pdf", "X-File-Name": "../../slides.pdf"})
    assert response.status_code == 200
    aid = response.json()['id']; assert '/' not in response.json()['filename']
    assert len(list(Path(system[3].content_dir).glob('*.pdf'))) == 1
    assert learner.get('/api/content/' + aid).status_code == 404
    c, vid = publish(admin, definition(pdf=aid))
    assert learner.get('/api/content/' + aid).headers['content-type'] == 'application/pdf'
    body = {"revision": c['revision'], "content": c['content']}
    assert admin.put('/api/admin/courses/' + c['id'], json=body).status_code == 200
    assert admin.put('/api/admin/courses/' + c['id'], json=body).status_code == 409
    bad = definition(); bad['modules'].append(bad['modules'][0])
    assert admin.post('/api/admin/courses', json=bad).status_code == 422
    admin.headers.pop('X-CSRF-Token')
    assert admin.post('/api/admin/content', content=b'%PDF-1.4', headers={"Content-Type": "application/pdf"}).status_code == 403


def test_csv_and_lab_registration(system):
    admin = system[1]
    sample = admin.get('/api/admin/exam-import-template.csv')
    assert sample.status_code == 200
    response = admin.post('/api/admin/exam-import', content=sample.content, headers={"Content-Type": "text/csv"})
    assert response.status_code == 200
    assert len(response.json()['questions']) == 3
    assert response.json()['questions'][1]['correct'] == 0
    assert admin.post('/api/admin/exam-import', content=b'invalid').status_code == 422
    assert admin.post('/api/admin/labs', json={"id": "new-lab", "title": "Practice", "template_id": 9990}).status_code == 200
    labs = admin.get('/api/labs').json()
    assert next(l for l in labs if l['id'] == 'new-lab')['enabled'] is False
    assert admin.post('/api/sessions', json={"lab_id": "new-lab"}).status_code == 409
    assert admin.post('/api/admin/labs', json={"id": "new-lab", "title": "Practice", "template_id": 9990}).status_code == 409
    assert not system[2].vms


def test_installed_lab_package_receipt_registers_and_optionally_activates(system):
    admin = system[1]
    receipt = {
        "schema_version": 1,
        "package_format": "academy-lab-package-v1",
        "id": "usb-practice",
        "title": "USB Practice Lab",
        "description": "Imported from approved removable media.",
        "kind": "linux",
        "template_id": 9910,
        "cores": 3,
        "memory": 3072,
        "disk_sha256": "a" * 64,
        "activate": True,
        "drills": [{"id": "check-shell", "title": "Check shell", "brief": "Inspect the shell.",
                    "goal": "Verify the local shell.", "tools": "academy-lab", "time": "5 min", "level": "1"}],
    }
    learner = user_client(system, 'package-student')
    assert learner.post('/api/admin/lab-packages/import', json=receipt).status_code == 403
    response = admin.post('/api/admin/lab-packages/import', json=receipt)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": "usb-practice", "enabled": True, "template_id": 9910,
                               "message": "Lab package registered and activated"}
    lab = next(value for value in admin.get('/api/labs').json() if value['id'] == 'usb-practice')
    assert lab['enabled'] and lab['cores'] == 3 and lab['memory'] == 3072
    assert lab['drills'][0]['id'] == 'check-shell'
    assert admin.post('/api/admin/lab-packages/import', json=receipt).status_code == 409
    invalid = {**receipt, "id": "bad-receipt", "disk_sha256": "not-a-checksum"}
    assert admin.post('/api/admin/lab-packages/import', json=invalid).status_code == 422


def test_lab_package_can_fill_existing_inactive_linux_placeholder(system):
    admin = system[1]
    assert admin.put('/api/admin/labs/linux', json={"template_id": 9002, "enabled": False,
                                                    "cores": 2, "memory": 2048}).status_code == 200
    receipt = {"schema_version": 1, "package_format": "academy-lab-package-v1", "id": "linux",
               "title": "Linux Lab", "description": "Installed offline Linux training image.",
               "kind": "linux", "template_id": 9911, "cores": 2, "memory": 4096,
               "disk_sha256": "b" * 64, "activate": False, "drills": []}
    response = admin.post('/api/admin/lab-packages/import', json=receipt)
    assert response.status_code == 200, response.text
    lab = next(value for value in admin.get('/api/labs').json() if value['id'] == 'linux')
    assert not lab['enabled'] and lab['template_id'] == 9911 and lab['memory'] == 4096


def test_retake_order_is_saved_and_feedback_includes_failed_answers(system):
    admin = system[1]; learner = user_client(system, 'retake-student')
    data = definition(require=False, attempts=3)
    data['exam']['questions'] = [{**data['exam']['questions'][0], 'id': 'q' + str(i)} for i in range(6)]
    _, vid = publish(admin, data)
    learner.post(f'/api/course-versions/{vid}/enroll')
    first = learner.post(f'/api/course-versions/{vid}/attempts').json()
    order = [q['id'] for q in first['questions']]
    assert len(set(order)) == 6
    assert 'explanation' not in first['questions'][0] and 'correct_answers' not in first
    assert [q['id'] for q in learner.get('/api/exam-attempts/' + first['id']).json()['questions']] == order
    result = learner.post(f"/api/exam-attempts/{first['id']}/submit", json={'answers': {q: 0 for q in order}}).json()
    assert result['score'] == 0 and not result['passed']
    assert set(result['correct_answers']) == set(order)
    assert all(q['explanation'] and q['selected_explanation'] for q in result['questions'])
    second = learner.post(f'/api/course-versions/{vid}/attempts').json()
    assert [q['id'] for q in second['questions']] != order
    assert [q['id'] for q in learner.post(f'/api/course-versions/{vid}/attempts').json()['questions']] == [q['id'] for q in second['questions']]
    passed = learner.post(f"/api/exam-attempts/{second['id']}/submit", json={'answers': {q: 1 for q in order}}).json()
    assert passed['score'] == 100 and passed['passed']


def test_answer_key_import_and_explanation_required_before_publication(system):
    admin = system[1]; learner = user_client(system, 'key-student')
    data = definition()
    payload = {'questions': data['exam']['questions'], 'csv': 'id,correct_answer,points,explanation,explanation_a,explanation_b\nq1,B,3,Routes describe network paths.,Directory command.,Route display command.\n'}
    assert learner.post('/api/admin/answer-key-import', json=payload).status_code == 403
    response = admin.post('/api/admin/answer-key-import', json=payload)
    assert response.status_code == 200, response.text
    question = response.json()['questions'][0]
    assert question['correct'] == 1 and question['points'] == 3
    assert question['explanation'] and len(question['choice_explanations']) == 2
    payload['csv'] = 'id,correct_answer\nunknown,A\n'
    assert admin.post('/api/admin/answer-key-import', json=payload).status_code == 422
    data['exam']['questions'][0]['explanation'] = ''
    course = admin.post('/api/admin/courses', json=data).json()
    assert admin.post('/api/admin/courses/' + course['id'] + '/publish', json={'revision': course['revision']}).status_code == 422


def test_additive_exam_order_migration_preserves_existing_rows(tmp_path):
    from sqlalchemy import text, inspect
    from academy.db import database, User, Course, CourseVersion, ExamAttempt
    url = 'sqlite:///' + str(tmp_path / 'migration.db')
    engine, factory = database(url)
    with factory() as db:
        user = User(username='migration-student', password_hash='test-only')
        course = Course(draft_json='{}'); db.add_all([user, course]); db.flush()
        version = CourseVersion(course_id=course.id, number=1, content_json='{}'); db.add(version); db.flush()
        attempt = ExamAttempt(version_id=version.id, user_id=user.id, status='graded', score=75, passed=True)
        db.add(attempt); db.commit(); attempt_id = attempt.id
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE exam_attempts DROP COLUMN question_order_json"))
    engine.dispose()
    migrated, new_factory = database(url)
    assert 'question_order_json' in {c['name'] for c in inspect(migrated).get_columns('exam_attempts')}
    with new_factory() as db:
        old = db.get(ExamAttempt, attempt_id)
        assert old.score == 75 and old.passed and old.question_order_json == '[]'
    migrated.dispose()
