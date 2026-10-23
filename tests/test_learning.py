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


def test_class_catalog_sums_explicit_module_and_exam_time_and_topics(system):
    admin=system[1]
    data=definition()
    data['category']='AI'
    data['modules'][0].update(estimated_minutes=35,topics=['Prompt structure','Grounding'])
    data['exam']['estimated_minutes']=20
    _,vid=publish(admin,data)
    published=next(course for course in admin.get('/api/courses').json() if course['version_id']==vid)
    assert published['estimated_minutes']==55
    assert published['key_topics']==['Grounding','Prompt structure']
    data=definition();data['exam']['estimated_minutes']=15
    _,vid=publish(admin,data)
    published=next(course for course in admin.get('/api/courses').json() if course['version_id']==vid)
    assert published['estimated_minutes'] is None


def test_module_quizzes_hide_keys_grade_at_80_and_shuffle_retake(system):
    admin=system[1]; learner=user_client(system,'module-quiz-learner')
    data=definition()
    data['modules'][0]['quiz']=[
        {"id":"route-q1","type":"multiple_choice","prompt":"Which command shows routes?",
         "choices":["pwd","ip route"],"correct":1,"points":1,"explanation":"ip route displays the kernel routing table.",
         "choice_explanations":["pwd prints the current directory.","This command displays route entries."]},
        {"id":"route-q2","type":"true_false","prompt":"The connected route can work without a gateway.",
         "choices":["True","False"],"correct":0,"points":1,"explanation":"A directly connected subnet needs no next hop.",
         "choice_explanations":["Correct; the interface owns this connected route.","A next hop is not required for directly connected networks."]}]
    _,vid=publish(admin,data)
    learner.post(f'/api/course-versions/{vid}/enroll')
    lesson=learner.get(f'/api/course-versions/{vid}').json()
    assert all('correct' not in q and 'explanation' not in q for q in lesson['content']['modules'][0]['quiz'])
    assert learner.put(f'/api/course-versions/{vid}/progress',json={'module_id':'module1','complete':True}).status_code==409

    first=learner.post(f'/api/course-versions/{vid}/modules/module1/quiz-attempts',json={}).json()
    first_order=[q['id'] for q in first['questions']]
    assert 'correct_answers' not in first and all('explanation' not in q for q in first['questions'])
    failed=learner.post(f"/api/module-quiz-attempts/{first['id']}/submit",json={'answers':{'route-q1':0,'route-q2':0}}).json()
    assert failed['score']==50 and failed['passed'] is False
    assert failed['correct_answers']=={'route-q1':1,'route-q2':0}
    q1=next(q for q in failed['questions'] if q['id']=='route-q1')
    assert q1['selected_explanation']=='pwd prints the current directory.'
    assert q1['explanation']=='ip route displays the kernel routing table.'

    second=learner.post(f'/api/course-versions/{vid}/modules/module1/quiz-attempts',json={}).json()
    assert [q['id'] for q in second['questions']] != first_order
    outsider=user_client(system,'module-quiz-outsider')
    assert outsider.get(f"/api/module-quiz-attempts/{second['id']}").status_code==404
    passed=learner.post(f"/api/module-quiz-attempts/{second['id']}/submit",json={'answers':{'route-q1':1,'route-q2':0}}).json()
    assert passed['score']==100 and passed['passed'] is True
    assert learner.put(f'/api/course-versions/{vid}/progress',json={'module_id':'module1','complete':True}).status_code==200
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code==200


def test_class_progress_test_awards_credit_only_for_perfect_module_scores(system):
    admin=system[1]; learner=user_client(system,'progress-test-student')
    data=definition()
    data['progress_test_enabled']=True
    data['modules'][0]['quiz']=[
        {"id":f"pt-routing-{i}","type":"multiple_choice","prompt":f"Routing pretest {i}: Which protocol resolves names?",
         "choices":["DNS","NTP"],"correct":0,"points":1,"explanation":"DNS resolves host names."}
        for i in range(8)]
    data['modules'].append({"id":"module2","title":"Addressing","description":"Address practice.",
        "lab_id":"netlab","required":True,"quiz":[
            {"id":f"pt-address-{i}","type":"multiple_choice","prompt":f"Addressing pretest {i}: Which value is a subnet mask?",
             "choices":["255.255.255.0","8.8.8.8"],"correct":0,"points":1,
             "explanation":"The first value identifies a /24 mask."} for i in range(8)]})
    _,vid=publish(admin,data)
    learner.post(f'/api/course-versions/{vid}/enroll')
    lesson=learner.get(f'/api/course-versions/{vid}').json()
    assert lesson['content']['progress_test_enabled'] is True
    assert lesson['current_module']==''
    assert all('correct' not in q for m in lesson['content']['modules'] for q in m['quiz'])
    first=learner.post(f'/api/course-versions/{vid}/progress-test-attempts').json()
    assert learner.get(f'/api/course-versions/{vid}').json()['current_module']=='module1'
    assert len(first['questions'])==16 and {q['module_id'] for q in first['questions']}=={'module1','module2'}
    assert 'correct_answers' not in first
    resumed=learner.post(f'/api/course-versions/{vid}/progress-test-attempts').json()
    assert resumed['id']==first['id'] and resumed['status']=='in_progress'
    assert learner.post(f'/api/progress-test-attempts/{first["id"]}/submit',json={"answers":{}}).status_code==422
    answers={**{f"pt-routing-{i}":0 for i in range(8)},
             **{f"pt-address-{i}":(1 if i==0 else 0) for i in range(8)}}
    partial=learner.post(f'/api/progress-test-attempts/{first["id"]}/submit',json={"answers":answers}).json()
    assert partial['score']==93.75
    assert partial['module_results']['module1']=={"score":100.0,"question_count":8,"perfect":True}
    assert partial['module_results']['module2']=={"score":87.5,"question_count":8,"perfect":False}
    assert learner.get(f'/api/course-versions/{vid}').json()['completed']==['module1']
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code==409
    assert learner.put(f'/api/course-versions/{vid}/progress',json={"module_id":"module2","complete":True}).status_code==200
    assert learner.post(f'/api/course-versions/{vid}/progress-test-attempts').status_code==409
    assert set(learner.get(f'/api/course-versions/{vid}').json()['completed'])=={'module1','module2'}
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code==200
    outsider=user_client(system,'progress-test-outsider')
    assert outsider.post(f'/api/progress-test-attempts/{first["id"]}/submit',json={"answers":answers}).status_code==404


