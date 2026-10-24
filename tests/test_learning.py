import copy
import json
from pathlib import Path
import pytest
from test_academy import system, user_client
from sqlalchemy import select
from academy.db import Audit, ExamReset, ProgressTestAttempt


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


def reset_account_id(admin, username):
    return next(item['id'] for item in admin.get('/api/admin/overview').json()['users']
                if item['username'] == username)


def test_admin_exam_resets_preserve_history_and_isolate_learners(system):
    admin = system[1]
    learner = user_client(system, 'reset-learner')
    other = user_client(system, 'reset-other')
    user_id = reset_account_id(admin, 'reset-learner')
    data = definition(require=False, attempts=1)
    data['modules'][0]['quiz'] = [
        {"id": "quiz-1", "type": "multiple_choice", "prompt": "Which tool lists sockets?",
         "choices": ["ss", "pwd"], "correct": 0, "points": 1, "explanation": "ss lists sockets."},
        {"id": "quiz-2", "type": "multiple_choice", "prompt": "Which tool shows a route?",
         "choices": ["ip route", "date"], "correct": 0, "points": 1, "explanation": "ip route shows routes."}]
    _, vid = publish(admin, data)
    for client in (learner, other):
        assert client.post(f'/api/course-versions/{vid}/enroll').status_code == 200
    quiz = learner.post(f'/api/course-versions/{vid}/modules/module1/quiz-attempts').json()
    final = learner.post(f'/api/course-versions/{vid}/attempts').json()
    other_final = other.post(f'/api/course-versions/{vid}/attempts').json()
    assert learner.get(f'/api/admin/users/{user_id}/exam-resets').status_code == 403
    assert learner.post(f'/api/admin/users/{user_id}/exam-resets', json={'scope': 'all'}).status_code == 403
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets', json={'scope': 'quiz:bad:module1'}).status_code == 422
    options = admin.get(f'/api/admin/users/{user_id}/exam-resets').json()['options']
    assert {f'quiz:{vid}:module1', f'final:{vid}', 'assessment:overall',
            'assessment:graduation'} <= {item['scope'] for item in options}

    reset = admin.post(f'/api/admin/users/{user_id}/exam-resets',
                       json={'scope': f'quiz:{vid}:module1'})
    assert reset.status_code == 200
    assert learner.post(f"/api/module-quiz-attempts/{quiz['id']}/submit",
                        json={'answers': {'quiz-1': 0, 'quiz-2': 0}}).status_code == 409
    assert learner.post(f'/api/course-versions/{vid}/modules/module1/quiz-attempts').json()['id'] != quiz['id']
    assert learner.post(f'/api/course-versions/{vid}/attempts').json()['id'] == final['id']
    assert other.post(f'/api/course-versions/{vid}/attempts').json()['id'] == other_final['id']

    response = learner.post(f"/api/exam-attempts/{final['id']}/submit", json={'answers': {'q1': 1}})
    assert response.status_code == 200 and response.json()['score'] == 100
    assert learner.post(f'/api/course-versions/{vid}/attempts').status_code == 409
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets',
                      json={'scope': f'final:{vid}'}).status_code == 200
    replacement = learner.post(f'/api/course-versions/{vid}/attempts').json()
    assert replacement['id'] != final['id']
    assert learner.get('/api/class-results').json()['attempts'][-1]['id'] == final['id']
    assert learner.get(f"/api/exam-attempts/{final['id']}").json()['score'] == 100
    assert learner.get(f'/api/course-versions/{vid}').json()['completed'] == []

    bank = [assessment_question('reset-overall', 'overall', 'Networking',
                                'Which observation isolates a local route failure?'),
            assessment_question('reset-graduation', 'graduation', 'Networking',
                                'Which command verifies the default route?')]
    assert admin.put('/api/admin/academy-assessments/bank', json={'questions': bank}).status_code == 200
    first = learner.post('/api/academy-assessments/overall/attempts').json()
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets',
                      json={'scope': 'assessment:overall'}).status_code == 200
    assert learner.put(f"/api/academy-assessments/attempts/{first['id']}",
                       json={'answers': {}}).status_code == 409
    second = learner.post('/api/academy-assessments/overall/attempts').json()
    assert second['id'] != first['id']
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets',
                      json={'scope': 'all'}).status_code == 200
    assert learner.post(f'/api/course-versions/{vid}/attempts').json()['id'] != replacement['id']
    assert learner.post('/api/academy-assessments/overall/attempts').json()['id'] != second['id']
    assert other.post(f'/api/course-versions/{vid}/attempts').json()['id'] == other_final['id']
    assert len(learner.get('/api/class-results').json()['attempts']) == 3
    assert len(learner.get('/api/academy-assessments').json()['attempts']) == 3
    with system[0].state.factory() as db:
        assert len(list(db.scalars(select(ExamReset).where(ExamReset.user_id == user_id)))) == 4
        assert len(list(db.scalars(select(Audit).where(Audit.action == 'reset_exam_attempts')))) == 4


