"use strict";
// Uses the Academy's existing local session, CSRF token and shared navigation.
const learning={draft:null,lesson:null,module:0,attempt:null,editing:false};
const newId=()=>crypto.randomUUID();
const selected=(value,expected)=>value===expected?"selected":"";
async function rawApi(path,body,type,extra={}){
  const response=await fetch('/api'+path,{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':type,'X-CSRF-Token':state.user.csrf,...extra},body});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Review the uploaded file');return data;
}
async function learningPage(name){
  learning.editing=false;
  if(name==='classes')await renderClasses();else await renderContent();
}
async function renderClasses(){
  const classes=await api('/courses');
  $('content').innerHTML=heading('Class catalog','Learn through local slide modules, practice in your own lab and complete a final exam.')+
    (classes.length?`<div class="learning-grid">${classes.map(c=>`<article class="panel class-card"><div class="class-cover"><p class="eyebrow">SELF-PACED CLASS · VERSION ${c.number}</p><strong>${esc(c.title)}</strong></div><div class="class-body"><p>${esc(c.description)}</p><p class="small muted">${c.module_count} modules · Final exam</p><p>${c.completed} / ${c.module_count} modules completed</p><div class="progress-line"><i style="width:${c.module_count?Math.round(c.completed/c.module_count*100):0}%"></i></div></div><div class="class-foot"><button class="primary" data-course="${esc(c.version_id)}">${c.completed?'Continue class':'Open class'} →</button></div></article>`).join('')}</div>`:
    `<div class="empty"><h2>Your classes will appear here</h2><p class="muted">An administrator can upload modules and publish a class from Content manager.</p></div>`);
}
async function renderContent(){
  const drafts=await api('/admin/courses');
  $('content').innerHTML=heading('Content manager','Build classes from your own slides, approved labs and final exams.',`<button class="primary" data-learning="create-class">Create class</button>`)+
    `<div class="learning-tabs"><button class="secondary" data-learning="grade-list">Grade written exams</button><button class="secondary" data-learning="new-lab">Add lab</button><a class="secondary" href="/api/admin/exam-import-template.csv">Download question CSV template</a></div>`+
    `<div class="notice"><strong>Works offline.</strong> Upload slide decks exported as PDF. Original slide animations and narration are not retained. Answer keys stay on the server.</div>`+
    (drafts.length?`<div class="session-list">${drafts.map(d=>`<article class="session-row"><div><h3>${esc(d.content.title)}</h3><p>${esc(d.content.description)}</p><p class="small muted">${d.content.modules.length} modules · ${d.content.exam.questions.length} questions · ${d.published_id?'Published; draft edits need a new release':'Draft; hidden from learners'}</p></div><div class="button-row"><button class="primary" data-edit-course="${esc(d.id)}">Edit class</button>${d.published_id?`<button class="secondary" data-course="${esc(d.published_id)}">View published</button>`:''}</div></article>`).join('')}</div>`:
    `<div class="empty"><h2>Build your first class</h2><p class="muted">Start with a title, then add your slide modules and exam questions.</p></div>`);
}
async function openDraft(id){learning.draft=await api('/admin/courses/'+id);learning.editing=true;renderEditor();}
function renderEditor(){
  const d=learning.draft,c=d.content,e=c.exam;
  $('breadcrumb').textContent='Class editor';
  $('content').innerHTML=heading('Edit class','Save a draft while you work. Publishing creates a separate version for learners.',`<button class="secondary" data-learning="content-back">Back to content</button>`)+
  `<form id="course-editor" class="learning-form"><div class="panel"><div class="editor-columns"><div><label for="course-title">Class title</label><input id="course-title" name="title" value="${esc(c.title)}" maxlength="180" required><label for="course-description">Description</label><textarea id="course-description" name="description" maxlength="10000">${esc(c.description)}</textarea></div><div><p class="eyebrow">DRAFT REVISION ${d.revision}</p><h3>${d.published_id?'A published version is available':'Not yet published'}</h3><p class="editor-help">Draft changes stay private. Learners already enrolled retain their class version and recorded results.</p><div class="button-row"><button class="primary" type="submit">Save draft</button><button class="secondary" type="button" data-learning="preview">Preview draft</button><button class="secondary" type="button" data-learning="publish">Save and publish</button>${d.published_id?`<button class="text-button" type="button" data-learning="unpublish">Unpublish</button>`:''}</div><p id="editor-status" class="learning-status small muted">All uploads and grades stay on this local Academy.</p></div></div></div>
  <div class="section-title"><h2>Slide and lab modules</h2><button class="secondary" type="button" data-learning="add-module">Add module</button></div>
  ${c.modules.map((m,i)=>`<section class="editor-item" data-module-editor="${i}"><div class="learning-toolbar"><h3>Module ${i+1}</h3><div class="button-row"><button type="button" class="text-button" data-move-module="${i}" data-direction="-1" ${i===0?'disabled':''}>Move up</button><button type="button" class="text-button" data-move-module="${i}" data-direction="1" ${i===c.modules.length-1?'disabled':''}>Move down</button><button type="button" class="text-button" data-remove-module="${i}">Remove</button></div></div><label>Module title<input name="m${i}-title" value="${esc(m.title)}" maxlength="180" required></label><label>Lesson instructions<textarea name="m${i}-description" maxlength="10000">${esc(m.description)}</textarea></label><div class="editor-columns"><div><label>Slide PDF<input type="file" accept="application/pdf,.pdf" data-pdf="${i}"></label><p class="editor-file">${m.asset_id?`PDF uploaded · <a href="/api/content/${esc(m.asset_id)}" target="_blank" rel="noopener">View slides</a> <button class="text-button" type="button" data-clear-pdf="${i}">Remove PDF</button>`:'No PDF uploaded. Maximum 50 MB.'}</p></div><div><label>Attach a lab<select name="m${i}-lab"><option value="">No lab</option>${state.labs.map(l=>`<option value="${esc(l.id)}" ${selected(m.lab_id,l.id)}>${esc(l.title)}${l.enabled?'':' (inactive)'}</option>`).join('')}</select></label><label><input type="checkbox" name="m${i}-required" ${m.required?'checked':''}>Required before the final exam</label></div></div></section>`).join('')||'<div class="notice">Add a slide module or lab module to begin.</div>'}
  <div class="panel"><h2>Final exam</h2><label>Exam instructions<textarea name="exam_instructions" maxlength="10000">${esc(e.instructions||'')}</textarea></label><div class="editor-columns"><label>Passing score (%)<input name="passing_score" type="number" min="1" max="100" value="${e.passing_score}" required></label><label>Maximum attempts<input name="max_attempts" type="number" min="1" max="20" value="${e.max_attempts}" required></label></div><label><input type="checkbox" name="require_modules" ${e.require_modules?'checked':''}>Require completion of required modules before the exam</label><p class="editor-help">After submission, learners see right/wrong results and explanations, including failed attempts. Each retake randomizes question order.</p><div class="learning-toolbar"><button class="secondary" type="button" data-learning="add-question">Add question</button><div><a href="/api/admin/exam-import-template.csv">Download CSV template</a><label>Import questions from CSV<input type="file" id="question-import" accept=".csv,text/csv"></label></div></div><p class="editor-help">CSV import appends questions to this draft. Review the imported answer keys before publishing. Written answers need an instructor rubric and manual grading.</p></div>
  ${e.questions.map((q,i)=>`<section class="editor-item" data-question-editor="${i}"><div class="learning-toolbar"><h3>Question ${i+1}</h3><button type="button" class="text-button" data-remove-question="${i}">Remove</button></div><label>Question type<select name="q${i}-type" data-question-type="${i}"><option value="multiple_choice" ${selected(q.type,'multiple_choice')}>Multiple choice</option><option value="true_false" ${selected(q.type,'true_false')}>True / false</option><option value="written" ${selected(q.type,'written')}>Written response</option></select></label><label>Question<textarea name="q${i}-prompt" maxlength="10000" required>${esc(q.prompt)}</textarea></label><label>Points<input name="q${i}-points" type="number" min="1" max="100" value="${q.points}" required></label>${q.type==='multiple_choice'?`<label>Answer options (one per line, up to eight)<textarea name="q${i}-choices" data-question-choices="${i}" required>${esc(q.choices.join('\n'))}</textarea></label>`:''}</section>`).join('')}
  ${renderAnswerKey(e)}
  <div class="learning-toolbar"><button class="primary" type="submit">Save draft</button><button class="secondary" type="button" data-learning="publish">Save and publish</button></div></form>`;
}

function renderAnswerKey(exam){
 return `<section class="panel"><h2>Answer key and grading</h2><p class="editor-help">These answers and explanations are private while an exam is in progress. Objective questions are graded automatically against this key. Written answers require instructor review.</p><div class="learning-toolbar"><button type="button" class="secondary" data-learning="key-template">Download this exam's answer key CSV</button><label>Upload answer key CSV<input type="file" id="answer-key-import" accept=".csv,text/csv"></label></div>${exam.questions.map((q,i)=>`<section class="editor-item"><h3>Question ${i+1}: ${esc(q.prompt)}</h3><p class="small muted">Question ID: ${esc(q.id)} · ${q.points} points</p>${q.type==='written'?`<label>Instructor rubric<textarea name="q${i}-rubric" maxlength="10000" required>${esc(q.rubric||'')}</textarea></label>`:`<label>Correct answer<select name="q${i}-correct">${q.choices.map((v,n)=>`<option value="${n}" ${selected(q.correct,n)}>${String.fromCharCode(65+n)}: ${esc(v)}</option>`).join('')}</select></label><label>Explanation of the correct answer<textarea name="q${i}-explanation" maxlength="10000" required>${esc(q.explanation||'')}</textarea></label>${q.choices.map((v,n)=>`<label>Why option ${String.fromCharCode(65+n)} is right or wrong (optional)<textarea name="q${i}-why-${n}" maxlength="10000">${esc(q.choice_explanations?.[n]||'')}</textarea></label>`).join('')}`}</section>`).join('')||'<p>Add exam questions before preparing the answer key.</p>'}</section>`;
}
function downloadAnswerKey(){
 readEditor();const questions=learning.draft.content.exam.questions;
 if(!questions.length)throw new Error('Add questions before downloading an answer key');
 const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';
 const rows=[['id','question','correct_answer','points','rubric','explanation',...'abcdefgh'.split('').map(v=>'explanation_'+v)]];
 for(const q of questions)rows.push([q.id,q.prompt,q.type==='written'?'':q.type==='true_false'?q.choices[q.correct]:String.fromCharCode(65+q.correct),q.points,q.rubric,q.explanation,...'abcdefgh'.split('').map((v,i)=>q.choice_explanations?.[i]||'')]);
 const url=URL.createObjectURL(new Blob([rows.map(r=>r.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
 const link=document.createElement('a');link.href=url;link.download='exam-answer-key.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function readEditor(){
  const form=$('course-editor');if(!form)return;
  const f=new FormData(form),c=learning.draft.content;
  c.title=String(f.get('title'));c.description=String(f.get('description'));
  c.modules.forEach((m,i)=>{m.title=String(f.get(`m${i}-title`));m.description=String(f.get(`m${i}-description`));m.lab_id=f.get(`m${i}-lab`)||null;m.required=f.has(`m${i}-required`);});
  c.exam.instructions=String(f.get('exam_instructions')||'');c.exam.passing_score=Number(f.get('passing_score'));c.exam.max_attempts=Number(f.get('max_attempts'));c.exam.require_modules=f.has('require_modules');c.exam.feedback='after_pass';
  c.exam.questions.forEach((q,i)=>{const prior=q.type;q.type=f.get(`q${i}-type`);q.prompt=String(f.get(`q${i}-prompt`));q.points=Number(f.get(`q${i}-points`));q.explanation=String(f.get(`q${i}-explanation`)||'');
    if(q.type==='written'){q.rubric=f.get(`q${i}-rubric`)||q.rubric||'';q.choices=[];q.correct=null;}
    else if(q.type==='true_false'){q.choices=['True','False'];q.correct=prior===q.type?Number(f.get(`q${i}-correct`)):0;q.rubric='';}
    else{q.choices=prior===q.type?String(f.get(`q${i}-choices`)||'').split('\n').map(v=>v.trim()).filter(Boolean):['Option one','Option two'];q.correct=prior===q.type?Number(f.get(`q${i}-correct`)):0;q.rubric='';if(q.correct>=q.choices.length)q.correct=0;}
    q.choice_explanations=q.type==='written'?[]:q.choices.map((v,n)=>prior===q.type?String(f.get(`q${i}-why-${n}`)||''):'');
  });
}
async function saveEditor(){
  if(!$('course-editor').reportValidity())throw new Error('Complete the required fields before saving');
  readEditor();learning.draft=await api('/admin/courses/'+learning.draft.id,'PUT',{revision:learning.draft.revision,content:learning.draft.content});
  renderEditor();notify('Draft saved');
}
function previewDraft(){
  readEditor();const c=learning.draft.content;
  $('content').innerHTML=heading('Draft preview',c.title,`<button class="secondary" data-learning="editor-back">Return to editor</button>`)+
    `<div class="notice">Administrator preview. Nothing here records learner progress or an exam result.</div>`+
    c.modules.map(m=>`<section class="panel class-lesson"><h2>${esc(m.title)}</h2><p class="module-description">${esc(m.description)}</p>${m.asset_id?`<iframe class="slide-frame" title="${esc(m.title)} slides" src="/api/content/${esc(m.asset_id)}"></iframe>`:''}${m.lab_id?`<p>Linked lab: ${esc(labFor(m.lab_id)?.title)}</p>`:''}</section>`).join('')+
    `<section class="panel"><h2>Final exam · ${c.exam.passing_score}% passing score</h2>${c.exam.questions.map((q,i)=>`<div class="editor-item"><h3>${i+1}. ${esc(q.prompt)}</h3>${q.type==='written'?`<p>Written response · Instructor rubric: ${esc(q.rubric)}</p>`:`<ol>${q.choices.map((a,n)=>`<li>${esc(a)}${n===q.correct?' — correct answer':''}</li>`).join('')}</ol>`}</div>`).join('')}</section>`;
}
async function openCourse(vid){
  learning.editing=false;state.current=null;state.consoleUrl=null;state.detail=null;state.page='classes';
  await api(`/course-versions/${vid}/enroll`,'POST',{});learning.lesson=await api('/course-versions/'+vid);
  const index=learning.lesson.content.modules.findIndex(m=>m.id===learning.lesson.current_module);learning.module=Math.max(0,index);renderLesson();
}
function renderLesson(){
  const l=learning.lesson,c=l.content,m=c.modules[learning.module];$('breadcrumb').textContent='Class workspace';
  $('content').innerHTML=heading(c.title,`Version ${l.number} · ${l.completed.length} / ${c.modules.length} modules completed`, `<button class="secondary" data-page="classes">Back to catalog</button>`)+
    `<div class="course-layout"><aside class="panel module-nav"><h3>Class modules</h3>${c.modules.map((v,i)=>`<button class="secondary ${i===learning.module?'selected':''}" data-module="${i}">${l.completed.includes(v.id)?'✓ ':''}${i+1}. ${esc(v.title)}<small>${v.required?'Required':'Optional'}${v.asset_id?' · Slides':''}${v.lab_id?' · Lab':''}</small></button>`).join('')}<button class="primary" data-learning="begin-exam">Final exam</button><p class="small muted">Passing score ${c.exam.passing_score}% · Up to ${c.exam.max_attempts} attempts</p></aside><section class="panel class-lesson"><p class="eyebrow">MODULE ${learning.module+1} OF ${c.modules.length}</p><h2>${esc(m.title)}</h2><p class="module-description">${esc(m.description)}</p>${m.asset_id?`<iframe class="slide-frame" title="${esc(m.title)} slides" src="/api/content/${esc(m.asset_id)}"></iframe><p class="small muted">Use the viewer controls to move through the slide pages. <a href="/api/content/${esc(m.asset_id)}" target="_blank" rel="noopener">Open PDF separately</a> if your browser does not show an embedded viewer.</p>`:''}${m.lab_id?`<div class="notice"><strong>${esc(labFor(m.lab_id)?.title||m.lab_id)}</strong><p>Practice in your private lab, then return to this class.</p><button class="primary" data-class-lab="${esc(m.lab_id)}" ${labFor(m.lab_id)?.enabled?'':'disabled'}>${labFor(m.lab_id)?.enabled?'Open lab':'Lab awaiting activation'}</button></div>`:''}<div class="learning-toolbar"><button class="secondary" data-module="${learning.module-1}" ${learning.module===0?'disabled':''}>Previous module</button><button class="primary" data-learning="complete-module">${l.completed.includes(m.id)?'Completed ✓':'Mark module complete'}</button><button class="secondary" data-module="${learning.module+1}" ${learning.module===c.modules.length-1?'disabled':''}>Next module</button></div><p class="small muted">Mark a module complete after working through it. Completion records your progress; the final exam checks your understanding.</p></section></div>`;
}
async function moduleProgress(complete){
  const l=learning.lesson;const value=await api(`/course-versions/${l.id}/progress`,'PUT',{module_id:l.content.modules[learning.module].id,complete});l.completed=value.completed;l.current_module=value.current_module;
}
function renderExam(){
  const a=learning.attempt,editable=a.status==='in_progress';$('breadcrumb').textContent='Final exam';
  $('content').innerHTML=heading(a.title,a.instructions||'Final exam',`<button class="secondary" data-learning="lesson-back">Back to class</button>`)+
    (editable?`<div class="notice">Save answers to resume later. Submitting ends this attempt. Written responses will be graded by an instructor.</div>`:
    `<div class="exam-summary"><span class="score-value">${a.status==='awaiting_review'?'Awaiting instructor grading':`${a.score}%`}</span><p>${a.status==='graded'?(a.passed?'Passed':'Passing score not reached'):'Your submitted answers are retained.'} · Passing score ${a.passing_score}%</p>${a.feedback?`<p class="module-description">${esc(a.feedback)}</p>`:''}</div>`)+
    `<form id="exam-form" class="learning-form">${a.questions.map((q,i)=>`<section class="panel exam-question"><p class="eyebrow">QUESTION ${i+1} · ${q.points} ${q.points===1?'POINT':'POINTS'}</p><h3>${esc(q.prompt)}</h3>${q.type==='written'?`<label>Written answer<textarea name="${esc(q.id)}" maxlength="20000" ${editable?'required':'readonly'}>${esc(a.answers[q.id]||'')}</textarea></label>`:q.choices.map((choice,n)=>`<label class="exam-choice"><input type="radio" name="${esc(q.id)}" value="${n}" ${a.answers[q.id]===n?'checked':''} ${editable?'required':'disabled'}><span>${esc(choice)}</span></label>`).join('')}${a.marks&&q.id in a.marks?`<p class="small muted">Awarded ${a.marks[q.id]} / ${q.points} points</p>`:''}${a.correct_answers&&q.id in a.correct_answers?`<p>Correct answer: ${esc(q.choices[a.correct_answers[q.id]])}</p><p><strong>${a.answers[q.id]===a.correct_answers[q.id]?"Correct":"Incorrect"}</strong></p>${q.selected_explanation?`<p class="review-answer">${esc(q.selected_explanation)}</p>`:""}${q.explanation?`<p><strong>Explanation:</strong> ${esc(q.explanation)}</p>`:"<p class=\"small muted\">An explanation has not been provided for this older exam version.</p>"}`:''}</section>`).join('')}${editable?`<div class="learning-toolbar"><button type="button" class="secondary" data-learning="save-answers">Save answers</button><button class="primary" type="submit">Submit final exam</button></div>`:''}</form>`;
}
function examAnswers(){const data=new FormData($('exam-form'));return Object.fromEntries(learning.attempt.questions.filter(q=>data.has(q.id)).map(q=>[q.id,q.type==='written'?String(data.get(q.id)):Number(data.get(q.id))]));}
async function loadClassResults(){
  const host=$('class-results');if(!host)return;const data=await api('/class-results');if(!$('class-results'))return;
  host.innerHTML=`<div class="section-title"><h2>Class progress and exams</h2></div>`+(data.enrollments.length?`<div class="session-list">${data.enrollments.map(e=>`<article class="session-row"><div><h3>${esc(e.title)}</h3><p>${e.completed} / ${e.module_count} modules completed</p></div><button class="secondary" data-course="${esc(e.version_id)}">Resume this version</button></article>`).join('')}</div>`:'<p class="muted">Open a class to start recording progress.</p>')+
  (data.attempts.length?`<div class="panel table-scroll"><table><thead><tr><th>Class</th><th>Exam status</th><th>Score</th><th>Attempt</th></tr></thead><tbody>${data.attempts.map(a=>`<tr><td>${esc(a.title)}</td><td>${esc({in_progress:'In progress',awaiting_review:'Awaiting grading',graded:a.passed?'Passed':'Not passed'}[a.status])}</td><td>${a.score===null?'—':a.score+'%'}</td><td><button class="text-button" data-attempt="${esc(a.id)}">${a.status==='in_progress'?'Continue':'View result'}</button></td></tr>`).join('')}</tbody></table></div>`:'');
}
async function renderGrades(){
  const rows=await api('/admin/exam-attempts');$('content').innerHTML=heading('Grade written exams','Review submitted answers against the published rubric.',`<button class="secondary" data-learning="content-back">Back to content</button>`)+
  (rows.length?`<div class="grade-list">${rows.map(a=>`<form class="panel learning-form" data-grade="${esc(a.id)}"><h2>${esc(a.title)}</h2><p>${esc(a.username)} · Submitted ${esc(date(a.submitted))}</p>${a.questions.map(q=>`<section class="editor-item"><h3>${esc(q.prompt)}</h3><p class="review-answer">${esc(q.type==='written'?a.answers[q.id]:q.choices[a.answers[q.id]])}</p>${q.type==='written'?`<p><strong>Rubric:</strong> ${esc(q.rubric)}</p><label>Awarded points (maximum ${q.points})<input name="${esc(q.id)}" type="number" step="0.5" min="0" max="${q.points}" required></label>`:`<p>Automatically awarded ${a.marks[q.id]} / ${q.points} points</p>`}</section>`).join('')}<label>Instructor feedback<textarea name="feedback" maxlength="10000"></textarea></label><button class="primary">Save final grade</button></form>`).join('')}</div>`:'<div class="empty"><h2>No written exams awaiting grading</h2></div>');
}
function renderNewLab(){
  $('content').innerHTML=heading('Add a lab','Create an inactive catalog entry for a validated Proxmox template.',`<button class="secondary" data-page="admin">Back to administration</button>`)+
  `<div class="notice"><strong>Recommended: install an Academy lab package.</strong> Run the included package installer on Proxmox with the package from your USB drive. It creates and validates the template and writes a small receipt. Upload that receipt here to add all lab information automatically.</div><form id="lab-package-form" class="panel learning-form"><h2>Import installed lab package</h2><label>Academy import receipt<input id="lab-package-receipt" type="file" accept=".json,application/json" required></label><label><input name="activate" type="checkbox"> Activate immediately after Proxmox template verification</label><p class="editor-help">Leave activation off until the lab has passed console, readiness, isolation and exercise checks. Importing a receipt never uploads or executes a VM image in the web server.</p><button class="primary">Import package receipt</button></form><div class="notice"><strong>Manual registration</strong> is available for templates prepared without the Academy package tools.</div><form id="new-lab-form" class="panel learning-form"><label>Lab ID<input name="id" placeholder="my-linux-lab" pattern="[a-z][a-z0-9-]{1,63}" maxlength="64" required></label><label>Lab title<input name="title" maxlength="128" required></label><label>Description<textarea name="description" maxlength="10000"></textarea></label><div class="editor-columns"><label>Proxmox template VM ID<input name="template_id" type="number" min="100" max="999999999" required></label><label>Environment type<select name="kind"><option value="custom">Custom Ubuntu workspace</option><option value="linux">Linux lab</option><option value="netlab">Networking lab</option></select></label><label>CPU cores<input name="cores" type="number" min="1" max="16" value="2" required></label><label>RAM (MB)<input name="memory" type="number" min="1024" max="32768" value="2048" required></label></div><label>Optional exercise definitions (JSON file)<input id="lab-drills" type="file" accept=".json,application/json"></label><p class="editor-help">Use the supplied lab-exercises.example.json format. Exercise IDs must match the actions implemented inside the VM. Omit this file for an open practice workspace. Existing Linux Lab should be configured rather than duplicated.</p><button class="primary">Add inactive lab</button></form>`;
}
document.addEventListener('click',async event=>{
  const t=event.target.closest('[data-learning],[data-course],[data-edit-course],[data-module],[data-class-lab],[data-attempt],[data-remove-module],[data-move-module],[data-remove-question],[data-clear-pdf]');
  if(!t||t.disabled)return;event.preventDefault();t.disabled=true;
  try{
    if(t.dataset.course)await openCourse(t.dataset.course);
    else if(t.dataset.editCourse)await openDraft(t.dataset.editCourse);
    else if(t.dataset.attempt){learning.attempt=await api('/exam-attempts/'+t.dataset.attempt);learning.lesson=await api('/course-versions/'+learning.attempt.version_id);learning.module=0;state.current=null;state.consoleUrl=null;state.page='classes';renderExam();}
    else if(t.hasAttribute('data-module')){learning.module=Number(t.dataset.module);await moduleProgress(false);renderLesson();}
    else if(t.dataset.classLab){const existing=state.sessions.find(s=>s.lab_id===t.dataset.classLab);const v=existing||await api('/sessions','POST',{lab_id:t.dataset.classLab});await refresh();await openSession(v.id);}
    else if(t.hasAttribute('data-remove-module')){readEditor();learning.draft.content.modules.splice(Number(t.dataset.removeModule),1);renderEditor();}
    else if(t.hasAttribute('data-clear-pdf')){readEditor();learning.draft.content.modules[Number(t.dataset.clearPdf)].asset_id=null;renderEditor();}
    else if(t.hasAttribute('data-move-module')){readEditor();const modules=learning.draft.content.modules,i=Number(t.dataset.moveModule),j=i+Number(t.dataset.direction);[modules[i],modules[j]]=[modules[j],modules[i]];renderEditor();}
    else if(t.hasAttribute('data-remove-question')){readEditor();learning.draft.content.exam.questions.splice(Number(t.dataset.removeQuestion),1);renderEditor();}
    else switch(t.dataset.learning){
      case 'create-class': learning.draft=await api('/admin/courses','POST',{title:'Untitled class',description:'',modules:[],exam:{}});learning.editing=true;renderEditor();break;
      case 'content-back': await page('content');break;
      case 'editor-back': renderEditor();break;
      case 'add-module': readEditor();learning.draft.content.modules.push({id:newId(),title:'New module',description:'',asset_id:null,lab_id:null,required:true});renderEditor();break;
      case 'add-question': readEditor();learning.draft.content.exam.questions.push({id:newId(),type:'multiple_choice',prompt:'New question',choices:['Option one','Option two'],correct:0,points:1,rubric:''});renderEditor();break;
      case 'preview':previewDraft();break;
      case 'publish':await saveEditor();if(await confirmAction('Publish this class?','This creates a new version in the learner class catalog. Existing enrollments retain their earlier version.')){await api(`/admin/courses/${learning.draft.id}/publish`,'POST',{revision:learning.draft.revision});await openDraft(learning.draft.id);notify('Class published');}break;
      case 'unpublish':if(await confirmAction('Unpublish this class?','The class will leave the catalog. Existing enrollments and exam results remain available.')){await api(`/admin/courses/${learning.draft.id}/unpublish`,'POST',{});await openDraft(learning.draft.id);notify('Class unpublished');}break;
      case 'complete-module':await moduleProgress(true);renderLesson();break;
      case 'begin-exam':learning.attempt=await api(`/course-versions/${learning.lesson.id}/attempts`,'POST',{});renderExam();break;
      case 'lesson-back':if(learning.lesson)await openCourse(learning.lesson.id);else await page('classes');break;
      case 'save-answers':learning.attempt=await api(`/exam-attempts/${learning.attempt.id}`,'PUT',{answers:examAnswers()});notify('Answers saved');break;
      case 'grade-list':await renderGrades();break;
      case 'new-lab':renderNewLab();break;
      case 'key-template':downloadAnswerKey();break;
    }
  }catch(error){notify(error.message);}finally{if(t.isConnected)t.disabled=false;}
});
document.addEventListener('change',async event=>{
  const t=event.target;
  try{
    if(t.hasAttribute('data-pdf')){const file=t.files[0];if(!file)return;if(file.size>50*1024*1024)throw new Error('Each PDF must be 50 MB or smaller');readEditor();$('course-editor').querySelectorAll('button').forEach(b=>b.disabled=true);const asset=await rawApi('/admin/content',file,'application/pdf',{'X-File-Name':encodeURIComponent(file.name)});learning.draft.content.modules[Number(t.dataset.pdf)].asset_id=asset.id;renderEditor();notify('Slides uploaded. Save the draft to retain the module.');}
    else if(t.id==='answer-key-import'){const file=t.files[0];if(!file)return;if(file.size>1024*1024)throw new Error('Answer key CSV must be 1 MB or smaller');readEditor();const data=await api('/admin/answer-key-import','POST',{csv:await file.text(),questions:learning.draft.content.exam.questions});learning.draft.content.exam.questions=data.questions;renderEditor();notify('Answer key imported; review it and save your draft');}
    else if(t.id==='question-import'){const file=t.files[0];if(!file)return;readEditor();const data=await rawApi('/admin/exam-import',file,'text/csv');const seen=new Set(learning.draft.content.exam.questions.map(q=>q.id));if(data.questions.some(q=>seen.has(q.id)))throw new Error('Imported question IDs overlap existing questions. Change the CSV IDs before importing.');learning.draft.content.exam.questions.push(...data.questions);renderEditor();notify(`${data.questions.length} questions imported; save your draft`);}
    else if(t.hasAttribute('data-question-type')||t.hasAttribute('data-question-choices')){readEditor();renderEditor();}
  }catch(error){notify(error.message);if($('course-editor'))$('course-editor').querySelectorAll('button').forEach(b=>b.disabled=false);}
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!['course-editor','exam-form','new-lab-form','lab-package-form'].includes(form.id)&&!form.dataset.grade)return;
  event.preventDefault();const button=form.querySelector('button[type=submit],button:not([type])');if(button)button.disabled=true;
  try{
    if(form.id==='course-editor')await saveEditor();
    else if(form.id==='exam-form'){if(await confirmAction('Submit your final exam?','Submitted answers cannot be edited. Written responses will wait for instructor grading.')){learning.attempt=await api(`/exam-attempts/${learning.attempt.id}/submit`,'POST',{answers:examAnswers()});renderExam();}}
    else if(form.dataset.grade){const data=new FormData(form),marks=Object.fromEntries([...data.entries()].filter(([k])=>k!=='feedback').map(([k,v])=>[k,Number(v)]));await api(`/admin/exam-attempts/${form.dataset.grade}/grade`,'POST',{marks,feedback:String(data.get('feedback'))});await renderGrades();notify('Final grade saved');}
    else if(form.id==='new-lab-form'){const data=Object.fromEntries(new FormData(form));for(const k of ['template_id','cores','memory'])data[k]=Number(data[k]);const file=$('lab-drills').files[0];if(file&&file.size>1024*1024)throw new Error('Exercise JSON must be 1 MB or smaller');data.drills=file?JSON.parse(await file.text()):[];await api('/admin/labs','POST',data);await refresh();await page('admin');notify('Lab added inactive. Register its template before activating.');}
    else if(form.id==='lab-package-form'){const file=$('lab-package-receipt').files[0];if(!file)throw new Error('Choose the receipt created by the Proxmox package installer');if(file.size>1024*1024)throw new Error('The import receipt must be 1 MB or smaller');const data=JSON.parse(await file.text());data.activate=new FormData(form).has('activate');const result=await api('/admin/lab-packages/import','POST',data);await refresh();await page('admin');notify(result.message);}
  }catch(error){notify(error.message);}finally{if(button&&button.isConnected)button.disabled=false;}
});
