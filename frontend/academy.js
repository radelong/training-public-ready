"use strict";
const state={user:null,labs:[],sessions:[],results:[],page:"catalog",current:null,drill:null,detail:null,consoleUrls:{},consoleConnectingRoles:new Set(),consoleAutoFailedRoles:new Set(),termsVersion:null,videoItems:[],videoAvailable:false,videoAuthor:null,videoTopic:null,videoId:null,games:[],gameId:null,serverClockOffsetSeconds:null,assessment:null,assessmentIndex:null,assessmentCatalog:null};
const gameProgressChannel="academy-game-progress-v1";
let pendingGameProgress=null,latestGameProgress=null,gameProgressTimer=null,gameProgressDrain=null,gameProgressErrorShown=false;
const gameProgressFlushWaiters=new Map();
const labTypeFilter=new Set();
function labType(lab){return {netlab:"Networking",networking:"Networking",callback:"Networking",linux:"Linux",security:"Security",cloud:"Cloud",programming:"Programming"}[lab.kind]||"Other";}
function formatMinutes(value){if(!Number.isInteger(value)||value<1)return "Not set yet";const hours=Math.floor(value/60),minutes=value%60;return hours?`${hours} hr${hours===1?"":"s"}${minutes?` ${minutes} min`:""}`:`${minutes} min`;}
function renderLabTypeFilter(){
  const grid=$("content").querySelector(".catalog-grid");
  if(!grid)return;
  const types=[...new Set(state.labs.map(labType))].sort();
  if(types.length>1)grid.insertAdjacentHTML("beforebegin",`<fieldset class="catalog-filters"><legend>Filter labs by type</legend>${types.map(type=>`<label><input type="checkbox" data-lab-type="${esc(type)}" ${labTypeFilter.has(type)?"checked":""}> ${esc(type)}</label>`).join("")}<p class="small muted">Select no types to show all labs.</p></fieldset>`);
  [...grid.children].forEach((card,index)=>{card.hidden=labTypeFilter.size>0&&!labTypeFilter.has(labType(state.labs[index]));});
}
document.addEventListener("change",event=>{
  if(!event.target.matches("[data-lab-type]"))return;
  const type=event.target.dataset.labType;
  if(event.target.checked)labTypeFilter.add(type);else labTypeFilter.delete(type);
  render();
});
const $=(id)=>document.getElementById(id);
const esc=(value)=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const date=(stamp)=>new Date(stamp*1000).toLocaleString();
const labFor=(id)=>state.labs.find(l=>l.id===id);
function repairConsoleStorage(){try{const key="GUAC_AUTH_TOKEN",saved=localStorage.getItem(key);if(saved!==null){let value;try{value=JSON.parse(saved);}catch{}if(typeof value!=="string"||!value)localStorage.removeItem(key);}}catch{}}
function mountConsoleFrame(host,frame,oldFrame=null){
  const src=frame.getAttribute("src");if(!src)return;
  // Assign src after attaching the iframe to the live document. A frame parsed
  // inside the detached render tree can otherwise remain at about:blank.
  frame.removeAttribute("src");
  if(oldFrame)oldFrame.replaceWith(frame);else host.append(frame);
  frame.setAttribute("src",src);
}
function notify(message){$("toast").textContent=message;$("toast").hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>$("toast").hidden=true,6500);}
async function api(path,method="GET",data){const response=await fetch("/api"+path,{method,credentials:"same-origin",headers:{...(data?{"Content-Type":"application/json"}:{}),...(state.user?{"X-CSRF-Token":state.user.csrf}:{})},...(data?{body:JSON.stringify(data)}:{})});const serverDate=Date.parse(response.headers.get("Date")||"");if(Number.isFinite(serverDate))state.serverClockOffsetSeconds=serverDate/1000-Date.now()/1000;let result;try{result=await response.json();}catch{result={detail:"The service did not return a valid response"};}if(!response.ok){if(response.status===401&&path!=="/login")showLogin();throw new Error(typeof result.detail==="string"?result.detail:"Review the entered values and try again");}return result;}
async function flushGameProgress(){clearTimeout(gameProgressTimer);gameProgressTimer=null;if(gameProgressDrain){await gameProgressDrain;if(pendingGameProgress)return flushGameProgress();return;}if(!pendingGameProgress||!state.user)return;gameProgressDrain=(async()=>{while(pendingGameProgress&&state.user){const pending=pendingGameProgress;pendingGameProgress=null;try{await api(`/games/${pending.gameId}/progress`,"PUT",{state:pending.state});gameProgressErrorShown=false;}catch(error){pendingGameProgress=pendingGameProgress||pending;if(!gameProgressErrorShown){notify("Could not save game progress. Reconnect and try again.");gameProgressErrorShown=true;}throw error;}}})();try{await gameProgressDrain;}finally{gameProgressDrain=null;}}
window.addEventListener("message",event=>{const frame=document.querySelector("#content .game-player-frame"),message=event.data;if(!frame||event.source!==frame.contentWindow||state.page!=="games"||!state.gameId||!message||message.channel!==gameProgressChannel)return;if(message.type==="flushed"&&typeof message.requestId==="string"){const resolve=gameProgressFlushWaiters.get(message.requestId);if(resolve){gameProgressFlushWaiters.delete(message.requestId);flushGameProgress().then(()=>resolve(true)).catch(()=>resolve(false));}return;}const gameId=state.gameId;if(message.type==="load"){api(`/games/${gameId}/progress`).then(progress=>{if(frame.isConnected&&state.gameId===gameId)event.source.postMessage({channel:gameProgressChannel,type:"loaded",state:progress.state},"*");}).catch(()=>{if(frame.isConnected&&state.gameId===gameId)event.source.postMessage({channel:gameProgressChannel,type:"failed"},"*");});return;}if(message.type!=="save"||typeof message.state!=="string"||message.state.length>131072)return;pendingGameProgress=latestGameProgress={gameId,state:message.state};clearTimeout(gameProgressTimer);gameProgressTimer=setTimeout(()=>{if(frame.isConnected&&state.page==="games"&&state.gameId===gameId)flushGameProgress().catch(()=>{});},250);});
async function requestGameProgressFlush(){const frame=document.querySelector("#content .game-player-frame");if(!frame||!state.gameId)return flushGameProgress();const requestId=crypto.randomUUID();return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{gameProgressFlushWaiters.delete(requestId);reject(new Error("Could not confirm the game progress save. Keep the game open and try again."));},5000);gameProgressFlushWaiters.set(requestId,saved=>{clearTimeout(timer);saved?resolve():reject(new Error("Could not confirm the game progress save. Keep the game open and try again."));});frame.contentWindow.postMessage({channel:gameProgressChannel,type:"flush",requestId},"*");});}
window.addEventListener("pagehide",()=>{if(!latestGameProgress||!state.user)return;const body=JSON.stringify({state:latestGameProgress.state});if(new TextEncoder().encode(body).length>60000)return;fetch(`/api/games/${encodeURIComponent(latestGameProgress.gameId)}/progress`,{method:"PUT",credentials:"same-origin",keepalive:true,headers:{"Content-Type":"application/json","X-CSRF-Token":state.user.csrf},body}).catch(()=>{});});
function showLogin(){state.user=null;state.consoleUrls={};$("content").replaceChildren();if(location.pathname!=="/login"){location.assign("/login?next="+encodeURIComponent(location.pathname+location.search));return;}$("login-view").hidden=false;$("app-view").hidden=true;}
async function refresh(){[state.labs,state.sessions,state.results]=await Promise.all([api("/labs"),api("/sessions"),api("/results")]);state.labs.sort((a,b)=>(["netlab","linux"].indexOf(a.id))-( ["netlab","linux"].indexOf(b.id)));$("seat-count").textContent=state.sessions.length;}
const routes={catalog:"/labs",assessments:"/assessments",classes:"/classes",videos:"/videos",games:"/games",sessions:"/sessions",results:"/results",account:"/account",content:"/content",admin:"/admin", "bug-report":"/bug-report", "bug-reports":"/admin/bug-reports"};
function routePage(){if(location.pathname==="/lab-guide"||(location.pathname==="/labs"&&new URLSearchParams(location.search).get("view")==="guide"))return "catalog";return Object.keys(routes).find(name=>routes[name]===location.pathname)||"catalog";}
async function enter(user){state.user=user;$("password").value="";$("login-view").hidden=true;$("app-view").hidden=false;$("user-label").textContent=user.username;document.querySelectorAll(".admin-only").forEach(e=>e.hidden=user.role!=="admin");await refresh();if(user.role==="admin"){const count=await api("/admin/bug-reports/unread-count");const badge=$("bug-report-count");badge.textContent=count.count;badge.hidden=count.count===0;}const wanted=new URLSearchParams(location.search).get("next");const destination=Object.keys(routes).find(name=>routes[name]===wanted)||routePage();await page(user.role!=="admin"&&["admin","content","bug-reports"].includes(destination)?"catalog":destination,true);}
function passed(lab){return new Set(state.results.filter(r=>r.lab_id===lab&&r.passed).map(r=>r.drill_id));}
function badge(value,announce=false){return `<span class="status-pill ${esc(value)}"${announce?' role="status" aria-live="polite"':''}>${esc({queued:"Queued",provisioning:"Preparing VM",ready:"Ready",resetting:"Resetting",ending:"Ending",ended:"Ended",error:"Needs attention"}[value]||value)}</span>`;}
function startupMarkup(session){
  const phase=window.AcademyLabStartup?.startupPhase(session);
  if(!phase)return "";
  const estimate=window.AcademyLabStartup.estimateSeconds(Boolean(session.paired));
  const now=Date.now()/1000+(state.serverClockOffsetSeconds||0);
  const result=window.AcademyLabStartup.progress({...phase,estimate,now});
  const value=result.indeterminate?"":` aria-valuenow="${result.percent}"`;
  const actionHeading=phase.action==="reset"?"Restoring a clean lab":phase.action==="retry"?"Retrying lab setup":session.paired?"Preparing your VM pair":"Preparing your private VM";
  return `<section class="panel lab-startup" data-lab-startup data-phase="${phase.phase}"><div class="lab-startup-copy"><p class="eyebrow">${phase.phase==="queued"?"WAITING FOR A PROVISIONING SLOT":"SETTING UP YOUR ENVIRONMENT"}</p><h2>${actionHeading}</h2><p data-startup-status role="status" aria-live="polite">${esc(result.status)}</p></div><div class="lab-startup-meter" role="progressbar" aria-label="Estimated lab startup progress" aria-valuemin="0" aria-valuemax="100"${value} aria-valuetext="${esc(result.ariaValueText)}" data-indeterminate="${result.indeterminate}"><i data-startup-fill style="width:${result.indeterminate?"34":result.percent}%"></i></div><p class="small muted">${esc(window.AcademyLabStartup.estimateLabel(Boolean(session.paired)))} Actual setup time varies with host load.</p></section>`;
}
function updateStartupProgress(){
  const card=document.querySelector("[data-lab-startup]");
  if(!card||!state.detail||!window.AcademyLabStartup)return;
  const phase=window.AcademyLabStartup.startupPhase(state.detail);
  if(!phase){card.remove();return;}
  const estimate=window.AcademyLabStartup.estimateSeconds(Boolean(state.detail.paired));
  const now=Date.now()/1000+(state.serverClockOffsetSeconds||0);
  const result=window.AcademyLabStartup.progress({...phase,estimate,now});
  card.dataset.phase=phase.phase;
  card.querySelector(".eyebrow").textContent=phase.phase==="queued"?"WAITING FOR A PROVISIONING SLOT":"SETTING UP YOUR ENVIRONMENT";
  const status=card.querySelector("[data-startup-status]");
  if(status.textContent!==result.status)status.textContent=result.status;
  const meter=card.querySelector("[role=progressbar]");
  meter.dataset.indeterminate=String(result.indeterminate);
  if(meter.getAttribute("aria-valuetext")!==result.ariaValueText){
    meter.setAttribute("aria-valuetext",result.ariaValueText);
    if(result.indeterminate)meter.removeAttribute("aria-valuenow");else meter.setAttribute("aria-valuenow",String(result.percent));
  }
  card.querySelector("[data-startup-fill]").style.width=result.indeterminate?"34%":`${result.percent}%`;
}
async function loadLabGuideTranscript(){
  const target=document.querySelector("[data-lab-guide-transcript]");
  if(!target)return;
  try{
    const response=await fetch("/static/lab-guide.vtt",{credentials:"same-origin"});
    if(!response.ok)throw new Error("Transcript unavailable");
    const cues=(await response.text()).replace(/\r/g,"").split("\n\n").flatMap(cue=>{
      const lines=cue.split("\n"),timing=lines.findIndex(line=>line.includes("-->"));
      return timing<0?[]:[lines.slice(timing+1).join(" ").trim()];
    }).filter(Boolean);
    target.innerHTML=`<p>${esc(cues.join(" "))}</p>`;
  }catch{
    target.textContent="Transcript unavailable. Turn on English captions in the video controls.";
  }finally{
    target.setAttribute("aria-busy","false");
  }
}
function labGuideMarkup(){return `<section class="panel lab-guide-player"><div class="lab-guide-player-heading"><div><p class="eyebrow">ACADEMY QUICK START</p><h2>How to use the labs</h2><p class="muted">Watch this short walkthrough before your first session.</p></div><span class="guide-duration">About 2½ minutes</span></div><video controls preload="metadata" playsinline poster="/static/lab-guide-poster.png?v=20261022-lab-guide-2" aria-label="How to use Training Academy labs"><source src="/static/lab-guide.mp4?v=20261022-lab-guide-2" type="video/mp4"><track kind="captions" src="/static/lab-guide.vtt?v=20261022-lab-guide-2" srclang="en" label="English" default>Your browser cannot play this video. <a href="/static/lab-guide.mp4?v=20261022-lab-guide-2">Open the lab guide video</a>.</video><details class="lab-guide-transcript"><summary>Read the video transcript</summary><div data-lab-guide-transcript aria-busy="true" role="region" aria-label="Video transcript">Loading transcript…</div></details></section><section class="lab-guide-steps" aria-label="Lab workflow"><article class="panel"><span>01</span><h3>Choose a lab</h3><p>Browse the catalog and review the environment, exercises, time estimate and key topics.</p></article><article class="panel"><span>02</span><h3>Start and wait</h3><p>Watch the queued or estimated setup status until the workspace is ready.</p></article><article class="panel"><span>03</span><h3>Work the exercise</h3><p>Read the task, prepare it, then work in the embedded terminal or paired consoles.</p></article><article class="panel"><span>04</span><h3>Check and finish</h3><p>Review feedback, retry as needed, then reset or end the lab when you are done.</p></article></section>`;}
function heading(title,description,actions=""){return `<div class="page-heading"><div><p class="eyebrow">TRAINING ACADEMY</p><h1>${esc(title)}</h1><p class="muted">${esc(description)}</p></div>${actions}</div>`;}
async function page(name,replace=false){if(!routes[name]||(["admin","content","bug-reports"].includes(name)&&state.user?.role!=="admin"))return;if(state.page==="games"&&(name!=="games"||state.gameId)&&!await confirmGameLeave())return;const route=routes[name];if(location.pathname+location.search!==route)history[replace?"replaceState":"pushState"]({},"",route);state.page=name;state.current=null;state.consoleUrls={};state.detail=null;state.gameId=null;document.querySelectorAll("[data-page]").forEach(e=>e.classList.toggle("active",e.dataset.page===name));$("breadcrumb").textContent={catalog:"Lab catalog",sessions:"My lab sessions",results:"My results",assessments:"Academy assessments",admin:"Administration",account:"My account",classes:"Class catalog",videos:"Video library",games:"Learning games",content:"Content manager","bug-report":"Report a Bug","bug-reports":"Bug report inbox"}[name];document.title=$("breadcrumb").textContent+" | Training Academy";if(name==="admin")await renderAdmin();else if(name==="bug-reports")await renderBugReports();else if(name==="videos")await renderVideos();else if(name==="games")await renderGames();else if(name==="assessments")await renderAssessments();else if(["classes","content"].includes(name))await learningPage(name);else render();}
function render(){if(state.current){renderWorkspace();return;}if(state.page==="catalog"){renderCatalog();renderLabTypeFilter();}else if(state.page==="sessions")renderSessions();else if(state.page==="results")renderResults();else if(state.page==="assessments")renderAssessments();else if(state.page==="account")renderAccount();else if(state.page==="bug-report")renderBugReport();}
function renderCatalog(){const complete=new Set(state.results.filter(r=>r.passed).map(r=>r.lab_id+":"+r.drill_id)).size;$("content").innerHTML=labGuideMarkup()+heading("Your next step starts here","Choose a lab, open your private environment and work through realistic tasks at your own pace.")+`<div class="metrics"><div class="metric"><strong>${state.labs.filter(l=>l.enabled).length}</strong><span>Available labs</span></div><div class="metric"><strong>${state.sessions.length}</strong><span>Active sessions</span></div><div class="metric"><strong>${complete}</strong><span>Exercises completed</span></div></div><div class="section-title"><h2>Hands-on labs</h2><span class="small muted">Private VMs · Local access</span></div><div class="catalog-grid">`+state.labs.map(l=>{const existing=state.sessions.find(s=>s.lab_id===l.id);const done=passed(l.id).size;const percent=l.drills.length?Math.round(done/l.drills.length*100):0;const motif={netlab:"□—◇—□",linux:"&gt;_",kubernetes:"⬡",callback:"⇢",pmo:"▥"}[l.kind]||"□";return `<article class="lab-card"><div class="card-visual ${esc(l.kind)}"><p class="eyebrow">${esc({netlab:"NETWORKS & FIREWALLS",linux:"LINUX LAB",kubernetes:"CLUSTER OPERATIONS",callback:"NETWORK TROUBLESHOOTING",pmo:"MISSION CAPABILITIES"}[l.kind]||l.kind)}</p><span class="motif" aria-hidden="true">${motif}</span></div><div class="card-body"><h3>${esc(l.title)}</h3><p>${esc(l.description)}</p><div class="card-meta"><span>${l.drills.length?l.drills.length+" exercises":"Custom workspace"}</span><span>${l.memory/1024} GB RAM</span><span>${l.paired?"Paired Ubuntu VMs":"Ubuntu VM"}</span></div><div class="catalog-details"><p><strong>Expected time:</strong> ${formatMinutes(l.expected_minutes)}</p><p><strong>Key topics:</strong> ${esc((l.key_topics||[]).join(" · ")||"Not set yet")}</p></div></div><div class="card-bottom"><div class="card-progress">${l.drills.length?done+" / "+l.drills.length+" completed":"Template supplied locally"}<div class="progress-line"><i style="width:${percent}%"></i></div></div>${existing?`<button class="primary" data-open="${esc(existing.id)}">Open session →</button>`:l.enabled?`<button class="primary" data-launch="${esc(l.id)}">Start lab →</button>`:`<span class="status-pill">Awaiting activation</span>`}</div></article>`;}).join("")+`</div><div class="notice"><strong>A place to practice.</strong> Your lab changes stay in your assigned VM. You can reconnect during the session, restore a clean VM or end the lab when you finish. Exercise results remain in your account.</div>`;loadLabGuideTranscript();}
function renderSessions(){$("content").innerHTML=heading("My lab sessions","Reconnect to an existing environment or return to the catalog to start another lab.")+`<div class="session-list">`+(state.sessions.length?state.sessions.map(s=>`<article class="session-row"><div><h3>${esc(labFor(s.lab_id)?.title||s.lab_id)}</h3><p>${esc(s.message)}</p><p>Session ends ${esc(date(s.expires))}</p></div><div class="button-row">${badge(s.state)}<button class="primary" data-open="${esc(s.id)}">Open workspace</button></div></article>`).join(""):`<div class="empty"><h2>No active labs</h2><p class="muted">Start a lab from the catalog when you are ready.</p><button class="primary" data-page="catalog">Browse labs</button></div>`)+`</div>`;}
async function openSession(id){state.current=id;state.consoleUrls={};state.consoleAutoFailedRoles.clear();state.detail=await api("/sessions/"+id);state.drill=state.detail.active_drill||labFor(state.detail.lab_id)?.drills[0]?.id||null;$("breadcrumb").textContent="Lab workspace";renderWorkspace();const roles=state.detail.paired?["sender","listener"]:["sender"];await Promise.all(roles.map(role=>connectConsole(false,role)));}
async function connectConsole(manual=false,role="sender"){const id=state.current;if(!id||state.detail?.state!=="ready"||state.consoleConnectingRoles.has(role)||(!manual&&(state.consoleUrls[role]||state.consoleAutoFailedRoles.has(role))))return;state.consoleConnectingRoles.add(role);try{repairConsoleStorage();const value=await api(`/sessions/${id}/console?role=${encodeURIComponent(role)}`,"POST",{});if(state.current!==id)return;state.consoleUrls[role]=value.url;state.consoleAutoFailedRoles.delete(role);renderWorkspace();}catch(error){if(state.current===id){state.consoleAutoFailedRoles.add(role);notify(`The ${role} terminal could not connect: ${error.message}. Select Connect terminal to retry.`);}}finally{state.consoleConnectingRoles.delete(role);}}
function renderWorkspace(){
  const d=state.detail;if(!d)return;
  const lab=labFor(d.lab_id),drill=lab.drills.find(v=>v.id===state.drill),saved=passed(lab.id);
  const busy=d.jobs?.some(j=>["running","queued"].includes(j.state)),ready=d.state==="ready"&&!busy;
  const roles=d.paired?["sender","listener"]:["sender"];
  // Keep an active console grant and iframe mounted while an exercise action is
  // queued or running. Only a VM lifecycle transition invalidates its grant.
  if(d.state!=="ready"){state.consoleUrls={};state.consoleAutoFailedRoles.clear();}
  const completed=d.jobs?.find(j=>j.state==="complete"&&j.message&&["start","check","hint","solution"].includes(j.action)&&j.drill_id===state.drill);
  const brief=drill?`<p class="eyebrow">${esc(drill.id)}</p><h2>${esc(drill.title)}</h2><p>${esc(lab.id==="linux"?drill.brief.replace("Run lab shell in the Academy terminal to perform the commands.","Use the Academy terminal to perform the commands."):drill.brief)}</p><div class="goal"><p><strong>Your task</strong><br>${esc(drill.goal)}</p></div><p class="small muted"><strong>Useful tools:</strong> ${esc(drill.tools)}</p>${drill.diagram?`<figure class="exercise-diagram"><img src="${esc(drill.diagram)}" alt="${esc(drill.diagram_alt||"Exercise network diagram")}"><figcaption>${esc(drill.diagram_caption||"")}</figcaption></figure>`:""}${lab.id==="linux"?`<p class="small muted">Select Start exercise to prepare the lesson files. The terminal opens in the student workspace; use <code>ls ~/lab</code> to inspect the prepared folders.</p>`:""}<div class="button-row"><button class="primary" data-action="start" ${!ready?"disabled":""}>Start exercise</button><button class="secondary" data-action="check" ${!ready||d.active_drill!==drill.id?"disabled":""}>Check my work</button><button class="text-button" data-action="hint" ${!ready?"disabled":""}>Hint</button><button class="text-button" data-action="solution" ${!ready?"disabled":""}>Solution</button></div>`:`<h2>Your local workspace</h2><p>This VM provides the training environment included in its approved template. Open the terminal below to begin.</p>`;
  const consoleMarkup=`<div class="console-stack">${roles.map(role=>`<section class="console-window" data-console-window="${role}" aria-label="${role} terminal"><div class="console-heading"><span>${role==="sender"?"Sender":"Listener"} terminal · Private Ubuntu VM</span><button data-console="${role}" ${!ready?"disabled":""}>${state.consoleUrls[role]?"Reconnect":"Connect terminal"}</button></div><div class="console-host" data-console-host="${role}">${state.consoleUrls[role]?`<iframe data-console-frame="${role}" title="Private ${role} lab terminal" referrerpolicy="no-referrer" src="${esc(state.consoleUrls[role])}"></iframe>`:`<div class="console-placeholder" data-console-placeholder="${role}"><div><h3>${ready?"Ready when you are":"Preparing your environment"}</h3><p>${ready?`Connect the ${role} terminal to work in your private VM.`:esc(d.message)}</p></div></div>`}</div></section>`).join("")}</div>`;
  const markup=`<div class="work-header"><button class="back-button" data-page="sessions">← My lab sessions</button><div class="button-row">${badge(d.state,true)}${d.state==="error"?`<button class="secondary" data-action="retry" ${busy?"disabled":""}>Retry preparation</button>`:""}<button class="secondary" data-action="reset" ${!ready?"disabled":""}>Restore clean ${d.paired?"VM pair":"VM"}</button><button class="secondary" data-action="end" ${busy?"disabled":""}>End lab</button></div></div>`+startupMarkup(d)+heading(lab.title,d.message)+`<p class="small muted">Session ${esc(d.id.slice(0,8))} · Ends ${esc(date(d.expires))} · Results saved to your account</p><div class="workspace"><aside class="panel drill-panel"><h3>${lab.drills.length?"Exercise list":"Workspace"}</h3>${lab.drills.length?`<div class="drill-progress" role="progressbar" aria-label="Exercises completed" aria-valuemin="0" aria-valuemax="${lab.drills.length}" aria-valuenow="${Math.min(saved.size,lab.drills.length)}"><i style="width:${Math.min(100,Math.round(saved.size/lab.drills.length*100))}%"></i></div>`:""}<div class="drill-list">${lab.drills.length?lab.drills.map(v=>`<button class="drill-item ${v.id===state.drill?"selected":""} ${saved.has(v.id)?"is-complete":""}" data-drill="${esc(v.id)}"><span class="drill-title-row"><span>${esc(v.title)}</span>${saved.has(v.id)?'<span class="drill-status drill-check" aria-label="Completed">✓</span>':`<span class="drill-status" aria-hidden="true">${v.id===state.drill?"•":""}</span>`}</span><small>${esc(v.time||"Self-paced")} · Level ${esc(v.level||"1")}</small></button>`).join(""):`<p class="muted small" style="padding:20px">Use your approved local guides to work through this environment.</p>`}</div></aside><section class="workspace-main"><article class="panel brief">${brief}${busy?`<p class="small muted" role="status">The lab is applying your request. Controls will be available when it finishes.</p>`:""}</article>${consoleMarkup}${completed?`<section class="panel output-panel"><h3>${completed.action==="check"?"Verification output":"Lab feedback"}</h3><pre>${esc(lab.id==="linux"?completed.message.replace("Academy terminal: run lab shell to enter trainee; exit returns to the VM.","The terminal opens in the student workspace."):completed.message)}</pre></section>`:""}</section></div>`;
  const content=$("content"),next=document.createElement("div");next.innerHTML=markup;
  const oldStack=content.querySelector(".console-stack"),nextStack=next.querySelector(".console-stack");
  if(oldStack&&nextStack&&roles.some(role=>state.consoleUrls[role])){
    for(const role of roles){
      const oldWindow=oldStack.querySelector(`[data-console-window="${role}"]`),newWindow=nextStack.querySelector(`[data-console-window="${role}"]`);
      const oldHeading=oldWindow.querySelector(".console-heading"),newHeading=newWindow.querySelector(".console-heading");if(oldHeading&&newHeading)oldHeading.replaceWith(newHeading);
      const host=oldWindow.querySelector(`[data-console-host="${role}"]`),incomingHost=newWindow.querySelector(`[data-console-host="${role}"]`);
      const oldFrame=host.querySelector(`[data-console-frame="${role}"]`),newFrame=incomingHost.querySelector(`[data-console-frame="${role}"]`);
      if(newFrame&&oldFrame&&oldFrame.getAttribute("src")===newFrame.getAttribute("src")){}
      else if(newFrame&&oldFrame)mountConsoleFrame(host,newFrame,oldFrame);
      else if(newFrame)mountConsoleFrame(host,newFrame);
      else oldFrame?.remove();
      const placeholder=host.querySelector(`[data-console-placeholder="${role}"]`),newPlaceholder=incomingHost.querySelector(`[data-console-placeholder="${role}"]`);
      if(newFrame)placeholder?.remove();else if(placeholder&&newPlaceholder)placeholder.replaceWith(newPlaceholder);
      else if(!placeholder&&newPlaceholder)host.append(newPlaceholder);
    }
    // Keep the live stack mounted so both active Guacamole iframes survive
    // exercise feedback, polling updates, and changes to the selected exercise.
    for(const selector of [".work-header",".page-heading",".workspace>aside.drill-panel",".workspace-main>.brief"]){const current=content.querySelector(selector),updated=next.querySelector(selector);if(current&&updated)current.replaceWith(updated);}
    const oldMeta=content.querySelector(".page-heading + p.small.muted"),newMeta=next.querySelector(".page-heading + p.small.muted");if(oldMeta&&newMeta)oldMeta.replaceWith(newMeta);
    const oldOutput=content.querySelector(".workspace-main>.output-panel"),newOutput=next.querySelector(".workspace-main>.output-panel");if(oldOutput&&newOutput)oldOutput.replaceWith(newOutput);else if(oldOutput)oldOutput.remove();else if(newOutput)content.querySelector(".workspace-main").append(newOutput);
  }else content.innerHTML=markup;
  content.querySelectorAll(".console-window iframe").forEach(frame=>window.academyTerminalFocus.attach(frame));
}
function renderResults(){
  const rows=state.results;
  $("content").innerHTML=heading("My results","Your lab, class and video credit in one place.",`<a class="secondary" href="/api/results.csv">Export lab CSV</a>`)+
    (rows.length?`<div class="panel table-scroll"><table><thead><tr><th>Exercise</th><th>Lab</th><th>Result</th><th>Verified</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${esc(labFor(r.lab_id)?.drills.find(d=>d.id===r.drill_id)?.title||r.drill_id)}</strong></td><td>${esc(labFor(r.lab_id)?.title||r.lab_id)}</td><td><span class="status-pill ${r.passed?"ready":""}">${r.passed?"Passed":"Not yet"}</span></td><td>${esc(date(r.created))}</td></tr>`).join("")}</tbody></table></div>`:`<div class="empty"><h2>No lab results yet</h2><p class="muted">Complete an exercise and select Check my work to record a result.</p></div>`)+
    `<div id="video-results"></div><div id="class-results"></div><div id="academy-assessment-results"></div>`;
  loadVideoCredits().catch(error=>notify(error.message));
  loadClassResults().catch(error=>notify(error.message));
  loadAcademyAssessmentResults().catch(error=>notify(error.message));
}
async function loadVideoCredits(){
  const credits=await api("/videos/credits");
  const target=$("video-results");
  if(!target)return;
  target.innerHTML=`<div class="section-title"><h2>Video completions</h2><span class="small muted">${credits.length} credited</span></div>`+
    (credits.length?`<div class="session-list">${credits.map(item=>`<article class="session-row"><div><h3>${esc(item.title)}</h3><p class="muted">${esc(item.author)} / ${esc(item.topic)}</p></div><span class="status-pill ready">Completed ${esc(date(item.completed_at))}</span></article>`).join("")}</div>`:
      `<p class="muted">Watch a video through to the end to earn credit here.</p>`);
}
async function reviewAssessment(id){const result=await api(`/academy-assessments/attempts/${encodeURIComponent(id)}`);if(result.status!=="graded")throw new Error("This assessment is not ready for review");state.assessment=result;state.assessmentIndex=null;await page("assessments");}
async function renderAssessments({showCatalog=false}={}){
  const catalog=await api("/academy-assessments");state.assessmentCatalog=catalog;
  const active=catalog.attempts.find(item=>item.status==="in_progress");
  if(!showCatalog&&!state.assessment&&active)state.assessment=await api(`/academy-assessments/attempts/${active.id}`);
  if(state.assessment){renderAssessmentAttempt(state.assessment);return;}
  const cards=["overall","graduation"].map(kind=>{
    const data=catalog.assessments[kind],latest=catalog.attempts.find(item=>item.kind===kind&&item.status==="graded");
    const title=kind==="overall"?"Overall readiness assessment":"Academy graduation assessment";
    const description=kind==="overall"?"Find strengths and gaps across Academy classes and lab topics. Your score by area creates a recommended learning path.":"Show what you have learned across the Academy. The comprehensive exam covers every knowledge area and uses an 80% passing score.";
    const inProgress=catalog.attempts.find(item=>item.kind===kind&&item.status==="in_progress");
    return `<article class="panel academy-assessment-card"><p class="eyebrow">${kind==="overall"?"START HERE":"WHEN YOU ARE READY TO GRADUATE"}</p><h2>${title}</h2><p>${description}</p><p class="small muted">${data.question_count} distinct questions · Randomized order</p><p class="small muted">${latest?`Latest: ${latest.score}% · ${esc(date(latest.submitted))}`:"No attempt yet"}</p>${data.question_count?`<button class="primary" data-assessment-start="${kind}">${inProgress?"Continue assessment":latest?"Retake assessment":"Begin assessment"}</button>`:`<span class="status-pill">Question bank not loaded</span>`}</article>`;
  }).join("");
  const adminTools=state.user.role==="admin"?`<section class="panel academy-assessment-admin"><h2>Assessment question bank</h2><p>Upload the separate question bank. The server rejects repeated prompts against module quizzes, class final exams, and the other Academy-wide assessment. Answer keys stay on the server.</p><form id="assessment-bank-form"><label for="assessment-bank-file">Assessment bank JSON</label><input id="assessment-bank-file" type="file" accept="application/json,.json" required><p class="small muted">Each assessment may contain up to 100 questions.</p><button class="secondary" type="submit">Validate and load question bank</button></form></section>`:"";
  const history=catalog.attempts.filter(item=>item.status==="graded").slice(0,8);
  const attempts=history.length?`<section class="panel academy-assessment-history"><h2>Recent assessments</h2><div class="table-scroll"><table><thead><tr><th>Assessment</th><th>Score</th><th>Result</th><th>Date</th><th>Knowledge areas</th><th>Review</th></tr></thead><tbody>${history.map(item=>`<tr><td>${item.kind==="overall"?"Overall readiness":"Graduation"}</td><td>${item.score}%</td><td>${item.passed===null?"Diagnostic":item.passed?"Passed":"Not passed"}</td><td>${esc(date(item.submitted))}</td><td>${Object.entries(item.area_scores).map(([area,value])=>`${esc(area)} ${value.score}%`).join(" · ")}</td><td><button class="text-button" data-assessment-review="${esc(item.id)}" aria-label="Review ${esc(item.username?item.username+' · ':'')}${item.kind==='overall'?'Overall readiness':'Graduation'} result from ${esc(date(item.submitted||item.created))}">Review result</button></td></tr>`).join("")}</tbody></table></div></section>`:"";
  let adminResults="";
  if(state.user.role==="admin"){
    const rows=await api("/admin/academy-assessment-results");
    adminResults=`<section class="panel academy-assessment-history"><h2>All learner assessment results</h2>${rows.length?`<div class="table-scroll"><table><thead><tr><th>Learner</th><th>Assessment</th><th>Score</th><th>Result</th><th>Knowledge areas</th><th>Date</th><th>Review</th></tr></thead><tbody>${rows.map(item=>`<tr><td>${esc(item.username)}</td><td>${item.kind==="overall"?"Overall readiness":"Graduation"}</td><td>${item.score===null?"—":item.score+"%"}</td><td>${item.passed===null?"Diagnostic":item.passed?"Passed":"Not passed"}</td><td>${Object.entries(item.area_scores||{}).map(([area,value])=>{const delta=item.area_growth?.[area];return `${esc(area)} ${value.score}%${delta===undefined?"":delta===null?" (first score)":` (${delta>=0?"+":""}${delta} points)`}`}).join(" · ")||"In progress"}</td><td>${esc(date(item.submitted||item.created))}</td><td>${item.status==="graded"?`<button class="text-button" data-assessment-review="${esc(item.id)}" aria-label="Review ${esc(item.username?item.username+' · ':'')}${item.kind==='overall'?'Overall readiness':'Graduation'} result from ${esc(date(item.submitted||item.created))}">Review result</button>`:"—"}</td></tr>`).join("")}</tbody></table></div>`:"<p class=\"muted\">No Academy-wide assessment attempts yet.</p>"}</section>`;
  }
  $("content").innerHTML=heading("Academy assessments","Start with a readiness check. Return for the graduation assessment after completing the recommended classes and labs.")+`<div class="academy-assessment-grid">${cards}</div>${adminTools}${attempts}${adminResults}`;
}
function renderAssessmentAttempt(attempt){
  const overall=attempt.kind==="overall",title=overall?"Overall readiness assessment":"Academy graduation assessment",editable=attempt.status==="in_progress";
  const nav=`<div class="assessment-topline"><button type="button" class="back-button" data-assessment-back>← All assessments</button><span>${attempt.questions.length} questions</span></div>`;
  if(editable){
    if(state.assessmentIndex===null){const firstUnanswered=attempt.questions.findIndex(question=>!(question.id in attempt.answers));state.assessmentIndex=firstUnanswered<0?attempt.questions.length-1:firstUnanswered;}
    state.assessmentIndex=Math.min(state.assessmentIndex,attempt.questions.length-1);
    const index=state.assessmentIndex,question=attempt.questions[index],answered=Object.keys(attempt.answers).length;
    $("content").innerHTML=heading(title,overall?"Answer each question to get a score by knowledge area and a suggested learning order.":"Answer each question. A score of 80% is required to pass.")+nav+`<form id="academy-assessment-form" class="academy-assessment-form"><div class="notice">Questions are mixed in a random order. Select an answer before Next. You cannot return to earlier questions. Subject labels and explanations appear after submission.</div><p class="small muted" role="status">${answered} of ${attempt.questions.length} answered</p><section class="panel exam-question" id="assessment-question"><p class="eyebrow">QUESTION ${index+1} OF ${attempt.questions.length}</p><h2 tabindex="-1">${esc(question.prompt)}</h2>${question.choices.map((choice,option)=>`<label class="exam-choice"><input type="radio" name="${esc(question.id)}" value="${option}" ${attempt.answers[question.id]===option?"checked":""}><span>${esc(choice)}</span></label>`).join("")}</section><div class="learning-toolbar"><button type="button" class="secondary" data-assessment-save>Save progress</button>${index<attempt.questions.length-1?'<button type="button" class="primary" data-assessment-next>Next question</button>':'<button type="submit" class="primary">Submit assessment</button>'}</div></form>`;
    return;
  }
  const areaRows=Object.entries(attempt.area_scores||{}).sort((a,b)=>a[0].localeCompare(b[0])).map(([area,value])=>`<tr><td>${esc(area)}</td><td>${value.score}%</td><td>${value.correct} / ${value.question_count}</td></tr>`).join("");
  const recs=overall?`<section class="panel academy-recommendations"><h2>Recommended next steps</h2>${attempt.recommendations.length?`<ol>${attempt.recommendations.map(item=>`<li><strong>${item.type==="class"?"Class":item.type==="game"?"Game":"Lab"}:</strong> ${esc(item.title)} <span class="small muted">${esc(item.area)} · ${item.area_score===undefined?"area result":"assessment score "+item.area_score+"%"} · ${esc(item.reason)}${item.type==="lab"&&!item.available?" · Not yet available":""}</span>${item.type==="game"?` <a href="/games" data-page="games">Browse learning games</a>`:""}</li>`).join("")}</ol>`:`<p>No matching classes, labs, or games are available for the areas that need practice. Ask the administrator to review published content and the assessment bank’s curriculum tags.</p>`}</section>`:"";
  $("content").innerHTML=heading(title,attempt.username?`Result for ${attempt.username}.`:"Your result is saved in My Results for you and your administrator.")+nav+`<section class="panel assessment-result"><p class="eyebrow">${overall?"DIAGNOSTIC RESULT":"GRADUATION RESULT"}</p><h2>${attempt.score}% ${overall?"overall":attempt.passed?"· Passed":"· Below 80% passing"}</h2><p>${overall?"The overall score is diagnostic. Use the area scores and learning path to plan what to take next.":attempt.passed?"The 80% Academy graduation standard was met.":"Review the results, strengthen gaps, then retake when ready."}</p><div class="table-scroll"><table><thead><tr><th>Knowledge area</th><th>Score</th><th>Correct</th></tr></thead><tbody>${areaRows}</tbody></table></div><p class="small muted">${esc(date(attempt.submitted))} · ${attempt.questions.length} questions</p></section>${recs}<details class="panel assessment-review"><summary>Review questions and explanations</summary>${attempt.questions.map((question,index)=>`<article class="assessment-review-item"><p class="eyebrow">${esc(question.area)} · QUESTION ${index+1}</p><h3>${esc(question.prompt)}</h3><p><strong>${attempt.answers[question.id]===attempt.correct_answers[question.id]?"Correct":"Incorrect"}</strong> · Answer: ${esc(question.choices[attempt.answers[question.id]])}</p><p>Correct answer: ${esc(question.choices[attempt.correct_answers[question.id]])}</p><p>${esc(question.explanation)}</p>${question.selected_explanation?`<p class="small muted">${esc(question.selected_explanation)}</p>`:""}</article>`).join("")}</details>`;
}
async function saveAssessmentProgress(showMessage=false){
  const form=$("academy-assessment-form"),answers={...state.assessment.answers};
  for(const [id,value] of new FormData(form))answers[id]=Number(value);
  state.assessment=await api(`/academy-assessments/attempts/${state.assessment.id}`,"PUT",{answers});
  if(showMessage)notify("Assessment progress saved");
}
async function loadAcademyAssessmentResults(){
  const host=$("academy-assessment-results");if(!host)return;const data=await api("/academy-assessments");if(!$("academy-assessment-results"))return;
  const attempts=data.attempts.filter(item=>item.status==="graded").slice().reverse(),previous={};
  const rows=attempts.map(item=>{const key=item.kind,label=item.kind==="overall"?"Overall readiness":"Graduation",areas=Object.entries(item.area_scores||{}).map(([area,value])=>{const before=previous[key]?.[area],change=before===undefined?"First score":`${value.score-before>=0?"+":""}${(value.score-before).toFixed(2)} points`;return `${esc(area)}: ${value.score}% (${change})`;}).join(" · ");previous[key]=Object.fromEntries(Object.entries(item.area_scores||{}).map(([area,value])=>[area,value.score]));return `<tr><td>${label}</td><td>${item.score}%</td><td>${item.passed===null?"Diagnostic":item.passed?"Passed":"Not passed"}</td><td>${esc(date(item.submitted))}</td><td>${areas}</td><td><button class="text-button" data-assessment-review="${esc(item.id)}" aria-label="Review ${esc(item.username?item.username+' · ':'')}${item.kind==='overall'?'Overall readiness':'Graduation'} result from ${esc(date(item.submitted||item.created))}">Review result</button></td></tr>`;});
  host.innerHTML=`<section class="panel academy-assessment-history"><h2>Academy-wide assessment growth</h2><p class="small muted">Area changes compare each attempt with your previous attempt of the same assessment.</p>${rows.length?`<div class="table-scroll"><table><thead><tr><th>Assessment</th><th>Total score</th><th>Outcome</th><th>Date</th><th>Area scores and growth</th><th>Review</th></tr></thead><tbody>${rows.reverse().join("")}</tbody></table></div>`:`<p class="muted">Complete the Overall readiness assessment to begin tracking Academy-wide growth.</p><a class="primary link-button" href="/assessments" data-page="assessments">Take an assessment</a>`}</section>`;
}
function renderAccount(){$("content").innerHTML=heading("My account","Keep your local academy password current.")+`<form id="password-form" class="panel form-panel" style="max-width:560px"><h3>${esc(state.user.username)}</h3><label for="current-password">Current password</label><input id="current-password" type="password" autocomplete="current-password" required><label for="new-password">New password</label><input id="new-password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><p class="small muted">Use at least 12 characters. Other signed-in sessions will be revoked.</p><button class="primary">Update password</button></form>`;}
function renderBugReport(){$("content").innerHTML=heading("Report a Bug","Send a problem report to the training administrator.")+`<form id="bug-report-form" class="panel form-panel bug-report-form-panel"><h2>What went wrong?</h2><p class="muted">Your report goes to the administrator’s private inbox. Describe what you were doing and what happened.</p><label for="bug-report-username">Signed in as</label><input id="bug-report-username" type="text" value="${esc(state.user.username)}" readonly aria-readonly="true"><label for="bug-report-message">Issue description</label><textarea id="bug-report-message" name="message" rows="9" minlength="10" maxlength="5000" placeholder="Include the page or lab, what you expected, and what happened." required></textarea><p class="small muted">Do not include passwords, recovery codes, or other sensitive information.</p><button class="primary" type="submit">Send report</button></form>`;}
async function renderBugReports(){const reports=await api("/admin/bug-reports");const unread=reports.filter(report=>!report.read_at).length;const count=$("bug-report-count");count.textContent=unread;count.hidden=unread===0;const items=reports.map(report=>`<article class="panel bug-report-card"><div class="bug-report-meta"><div><h2>${esc(report.username)}</h2><p class="small muted">${esc(date(report.created))}</p></div><span class="status-pill ${report.read_at?"":"ready"}">${report.read_at?"Read":"New"}</span></div><p class="bug-report-message">${esc(report.message)}</p>${report.read_at?"":`<button class="secondary" type="button" data-bug-read="${esc(report.id)}">Mark as read</button>`}</article>`).join("");$("content").innerHTML=heading("Bug report inbox","Private reports submitted by Academy users.",`<button class="secondary" type="button" data-bug-refresh>Refresh</button>`)+(reports.length?`<div class="bug-report-list">${items}</div>`:`<div class="empty"><h2>No bug reports yet</h2><p class="muted">New user reports will appear here.</p></div>`);}
async function renderVideos(){const library=await api("/videos");state.videoAvailable=library.available;state.videoItems=library.videos;renderVideoLibrary();}
async function renderGames(){state.games=await api("/games");const game=state.games.find(item=>item.id===state.gameId);if(state.gameId&&!game)state.gameId=null;const player=game?`<section class="panel game-player"><div class="game-player-heading"><div><p class="eyebrow">${esc(game.category)}</p><h2>${esc(game.title)}</h2><p class="muted">${esc(game.description)}</p></div><button class="secondary" data-game-back>Back to games</button></div><iframe class="game-player-frame" title="${esc(game.title)}" sandbox="allow-scripts" referrerpolicy="no-referrer" src="/api/games/${esc(game.id)}/play"></iframe><p class="small muted">Progress saves to your signed-in account. The isolated game cannot access Academy data, cookies, or APIs directly. Remote resources are blocked.</p></section>`:"";const cards=state.games.map(item=>`<article class="panel game-card"><div class="game-card-mark" aria-hidden="true">✦</div><p class="eyebrow">${esc(item.category)}</p><h2>${esc(item.title)}</h2><p>${esc(item.description||"A self-paced learning game.")}</p><p class="small muted">${Math.max(1,Math.ceil(item.size/1024))} KB · Available offline</p><button class="primary" data-game-play="${esc(item.id)}">Play game</button></article>`).join("");const content=$("content");content.classList.toggle("game-active",Boolean(game));content.innerHTML=heading("Learning games","Practice concepts in short interactive games built for the Academy.")+player+(cards?`<div class="game-grid">${cards}</div>`:`<div class="empty"><h2>No games available yet</h2><p class="muted">Your training administrator will add learning games here.</p></div>`);}
let videoOrderSaving=false,videoPointerDrag=null;
function renderVideoLibrary(){
  const items=state.videoItems;
  const authors=[...new Set(items.map(video=>video.author))];
  if(!authors.includes(state.videoAuthor))state.videoAuthor=authors[0]||null;
  const byAuthor=items.filter(video=>video.author===state.videoAuthor);
  const topics=[...new Set(byAuthor.map(video=>video.topic))];
  if(!topics.includes(state.videoTopic))state.videoTopic=topics[0]||null;
  const byTopic=byAuthor.filter(video=>video.topic===state.videoTopic);
  if(!byTopic.some(video=>video.id===state.videoId))state.videoId=byTopic[0]?.id||null;
  const selected=byTopic.find(video=>video.id===state.videoId);
  const title=heading("Video library","Choose a creator and topic, then watch in this page.",'<button class="secondary" type="button" data-video-refresh>Refresh library</button>');
  if(!state.videoAvailable){$("content").innerHTML=title+'<div class="video-empty"><h2>Video storage is unavailable</h2><p class="muted">Try Refresh library. Your training administrator can check the media connection.</p></div>';return;}
  if(!items.length){$("content").innerHTML=title+'<div class="video-empty"><h2>No videos available yet</h2><p class="muted">Videos appear here when an administrator adds MP4 files under an author and topic.</p></div>';return;}
  const authorButtons=authors.map(author=>{const count=items.filter(video=>video.author===author).length;const active=author===state.videoAuthor;return `<button type="button" data-video-author="${esc(author)}" aria-pressed="${active}" class="${active?"selected":""}">${esc(author)}<small>${count} ${count===1?"video":"videos"}</small></button>`;}).join("");
  const topicButtons=topics.map(topic=>{const count=byAuthor.filter(video=>video.topic===topic).length;const active=topic===state.videoTopic;return `<button type="button" data-video-topic="${esc(topic)}" aria-pressed="${active}" class="${active?"selected":""}">${esc(topic)}<small>${count} ${count===1?"video":"videos"}</small></button>`;}).join("");
  const creditText=video=>video.completed_at?"Completed · credit recorded":video.watched_percent?`${video.watched_percent}% watched · no credit yet`:"Not completed";
  const canReorderVideos=state.user?.role==="admin";
  const videoButtons=byTopic.map(video=>`<div class="video-row ${canReorderVideos?"video-row-reorder":""}" data-video-row="${esc(video.id)}">${canReorderVideos?`<button type="button" class="video-drag-handle" data-video-drag="${esc(video.id)}" aria-label="Reorder ${esc(video.title)}" aria-keyshortcuts="ArrowUp ArrowDown" title="Drag to reorder. Focus this handle and press Up or Down to move.">⠿</button>`:""}<button type="button" class="video-item ${video.id===state.videoId?"selected":""}" data-video-id="${esc(video.id)}" aria-pressed="${video.id===state.videoId}"><strong>${esc(video.title)}</strong><span>${Math.max(1,Math.round(video.size_bytes/1048576))} MB · ${esc(video.topic)}</span><span class="video-credit ${video.completed_at?"complete":""}">${esc(creditText(video))}</span></button></div>`).join("");
  const orderHelp=canReorderVideos?'<p class="video-meta video-order-help">Drag the grip to reorder videos in this topic. You can also focus a grip and press Up or Down. Changes save for everyone.</p><p class="video-order-status" data-video-order-status role="status" aria-live="polite"></p>':'';
  const taxonomyEditor=canReorderVideos?`<div class="video-taxonomy-tools"><form class="video-taxonomy-editor" data-video-taxonomy data-source-author="${esc(state.videoAuthor)}" data-source-topic="${esc(state.videoTopic)}"><h3>Move or rename this topic</h3><p class="video-meta">Change the creator or topic for all ${byTopic.length} videos in this group.</p><label>Creator<input name="author" list="video-creators" maxlength="180" required value="${esc(state.videoAuthor)}"><datalist id="video-creators">${authors.map(author=>`<option value="${esc(author)}">`).join("")}</datalist></label><label>Topic<input name="topic" maxlength="180" required value="${esc(state.videoTopic)}"></label><button class="secondary" type="submit">Save this topic group</button><p class="video-order-status" data-video-taxonomy-status role="status" aria-live="polite"></p></form><form class="video-taxonomy-editor" data-video-creator data-source-author="${esc(state.videoAuthor)}"><h3>Rename creator everywhere</h3><p class="video-meta">Rename ${esc(state.videoAuthor)} across all topics and videos.</p><label>New creator name<input name="author" maxlength="180" required value="${esc(state.videoAuthor)}"></label><button class="secondary" type="submit">Rename creator</button><p class="video-order-status" data-video-creator-status role="status" aria-live="polite"></p></form></div>`:"";
  $("content").innerHTML=title+`<div class="video-browser"><aside class="video-filters" aria-label="Video filters"><section class="video-filter"><h2>Creators</h2><div class="video-filter-list">${authorButtons}</div></section><section class="video-filter"><h2>Topics</h2><div class="video-filter-list">${topicButtons}</div></section></aside><section class="video-main" aria-label="Video player"><p class="eyebrow">${esc(state.videoAuthor)} / ${esc(state.videoTopic)}</p><h2>${esc(selected.title)}</h2><p class="video-meta">Select Play to stream this video in the Academy.</p><video class="video-player" controls playsinline preload="metadata" controlslist="nodownload" aria-label="${esc(selected.title)}" src="/api/videos/${esc(selected.id)}/stream">Your browser cannot play this video.</video><p class="video-credit-status" data-video-credit role="status">${esc(creditText(selected))}</p><p class="video-meta">Credit is recorded when you reach the end after watching at least 90% of the video. Seeking past sections does not count.</p>${taxonomyEditor}<h2>Videos in this topic</h2>${orderHelp}<div class="video-items ${canReorderVideos?"video-items-reorder":""}">${videoButtons}</div></section></div>`;
  const player=$("content").querySelector("video");
  player.addEventListener("error",()=>notify("The video could not play. Refresh the library or contact your training administrator."));
  let lastSent=0,creditUnavailable=false,queue=Promise.resolve();
  function report(ended=false){
    if(creditUnavailable||selected.completed_at)return;
    lastSent=performance.now();
    const position=player.currentTime,playing=!player.paused&&!player.seeking&&!ended;
    queue=queue.then(()=>api(`/videos/${selected.id}/progress`,"POST",{position,playing,ended}))
      .then(result=>{selected.watched_percent=result.watched_percent;selected.completed_at=result.completed_at;if(state.page==="videos"&&state.videoId===selected.id){if(result.completed_at)renderVideoLibrary();else $("content").querySelector("[data-video-credit]").textContent=creditText(selected);}})
      .catch(error=>{creditUnavailable=true;notify(`Video credit could not be recorded: ${error.message}`);});
  }
  player.addEventListener("play",()=>report());
  player.addEventListener("timeupdate",()=>{if(performance.now()-lastSent>=5000)report();});
  player.addEventListener("pause",()=>{if(!player.ended)report();});
  player.addEventListener("seeked",()=>report());
  player.addEventListener("ended",()=>report(true));
}
async function saveVideoOrder(videoIds,focusId){
  if(videoOrderSaving||state.user?.role!=="admin")return;
  const ordered=state.videoItems.filter(video=>video.author===state.videoAuthor&&video.topic===state.videoTopic);
  if(videoIds.length!==ordered.length||new Set(videoIds).size!==ordered.length||videoIds.some(id=>!ordered.some(video=>video.id===id)))return;
  videoOrderSaving=true;
  const status=$("content").querySelector("[data-video-order-status]");
  if(status)status.textContent="Saving order…";
  let saved=false;
  try{
    await api("/admin/videos/order","PUT",{author:state.videoAuthor,topic:state.videoTopic,video_ids:videoIds});
    saved=true;
    notify("Video order saved for this topic");
  }catch(error){notify(`Could not save video order: ${error.message}`);}
  try{await renderVideos();}catch(error){notify(`Could not refresh the video list: ${error.message}`);}
  videoOrderSaving=false;
  const resultStatus=$("content").querySelector("[data-video-order-status]");
  if(resultStatus)resultStatus.textContent=saved?"Order saved.":"Order was not saved. The previous order was restored.";
  if(focusId){const handle=[...document.querySelectorAll("[data-video-drag]")].find(item=>item.dataset.videoDrag===focusId);handle?.focus();}
}
document.addEventListener("keydown",event=>{
  const handle=event.target.closest?.("[data-video-drag]");
  if(!handle||state.user?.role!=="admin"||!(event.key==="ArrowUp"||event.key==="ArrowDown"))return;
  const list=handle.closest(".video-items"),rows=[...list.querySelectorAll("[data-video-row]")],from=rows.indexOf(handle.closest("[data-video-row]")),to=from+(event.key==="ArrowUp"?-1:1);
  if(to<0||to>=rows.length)return;
  event.preventDefault();
  if(to<from)list.insertBefore(rows[from],rows[to]);else list.insertBefore(rows[to],rows[from]);
  saveVideoOrder([...list.querySelectorAll("[data-video-row]")].map(row=>row.dataset.videoRow),handle.dataset.videoDrag);
});
document.addEventListener("pointerdown",event=>{
  const handle=event.target.closest?.("[data-video-drag]");
  if(!handle||state.user?.role!=="admin"||videoOrderSaving||event.button!==0)return;
  const list=handle.closest(".video-items-reorder");
  if(!list)return;
  videoPointerDrag={id:handle.dataset.videoDrag,pointerId:event.pointerId,list,handle,initialIds:[...list.querySelectorAll("[data-video-row]")].map(row=>row.dataset.videoRow)};
  handle.setPointerCapture(event.pointerId);
  handle.closest("[data-video-row]").classList.add("is-dragging");
});
document.addEventListener("pointermove",event=>{
  const drag=videoPointerDrag;
  if(!drag||drag.pointerId!==event.pointerId)return;
  const target=document.elementFromPoint(event.clientX,event.clientY),row=target?.closest("[data-video-row]");
  if(!row||row.parentElement!==drag.list)return;
  const source=[...drag.list.querySelectorAll("[data-video-row]")].find(item=>item.dataset.videoRow===drag.id);
  if(!source||source===row)return;
  event.preventDefault();
  const placeAfter=event.clientY>row.getBoundingClientRect().top+row.offsetHeight/2;
  for(const item of drag.list.querySelectorAll("[data-video-row]"))item.classList.remove("drop-before","drop-after");
  row.classList.add(placeAfter?"drop-after":"drop-before");
  const reference=placeAfter?row.nextSibling:row;
  if(reference!==source)drag.list.insertBefore(source,reference);
});
document.addEventListener("pointerup",event=>{
  const drag=videoPointerDrag;
  if(!drag||drag.pointerId!==event.pointerId)return;
  videoPointerDrag=null;
  for(const row of drag.list.querySelectorAll("[data-video-row]"))row.classList.remove("is-dragging","drop-before","drop-after");
  const videoIds=[...drag.list.querySelectorAll("[data-video-row]")].map(row=>row.dataset.videoRow);
  if(videoIds.some((id,index)=>id!==drag.initialIds[index]))saveVideoOrder(videoIds,drag.id);
});
document.addEventListener("pointercancel",event=>{
  const drag=videoPointerDrag;
  if(!drag||drag.pointerId!==event.pointerId)return;
  videoPointerDrag=null;
  renderVideos().catch(error=>notify(`Could not restore video order: ${error.message}`));
});
document.addEventListener("click",async event=>{
  const target=event.target.closest("button[data-video-author],button[data-video-topic],button[data-video-id],button[data-video-refresh]");
  if(!target||!state.user)return;
  try{
    if(target.hasAttribute("data-video-refresh"))await renderVideos();
    else if(target.hasAttribute("data-video-author")){state.videoAuthor=target.dataset.videoAuthor;state.videoTopic=null;state.videoId=null;renderVideoLibrary();}
    else if(target.hasAttribute("data-video-topic")){state.videoTopic=target.dataset.videoTopic;state.videoId=null;renderVideoLibrary();}
    else if(target.hasAttribute("data-video-id")){state.videoId=target.dataset.videoId;renderVideoLibrary();}
  }catch(error){notify(error.message);}
});
document.addEventListener("submit",async event=>{
  const form=event.target.closest?.("form[data-video-taxonomy]");
  const creatorForm=event.target.closest?.("form[data-video-creator]");
  if((!form&&!creatorForm)||state.user?.role!=="admin")return;
  event.preventDefault();
  const activeForm=form||creatorForm,data=new FormData(activeForm),isCreatorRename=Boolean(creatorForm),author=String(data.get("author")||"").trim(),topic=String(data.get("topic")||"").trim();
  const status=activeForm.querySelector(isCreatorRename?"[data-video-creator-status]":"[data-video-taxonomy-status]");
  if(!author||(!isCreatorRename&&!topic)){status.textContent="Creator and topic are required.";return;}
  const submit=activeForm.querySelector("button[type=submit]");submit.disabled=true;status.textContent=isCreatorRename?"Renaming creator…":"Saving topic group…";
  try{
    if(isCreatorRename){
      await api("/admin/videos/creator","PUT",{source_author:activeForm.dataset.sourceAuthor,author});
      state.videoAuthor=author;
    }else{
      await api("/admin/videos/taxonomy","PUT",{source_author:activeForm.dataset.sourceAuthor,source_topic:activeForm.dataset.sourceTopic,author,topic});
      state.videoAuthor=author;state.videoTopic=topic;
    }
    state.videoId=null;await renderVideos();notify(isCreatorRename?"Creator renamed across all topics":"Creator and topic saved for this video group");
  }catch(error){status.textContent=`Could not save changes: ${error.message}`;submit.disabled=false;}
});
async function renderAdmin(){
  const info=await api("/admin/overview");
  state.users=info.users;
  if(state.examResetUserId&&!info.users.some(user=>user.id===state.examResetUserId))state.examResetUserId=null;
  const resetCatalog=state.examResetUserId?await api(`/admin/users/${state.examResetUserId}/exam-resets`):null;
  const resetPanel=resetCatalog?`<section class="panel" aria-labelledby="exam-reset-heading"><h3 id="exam-reset-heading">Exam retakes for ${esc(resetCatalog.username)}</h3><p class="small muted">Choose one exam or reset all exams for this account. Graded results, audit history, and class progress stay saved. An unfinished attempt is closed to new edits.</p><label for="admin-exam-scope">Exam</label><select id="admin-exam-scope">${resetCatalog.options.map(option=>`<option value="${esc(option.scope)}">${esc(option.label)}</option>`).join("")}</select><div class="button-row"><button type="button" class="secondary" data-admin-exam-reset="selected" ${resetCatalog.options.length?"":"disabled"}>Reset selected exam</button><button type="button" class="secondary" data-admin-exam-reset="all">Reset all exams</button><button type="button" class="text-button" data-admin-exam-close>Close</button></div></section>`:"";
  const seen=info.worker_last_seen?date(info.worker_last_seen):"No worker heartbeat received";
  const accounts=info.users.map(u=>{
    const self=state.user.username===u.username;
    const actions=u.enabled
      ? `${self?"":`<button type="button" class="text-button" data-admin-reset="${esc(u.id)}">Reset password</button>`}${self?"":`<button type="button" class="text-button danger-link" data-admin-remove="${esc(u.id)}">Remove</button>`}`
      : `<button type="button" class="text-button" data-admin-restore="${esc(u.id)}">Restore</button>`;
    return `<tr><td>${esc(u.username)}${self?' <span class="muted small">(you)</span>':""}</td><td>${esc(u.role)}</td><td><span class="account-state ${u.enabled?"":"removed"}">${u.enabled?"Active":"Removed"}</span></td><td><div class="account-actions"><button type="button" class="text-button" data-admin-exams="${esc(u.id)}">Exam retakes</button>${actions}</div></td></tr>`;
  }).join("");
  $("content").innerHTML=heading("Administration","Create accounts, reset passwords, remove access and manage lab seats.",`<button class="secondary" data-page="content">Manage classes and upload slides</button><button class="primary" data-learning="new-lab">Add lab</button>`)
    +`<div class="notice"><strong>Worker:</strong> ${esc(seen)} · ${info.sessions.length} / ${info.capacity} seats assigned. Lab templates remain unavailable until you activate them.</div>
    <div class="panel"><h3>Lab templates</h3><p class="admin-lab-note">Enter Proxmox template IDs after each template passes its offline checks. Paired labs reserve both VMs together and keep the learner terminals separate.</p>${state.labs.map(l=>`<form class="lab-settings" data-lab-settings="${esc(l.id)}"><div class="settings-row"><strong>${esc(l.title)}</strong><label>Sender / VM ID<input type="number" name="template_id" aria-label="${esc(l.title)} sender template VM ID" min="100" value="${l.template_id||""}" required></label>${l.paired||l.secondary_template_id?`<label>Listener template VM ID<input type="number" name="secondary_template_id" aria-label="${esc(l.title)} listener template VM ID" min="100" value="${l.secondary_template_id||""}"></label>`:""}<label>Cores<input type="number" name="cores" min="1" max="16" value="${l.cores}" required></label><label>RAM MB<input type="number" name="memory" min="1024" max="32768" value="${l.memory}" required></label><label><input type="checkbox" name="enabled" ${l.enabled?"checked":""}> Active</label></div><button class="secondary">Save ${esc(l.title)}</button></form>`).join("")}</div>
    <div class="admin-grid"><form id="user-form" class="panel form-panel"><h3>Add a local account</h3><label for="new-username">Username</label><input id="new-username" name="username" pattern="[A-Za-z0-9_.-]{3,64}" required autocomplete="off"><label for="user-password">Initial password</label><input id="user-password" name="password" type="password" minlength="12" maxlength="128" required autocomplete="new-password"><label for="user-role">Role</label><select id="user-role" name="role"><option value="learner">Learner</option><option value="admin">Administrator</option></select><button class="primary">Create account</button></form>
    <div class="panel"><h3>Local accounts</h3><p class="small muted">Removing an account blocks sign-in and ends its lab sessions. Learning records are retained; removed accounts can be restored.</p><div class="table-scroll"><table><thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>${accounts||'<tr><td colspan="4">No accounts</td></tr>'}</tbody></table></div></div></div>${resetPanel}
    <div class="section-title"><h2>Assigned lab seats</h2><button class="text-button" data-refresh-admin>Refresh</button></div><div class="panel table-scroll"><table><thead><tr><th>Learner</th><th>Lab</th><th>VM</th><th>State</th><th>Action</th></tr></thead><tbody>${info.sessions.map(v=>`<tr><td>${esc(v.username)}</td><td>${esc(labFor(v.lab_id)?.title)}</td><td>${esc(v.vmid)}</td><td>${badge(v.state)}</td><td><button class="text-button" data-admin-end="${esc(v.id)}">Release seat</button></td></tr>`).join("")||'<tr><td colspan="5">No active sessions</td></tr>'}</tbody></table></div>`;
}
async function confirmAction(title,text){$("confirm-title").textContent=title;$("confirm-text").textContent=text;const dialog=$("confirm-dialog");dialog.showModal();return new Promise(resolve=>dialog.addEventListener("close",()=>resolve(dialog.returnValue==="confirm"),{once:true}));}
async function confirmGameLeave(){try{await requestGameProgressFlush();return true;}catch(error){const leave=await confirmAction("Leave without confirmed progress save?","The Academy could not confirm this game’s latest save. You may lose recent progress. Choose Cancel to stay in the game and try again.");if(!leave)notify(error.message);return leave;}}
document.addEventListener("click",async event=>{
  const target=event.target.closest("[data-page],button[data-launch],button[data-open],button[data-action],button[data-drill],button[data-console],button[data-refresh-admin],button[data-admin-end],button[data-admin-reset],button[data-admin-remove],button[data-admin-restore],button[data-admin-exams],button[data-admin-exam-reset],button[data-admin-exam-close],button[data-admin-password-cancel],button[data-bug-read],button[data-bug-refresh],button[data-game-play],button[data-game-back],button[data-assessment-start],button[data-assessment-review],button[data-assessment-back],button[data-assessment-save],button[data-assessment-next]");
  if(!target||target.disabled)return;
  try{
    if(target.dataset.page){event.preventDefault();await page(target.dataset.page);}
    else if(target.dataset.assessmentStart){state.assessment=await api(`/academy-assessments/${target.dataset.assessmentStart}/attempts`,"POST",{});state.assessmentIndex=null;renderAssessmentAttempt(state.assessment);}
    else if(target.dataset.assessmentReview)await reviewAssessment(target.dataset.assessmentReview);
    else if(target.hasAttribute("data-assessment-back")){if(state.assessment?.status==="in_progress")await saveAssessmentProgress();state.assessment=null;state.assessmentIndex=null;await renderAssessments({showCatalog:true});}
    else if(target.hasAttribute("data-assessment-save")){target.disabled=true;await saveAssessmentProgress(true);target.disabled=false;renderAssessmentAttempt(state.assessment);}
    else if(target.hasAttribute("data-assessment-next")){const question=state.assessment.questions[state.assessmentIndex];if(!$("academy-assessment-form").querySelector(`input[name="${CSS.escape(question.id)}"]:checked`)){notify("Select an answer before moving to the next question.");return;}target.disabled=true;await saveAssessmentProgress();state.assessmentIndex++;renderAssessmentAttempt(state.assessment);$("assessment-question").querySelector("h2").focus();}
    else if(target.dataset.gamePlay){state.gameId=target.dataset.gamePlay;await renderGames();}
    else if(target.hasAttribute("data-game-back")){if(!await confirmGameLeave())return;state.gameId=null;await renderGames();}
    else if(target.dataset.launch){target.disabled=true;const value=await api("/sessions","POST",{lab_id:target.dataset.launch});await refresh();await openSession(value.id);}
    else if(target.dataset.bugRead){await api(`/admin/bug-reports/${target.dataset.bugRead}/read`,"PUT",{});await renderBugReports();}
    else if(target.hasAttribute("data-bug-refresh"))await renderBugReports();
    else if(target.dataset.open)await openSession(target.dataset.open);
    else if(target.dataset.drill){state.drill=target.dataset.drill;renderWorkspace();}
    else if(target.hasAttribute("data-console"))await connectConsole(true,target.dataset.console);
    else if(target.dataset.action){const action=target.dataset.action;if(["reset","end","solution"].includes(action)){const text={reset:"This replaces your VM with a clean copy. Files and unfinished work in this VM will be removed. Your recorded results stay in your account.",end:"This deletes your assigned VM and its files. Your recorded exercise results remain available.",solution:"This displays the full walkthrough for the selected exercise."}[action];if(!await confirmAction({reset:"Restore a clean VM?",end:"End this lab?",solution:"Show the solution?"}[action],text))return;}await api(`/sessions/${state.current}/actions`,"POST",{action,drill_id:state.drill||""});if(["reset","end"].includes(action))state.consoleUrls={};state.detail=await api("/sessions/"+state.current);renderWorkspace();notify("Lab request queued");}
    else if(target.hasAttribute("data-refresh-admin")){await refresh();await renderAdmin();}
    else if(target.dataset.adminExams){state.examResetUserId=target.dataset.adminExams;await renderAdmin();$("admin-exam-scope").focus();}
    else if(target.hasAttribute("data-admin-exam-close")){state.examResetUserId=null;await renderAdmin();}
    else if(target.dataset.adminExamReset){const user=state.users.find(item=>item.id===state.examResetUserId);const scope=target.dataset.adminExamReset==="all"?"all":$("admin-exam-scope").value;const label=scope==="all"?"all exams":$("admin-exam-scope").selectedOptions[0].textContent;if(user&&await confirmAction(`Reset ${label} for ${user.username}?`,"This opens a new attempt and prevents editing an unfinished earlier attempt. Graded results, audit history, and class progress stay saved.")){const result=await api(`/admin/users/${user.id}/exam-resets`,"POST",{scope});await renderAdmin();notify(result.message);}}
    else if(target.dataset.adminEnd){if(await confirmAction("Release this learner’s seat?","The assigned VM and its files will be deleted. Recorded results will be retained.")){await api("/admin/sessions/"+target.dataset.adminEnd+"/end","POST",{});await renderAdmin();}}
    else if(target.dataset.adminReset){const user=state.users.find(u=>u.id===target.dataset.adminReset);$("admin-password-form").dataset.userId=target.dataset.adminReset;$("admin-password-user").textContent=user?`Set a new password for ${user.username}.`:"Set a new password for this account.";$("admin-new-password").value="";$("admin-password-dialog").showModal();$("admin-new-password").focus();}
    else if(target.dataset.adminRemove||target.dataset.adminRestore){const enabled=Boolean(target.dataset.adminRestore);const id=target.dataset.adminRemove||target.dataset.adminRestore;const title=enabled?"Restore this account?":"Remove this account?";const message=enabled?"This account will be able to sign in again.":"Sign-in will be blocked, current logins revoked, and active lab VMs queued for cleanup. Learning records will be retained.";if(await confirmAction(title,message)){const result=await api("/admin/users/"+id,"PUT",{enabled});await renderAdmin();notify(result.message);}}
    else if(target.hasAttribute("data-admin-password-cancel"))$("admin-password-dialog").close();
  }catch(error){target.disabled=false;notify(error.message);}
});
$("login-form").addEventListener("submit",async e=>{e.preventDefault();const button=e.target.querySelector("button");button.disabled=true;$("login-error").textContent="";try{if(!$("terms-agree").checked)throw new Error("Review and agree to the user agreement before signing in");if(!state.termsVersion)throw new Error("The agreement could not be loaded; reload and try again");await api("/terms/accept","POST",{agree:true,version:state.termsVersion});const user=await api("/login","POST",{username:$("username").value,password:$("password").value});await enter(user);}catch(error){$("login-error").textContent=error.message;}finally{button.disabled=false;}});
$("logout").addEventListener("click",async()=>{try{if(state.page==="games"&&state.gameId){if(!await confirmGameLeave())return;}else await flushGameProgress();await api("/logout","POST",{});latestGameProgress=null;location.assign("/login");}catch(error){notify(error.message);}});
document.addEventListener("submit",async e=>{
  const form=e.target;
  if(!["user-form","password-form","admin-password-form","bug-report-form","academy-assessment-form","assessment-bank-form"].includes(form.id)&&!form.dataset.labSettings)return;
  e.preventDefault();const button=form.querySelector('button[type="submit"]')||form.querySelector("button");if(button)button.disabled=true;
  try{
    if(form.id==="bug-report-form"){const result=await api("/bug-reports","POST",{message:$("bug-report-message").value});form.reset();$("bug-report-username").value=state.user.username;notify(result.message);}
    else if(form.id==="academy-assessment-form"){
      const answers={...state.assessment.answers,...Object.fromEntries([...new FormData(form).entries()].map(([id,value])=>[id,Number(value)]))};
      const missing=state.assessment.questions.find(question=>!(question.id in answers));
      if(missing){state.assessment=await api(`/academy-assessments/attempts/${state.assessment.id}`,"PUT",{answers});state.assessmentIndex=state.assessment.questions.findIndex(question=>question.id===missing.id);renderAssessmentAttempt(state.assessment);$("assessment-question").querySelector("h2").focus();notify("Answer every question before submitting.");return;}
      if(!await confirmAction("Submit this assessment?","You cannot change answers after submission. Your score, area results and explanations will be saved in My Results."))return;
      state.assessment=await api(`/academy-assessments/attempts/${state.assessment.id}/submit`,"POST",{answers});state.assessmentIndex=null;renderAssessmentAttempt(state.assessment);
    }
    else if(form.id==="assessment-bank-form"){
      const file=$("assessment-bank-file").files[0];if(!file)throw new Error("Choose the Academy-wide assessment bank JSON file");
      if(file.size>2*1024*1024)throw new Error("Assessment bank files must be 2 MB or smaller");
      const bank=JSON.parse(await file.text());const result=await api("/admin/academy-assessments/bank","PUT",bank);
      state.assessment=null;notify(`Question bank loaded: ${result.counts.overall} readiness and ${result.counts.graduation} graduation questions.`);await renderAssessments();
    }
    else if(form.id==="user-form"){await api("/admin/users","POST",Object.fromEntries(new FormData(form)));await renderAdmin();notify("Local account created");}
    else if(form.id==="password-form"){await api("/password","POST",{current_password:$("current-password").value,new_password:$("new-password").value});form.reset();notify("Password updated");}
    else if(form.id==="admin-password-form"){const result=await api("/admin/users/"+form.dataset.userId+"/password","PUT",{new_password:$("admin-new-password").value});$("admin-password-dialog").close();form.reset();await renderAdmin();notify(result.message);}
    else if(form.dataset.labSettings){const data=new FormData(form);await api("/admin/labs/"+form.dataset.labSettings,"PUT",{template_id:Number(data.get("template_id")),secondary_template_id:data.has("secondary_template_id")?(Number(data.get("secondary_template_id"))||null):undefined,cores:Number(data.get("cores")),memory:Number(data.get("memory")),enabled:data.has("enabled")});await refresh();await renderAdmin();notify("Lab settings saved");}
  }catch(error){notify(error.message);}finally{if(button)button.disabled=false;}
});
setInterval(async()=>{if(!state.user)return;try{await refresh();if(state.current){const latest=await api("/sessions/"+state.current);if(JSON.stringify(latest)!==JSON.stringify(state.detail)){state.detail=latest;if(latest.state==="ended"){notify("Lab ended. Your results are saved.");await page("sessions");}else {renderWorkspace();const roles=latest.paired?["sender","listener"]:["sender"];await Promise.all(roles.map(role=>connectConsole(false,role)));}}}else if(["catalog","sessions"].includes(state.page))render();}catch(error){if(state.user)notify(error.message);}},3000);
setInterval(updateStartupProgress,1000);
window.addEventListener("popstate",()=>{if(state.user)page(routePage(),true).catch(error=>notify(error.message));});
(async()=>{try{const terms=await api("/terms/status");state.termsVersion=terms.version;$("terms-version").textContent=terms.version;try{await enter(await api("/me"));}catch{showLogin();}}catch{$("login-error").textContent="The agreement could not be loaded. Reload the page to try again.";showLogin();}})();