def test_admin_pretest_reset_reopens_only_selected_class_and_can_be_skipped(system):
    admin = system[1]
    learner = user_client(system, 'pretest-reset-learner')
    other = user_client(system, 'pretest-reset-other')
    user_id = reset_account_id(admin, 'pretest-reset-learner')
    data = definition()
    data['progress_test_enabled'] = True
    data['modules'][0]['quiz'] = [
        {"id": f"pretest-{index}", "type": "multiple_choice",
         "prompt": f"Which route evidence is numbered {index}?",
         "choices": ["Route table", "Clock"], "correct": 0, "points": 1,
         "explanation": "The route table provides route evidence."} for index in range(8)]
    _, vid = publish(admin, data)
    for client in (learner, other):
        client.post(f'/api/course-versions/{vid}/enroll')
    first = learner.post(f'/api/course-versions/{vid}/progress-test-attempts').json()
    assert learner.put(f'/api/course-versions/{vid}/progress',
                       json={'module_id': 'module1', 'complete': False}).status_code == 200
    assert learner.get(f'/api/course-versions/{vid}').json()['pretest_available'] is False
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets',
                      json={'scope': f'pretest:{vid}'}).status_code == 200
    lesson = learner.get(f'/api/course-versions/{vid}').json()
    assert lesson['pretest_available'] is True and lesson['progress_test_attempt'] is None
    assert learner.post(f"/api/progress-test-attempts/{first['id']}/submit",
                        json={'answers': {}}).status_code == 409
    second = learner.post(f'/api/course-versions/{vid}/progress-test-attempts').json()
    assert second['id'] != first['id']
    assert learner.get(f'/api/course-versions/{vid}').json()['progress_test_attempt']['id'] == second['id']
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets',
                      json={'scope': f'pretest:{vid}'}).status_code == 200
    assert learner.get(f'/api/course-versions/{vid}').json()['pretest_available'] is True
    assert learner.put(f'/api/course-versions/{vid}/progress',
                       json={'module_id': 'module1', 'complete': False}).status_code == 200
    assert learner.get(f'/api/course-versions/{vid}').json()['pretest_available'] is False
    assert learner.post(f'/api/course-versions/{vid}/progress-test-attempts').status_code == 409
    assert admin.post(f'/api/admin/users/{user_id}/exam-resets',
                      json={'scope': 'all'}).status_code == 200
    assert learner.get(f'/api/course-versions/{vid}').json()['pretest_available'] is True
    third = learner.post(f'/api/course-versions/{vid}/progress-test-attempts').json()
    assert third['id'] not in (first['id'], second['id'])
    assert other.get(f'/api/course-versions/{vid}').json()['pretest_available'] is True
    with system[0].state.factory() as db:
        attempts = list(db.scalars(select(ProgressTestAttempt).where(ProgressTestAttempt.user_id == user_id)))
        assert len(attempts) == 3 and all(item.status == 'in_progress' for item in attempts)


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


def assessment_question(qid,kind,area,prompt,correct=0):
    return {"id":qid,"kind":kind,"area":area,"prompt":prompt,
        "choices":["First choice","Second choice","Third choice"],"correct":correct,"points":1,
        "explanation":"The first choice follows the evidence and the stated scope.",
        "choice_explanations":["This option is supported by the scenario.","This option does not fit the stated evidence.","This option is outside the requested scope."],
        "course_categories":["Networking"] if area=="Networking" else ["Linux"],
        "lab_kinds":["netlab"] if area=="Networking" else ["linux"],
        "topics":["Addressing and troubleshooting"] if area=="Networking" else ["Linux operations"]}


