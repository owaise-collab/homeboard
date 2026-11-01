'use strict';
// Execute the shipped scripts with automatic boot intact. These checks cover
// actual startup paths rather than instrumenting the boot call away.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const scripts = Array.from(html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi), m => m[1]);
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(mode) {
  const nodes = new Map(), timers = new Map(), listeners = new Map();
  let next = 1;
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {id, textContent: id === 'app' ? 'Opening your home…' : '',
      innerHTML:'', hidden:false, dataset:{}, addEventListener(){},
      classList:{toggle(){},remove(){},add(){}}});
    return nodes.get(id);
  }
  const state = {schema:1, members:[{id:'family',name:'Family',color:'sage'}], events:[],
    tasks:[],items:[],notes:[],meals:{},preferences:{household:'Our home',timezone:'UTC',hour24:true,theme:'premium'}};
  const context = {Date,Intl,Promise,URL,Blob,AbortController,
    location:{protocol:'http:',pathname:'/display',hash:'',origin:'http://home.test',reload(){}},
    document:{getElementById:node,addEventListener(){},querySelectorAll(){return [];},
      documentElement:{dataset:{}},body:{classList:{toggle(){},remove(){},add(){}}}},
    setTimeout(fn,delay){const id=next++;timers.set(id,{fn,delay});return id;},
    clearTimeout(id){timers.delete(id);},setInterval(){},
    addEventListener(type,fn){listeners.set(type,fn);},
    fetch:async route=>{
      if(mode==='stalled')return new Promise(()=>{});
      if(mode==='network-error')throw new Error('Server is unreachable');
      if(mode==='malformed')return {ok:true,json:async()=>{throw new SyntaxError('Truncated JSON');}};
      const data=route==='/api/me'?{initialized:mode!=='first-run',authenticated:mode==='authenticated',
        user:{id:'tv',name:'TV',role:'display'},csrf:'test'}:{state,revision:1};
      return {ok:true,json:async()=>data};
    }
  };
  context.window=context;vm.createContext(context);
  for(const source of scripts)vm.runInContext(source,context,{timeout:1000});
  return {root:node('app'),timers,listeners};
}
test('first-run automatic boot replaces the loading text with account setup',async()=>{
  const h=harness('first-run');await tick();
  assert.match(h.root.innerHTML,/Set up Homeboard/);
});
test('initialized automatic boot shows the sign-in form',async()=>{
  const h=harness('login');await tick();assert.match(h.root.innerHTML,/Sign in/);
});
test('authenticated display automatic boot renders the clock and today view',async()=>{
  const h=harness('authenticated');await tick();
  assert.match(h.root.innerHTML,/Today, together/);assert.match(h.root.innerHTML,/data-clock/);
});
test('network and malformed-response failures show a retry screen',async()=>{
  for(const mode of ['network-error','malformed']){
    const h=harness(mode);await tick();assert.match(h.root.innerHTML,/Try again/);
    assert.doesNotMatch(h.root.innerHTML,/Opening your home/);
  }
});
test('a stalled startup request times out instead of loading indefinitely',async()=>{
  const h=harness('stalled');
  const timer=Array.from(h.timers.values()).find(t=>t.delay===8000);
  assert(timer);timer.fn();await tick();assert.match(h.root.innerHTML,/Connection timed out/);
});
test('the early startup watchdog provides a retry even when application scripts fail',async()=>{
  const h=harness('stalled');h.listeners.get('error')();
  assert.match(h.root.innerHTML,/startup-retry/);
  assert.doesNotMatch(h.root.innerHTML,/Opening your home/);
});
