const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {test}=require('node:test');

function harness(){
  const deferred=[],listeners=new Map();
  const sink={focus(options){this.calls++;this.options=options;},calls:0};
  const doc={addEventListener(type,fn){listeners.set(type,[...(listeners.get(type)||[]),fn]);},querySelector(selector){assert.equal(selector,'body > textarea');return sink;}};
  const win={calls:0,focus(){this.calls++;},setTimeout(fn){deferred.push(fn);}};
  const frame={isConnected:true,contentDocument:doc,contentWindow:win,loads:[],addEventListener(type,fn){assert.equal(type,'load');this.loads.push(fn);}};
  const context={window:{},WeakSet};
  vm.runInNewContext(fs.readFileSync('frontend/terminal-focus.js','utf8'),context);
  const attach=context.window.academyTerminalFocus.attach;
  function click(display=true){for(const fn of listeners.get('pointerdown')||[])fn({target:{closest(){return display?{}:null;}}});}
  function flush(){while(deferred.length)deferred.shift()();}
  return {attach,frame,doc,win,sink,listeners,click,flush};
}

test('one display click restores keyboard input after each focus loss',()=>{
  const h=harness();h.attach(h.frame);
  for(let i=1;i<=5;i++){
    h.click();assert.equal(h.win.calls,i);
    assert.equal(h.sink.calls,i-1,'focus must wait for Guacamole mouse handlers');
    h.flush();assert.equal(h.sink.calls,i);assert.equal(h.sink.options.preventScroll,true);
  }
});
test('workspace updates do not duplicate listeners or steal menu input',()=>{
  const h=harness();h.attach(h.frame);h.attach(h.frame);h.frame.loads[0]();
  assert.equal(h.frame.loads.length,1);assert.equal(h.listeners.get('pointerdown').length,1);
  h.click(false);h.flush();assert.equal(h.sink.calls,0);assert.equal(h.win.calls,0);
});
test('a deferred click cannot focus a replaced or removed terminal',()=>{
  const h=harness();h.attach(h.frame);h.click();h.frame.isConnected=false;h.flush();assert.equal(h.sink.calls,0);
  h.frame.isConnected=true;h.click();h.frame.contentDocument={};h.flush();assert.equal(h.sink.calls,0);
});