def test_skipping_class_pretest_keeps_it_closed_after_class_starts(system):
    admin=system[1]; learner=user_client(system,'progress-test-skip-student')
    data=definition(); data['progress_test_enabled']=True
    data['modules'][0]['quiz']=[{"id":f"skip-{i}","type":"multiple_choice","prompt":f"Skip test {i}?",
        "choices":["A","B"],"correct":0,"points":1,"explanation":"A is correct."} for i in range(8)]
    _,vid=publish(admin,data)
    learner.post(f'/api/course-versions/{vid}/enroll')
    assert learner.get(f'/api/course-versions/{vid}').json()['current_module']==''
    assert learner.put(f'/api/course-versions/{vid}/progress',json={"module_id":"module1","complete":False}).status_code==200
    assert learner.get(f'/api/course-versions/{vid}').json()['current_module']=='module1'
    response=learner.post(f'/api/course-versions/{vid}/progress-test-attempts')
    assert response.status_code==409
    assert response.json()['detail']=='The class pretest is only available when the class first opens'


def test_enabled_progress_test_requires_each_module_and_no_final_prompt_duplicates(system):
    admin=system[1]
    data=definition(); data['progress_test_enabled']=True
    data['modules'][0]['quiz']=[{"id":f"p{i}","type":"multiple_choice","prompt":f"Question {i}?",
        "choices":["A","B"],"correct":0,"explanation":"A is correct."} for i in range(8)]
    data['modules'].append({"id":"module2","title":"Module 2","lab_id":"netlab","quiz":[]})
    assert admin.post('/api/admin/courses',json=data).status_code==422
    data['modules'][1]['quiz']=[{"id":f"p2-{i}","type":"multiple_choice","prompt":f"Addressing question {i}?",
        "choices":["A","B"],"correct":0,"explanation":"A is correct."} for i in range(8)]
    data['modules'][0]['quiz'].pop()
    assert admin.post('/api/admin/courses',json=data).status_code==422
    data['modules'][0]['quiz'].append({"id":"p-final-duplicate","type":"multiple_choice",
        "prompt":" which COMMAND   displays ROUTES? ","choices":["A","B"],"correct":0,"explanation":"A is correct."})
    assert admin.post('/api/admin/courses',json=data).status_code==422


def test_published_module_quiz_requires_explanations_and_objective_questions(system):
    admin=system[1]
    data=definition()
    data['modules'][0]['quiz']=[{"id":"q","type":"multiple_choice","prompt":"Question?",
        "choices":["A","B"],"correct":0,"points":1}]
    created=admin.post('/api/admin/courses',json=data)
    assert created.status_code==200
    assert admin.post('/api/admin/courses/'+created.json()['id']+'/publish',
                      json={'revision':created.json()['revision']}).status_code==422

    data=definition()
    data['modules'][0]['quiz']=[{"id":"q","type":"written","prompt":"Explain.","points":1,"rubric":"Evidence"}]
    assert admin.post('/api/admin/courses',json=data).status_code==422


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


def test_paired_offline_lab_receipt_imports_both_template_roles(system):
    admin = system[1]
    receipt = {"schema_version": 2, "package_format": "academy-lab-package-v2",
               "id": "callback-practice", "title": "Callback Troubleshooting",
               "description": "Diagnose a synthetic local HTTP heartbeat.", "kind": "callback",
               "template_id": 9920, "secondary_template_id": 9921, "cores": 2, "memory": 2048,
               "disk_sha256": "a" * 64, "secondary_disk_sha256": "b" * 64, "activate": False,
               "drills": [{"id": "callback-01-sender-service", "title": "Restore Sender service",
                           "brief": "Inspect the synthetic heartbeat path.", "goal": "Restore delivery.",
                           "tools": "systemctl, curl", "time": "10 min", "level": "1"}]}
    response = admin.post('/api/admin/lab-packages/import', json=receipt)
    assert response.status_code == 200, response.text
    lab = next(value for value in admin.get('/api/labs').json() if value['id'] == receipt['id'])
    assert not lab['enabled'] and lab['paired']
    invalid = {**receipt, "id": "callback-without-listener", "secondary_disk_sha256": None}
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
