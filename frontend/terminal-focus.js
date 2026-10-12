"use strict";
// The console is served on this origin. Restore its keyboard input only when
// the learner clicks the remote display, leaving menus and text fields alone.
window.academyTerminalFocus=(()=>{
  const frames=new WeakSet(),documents=new WeakSet();
  function bind(frame){
    try{
      const doc=frame.contentDocument;
      if(!doc||documents.has(doc))return;
      documents.add(doc);
      doc.addEventListener("pointerdown",event=>{
        if(!event.target.closest?.(".client-main"))return;
        frame.contentWindow.focus();
        // Guacamole's mouse handler prevents the browser's default focus.
        // Its InputSink requires deferred focus after those handlers finish.
        frame.contentWindow.setTimeout(()=>{
          if(!frame.isConnected||frame.contentDocument!==doc)return;
          const sink=doc.querySelector("body > textarea");
          if(sink)sink.focus({preventScroll:true});
        },0);
      },true);
    }catch{/* A terminal navigation may briefly replace its document. */}
  }
  return {attach(frame){
    if(!frame)return;
    if(!frames.has(frame)){
      frames.add(frame);
      frame.addEventListener("load",()=>bind(frame));
    }
    bind(frame);
  }};
})();