def test_academy_assessments_are_separate_private_and_report_area_growth(system):
    admin=system[1]; learner=user_client(system,"academy-assessment-learner"); outsider=user_client(system,"academy-assessment-outsider")
    course=definition(); course["category"]="Networking"; course["title"]="Routing Foundations"
    course["modules"][0]["quiz"]=[{"id":"module-route-check","type":"multiple_choice",
        "prompt":"Which command checks the active listener?","choices":["ss","pwd"],"correct":0,"points":1,
        "explanation":"The ss command reports listening sockets."}]
    _,version_id=publish(admin,course)
    assert learner.get("/api/academy-assessments").json()["assessments"]["overall"]["question_count"]==0
    def rejected(prompt, second_prompt="A distinct routing scenario?"):
        repeated=assessment_question("duplicate","overall","Networking",prompt)
        response=admin.put("/api/admin/academy-assessments/bank",json={"questions":[
            repeated,assessment_question("grad-1","graduation","Networking",second_prompt)]})
        assert response.status_code==422
    rejected(" Which command   displays ROUTES! ")
    rejected("WHICH command checks the active listener?")
    rejected("A distinct routing scenario?", " a DISTINCT routing scenario! ")

    bank=[
        assessment_question("overall-net-1","overall","Networking","A workstation can reach its subnet but not remote networks. Which evidence is most useful first?"),
        assessment_question("overall-net-2","overall","Networking","A packet leaves the source VLAN but never reaches the next subnet. Which path should be checked next?",1),
        assessment_question("overall-linux-1","overall","Linux","A service exits immediately after startup. Which record best identifies its startup failure?",1),
        assessment_question("overall-linux-2","overall","Linux","A user can read a file but cannot update it. Which permission should be inspected?"),
        assessment_question("grad-net-1","graduation","Networking","A host resolves a name but connects to the wrong address. Which record separates DNS from routing?",1),
        assessment_question("grad-linux-1","graduation","Linux","A process binds to a port but remote clients cannot connect. What should be checked first?"),
    ]
    response=admin.put("/api/admin/academy-assessments/bank",json={"questions":bank})
    assert response.status_code==200,response.text
    assert response.json()["counts"]=={"overall":4,"graduation":2}
    assert learner.get("/api/academy-assessments").json()["assessments"]["graduation"]["question_count"]==2
    overall=learner.post("/api/academy-assessments/overall/attempts",json={}).json()
    assert len(overall["questions"])==4 and "correct_answers" not in overall
    assert all(not {"correct","explanation","area","topics","section"}.intersection(question) for question in overall["questions"])
    assert outsider.get(f"/api/academy-assessments/attempts/{overall['id']}").status_code==404
    assert learner.post(f"/api/academy-assessments/attempts/{overall['id']}/submit",json={"answers":{}}).status_code==422
    correct_by_id={question["id"]:question["choices"][question["correct"]] for question in bank}
    wrong={question["id"]:(question["choices"].index(correct_by_id[question["id"]])+1)%len(question["choices"])
        for question in overall["questions"]}
    failed=learner.post(f"/api/academy-assessments/attempts/{overall['id']}/submit",json={"answers":wrong}).json()
    assert failed["score"]==0 and failed["passed"] is None
    assert failed["area_scores"]["Networking"]["score"]==0
    assert failed["area_scores"]["Linux"]["score"]==0
    assert failed["correct_answers"] and failed["recommendations"]
    assert failed["questions"][0]["explanation"]
    assert learner.get("/api/academy-assessments").json()["attempts"][0]["area_scores"]["Linux"]["score"]==0
    assert learner.get("/api/admin/academy-assessment-results").status_code==403
    results=admin.get("/api/admin/academy-assessment-results").json()
    assert results[0]["username"]=="academy-assessment-learner"
    assert results[0]["area_scores"]["Networking"]["question_count"]==2

    graduation=learner.post("/api/academy-assessments/graduation/attempts",json={}).json()
    assert len(graduation["questions"])==2
    passed=learner.post(f"/api/academy-assessments/attempts/{graduation['id']}/submit",json={
        "answers":{question["id"]:question["choices"].index("First choice") for question in graduation["questions"]}}).json()
    assert passed["score"]==50 and passed["passed"] is False
    assert admin.get(f"/api/academy-assessments/attempts/{passed['id']}").json()["passed"] is False
    assert learner.put("/api/admin/academy-assessments/bank",json={"questions":bank}).status_code==403


def test_academy_assessment_retake_shuffles_and_bank_has_per_test_limit(system):
    admin=system[1]; learner=user_client(system,"assessment-retake-learner")
    bank=[assessment_question(f"overall-{i}","overall","Linux",f"Linux readiness scenario {i}: which evidence should be checked?") for i in range(3)]
    bank += [assessment_question(f"grad-{i}","graduation","Linux",f"Linux graduation scenario {i}: which next action is justified?") for i in range(3)]
    assert admin.put("/api/admin/academy-assessments/bank",json={"questions":bank}).status_code==200
    first=learner.post("/api/academy-assessments/graduation/attempts",json={}).json()
    first_order=[question["id"] for question in first["questions"]]
    learner.post(f"/api/academy-assessments/attempts/{first['id']}/submit",json={"answers":{q["id"]:0 for q in first["questions"]}})
    second=learner.post("/api/academy-assessments/graduation/attempts",json={}).json()
    assert [question["id"] for question in second["questions"]]!=first_order
    too_many=[assessment_question(f"overall-{i}","overall","Linux",f"Unique Linux scenario {i}: what should be examined next?") for i in range(101)]
    too_many += [assessment_question("grad-only","graduation","Linux","What evidence should confirm the service is ready?")]
    assert admin.put("/api/admin/academy-assessments/bank",json={"questions":too_many}).status_code==422


def test_curated_private_assessment_bank_covers_all_areas_and_grades(system):
    admin=system[1]; learner=user_client(system,"academy-assessment-bank-learner")
    bank_path=Path(__file__).resolve().parents[1]/"staging/private/academy-assessments-bank.json"
    if not bank_path.is_file():
        pytest.skip("Protected assessment bank is not included in public source")
    bank=json.loads(bank_path.read_text(encoding="utf-8"))
    result=admin.put("/api/admin/academy-assessments/bank",json=bank)
    assert result.status_code==200,result.text
    assert result.json()["counts"]=={"overall":80,"graduation":80}
    expected={"Networking":14,"Linux":14,"Security":13,"Active Directory":13,
        "AI and prompt engineering":13,"Python":13}
    assert set(result.json()["areas"])==set(expected)
    assert learner.get("/api/academy-assessments").json()["assessments"]["overall"]=={
        "question_count":80,"area_count":6}
    for kind in ("overall","graduation"):
        attempt=learner.post(f"/api/academy-assessments/{kind}/attempts",json={}).json()
        assert len(attempt["questions"])==80 and "correct_answers" not in attempt
        assert all(not {"correct","explanation","area","topics","section"}.intersection(question)
            for question in attempt["questions"])
        areas_by_id={question["id"]:question["area"] for question in bank["questions"]}
        mixed_areas=[areas_by_id[question["id"]] for question in attempt["questions"]]
        assert sum(left!=right for left,right in zip(mixed_areas,mixed_areas[1:]))>=20
        key={question["id"]:question["choices"][question["correct"]]
            for question in bank["questions"] if question["kind"]==kind}
        graded=learner.post(f"/api/academy-assessments/attempts/{attempt['id']}/submit",json={
            "answers":{question["id"]:question["choices"].index(key[question["id"]])
                for question in attempt["questions"]}}).json()
        assert graded["score"]==100
        assert {area:value["question_count"] for area,value in graded["area_scores"].items()}==expected
        assert all(value["score"]==100 for value in graded["area_scores"].values())
        assert all("area" in question and "topics" in question for question in graded["questions"])
        assert graded["passed"] is (True if kind=="graduation" else None)


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
