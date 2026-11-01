'use strict';
// Exercise the shipped onboarding controller and automatic boot. These DOM
// stubs check state, validation and requests; they do not claim browser layout QA.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomUUID} = require('node:crypto');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const scripts = Array.from(html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi), m => m[1]);
const tick = () => new Promise(resolve => setImmediate(resolve));
const clone = value => JSON.parse(JSON.stringify(value));
const owner = {ownerName:'Alex Morgan',username:'Alex.Morgan',password:'A long family passphrase',confirm:'A long family passphrase'};
const home = {household:'  The Morgan home  ',timezone:'Europe/London',hour24:'12'};
const initialState = () => ({schema:1,members:[{id:'family',name:'Family',color:'sage'}],events:[],tasks:[],items:[],notes:[],meals:{},preferences:{household:'Existing home',timezone:'UTC',hour24:true,theme:'premium'}});

function harness(options={}) {
  const nodes = new Map(), documentListeners = new Map(), intervals = [], timers = new Map(), requests = [];
  const store = {authenticated:!!options.authenticated,initialized:!!options.authenticated,state:initialState()};
  let nextTimer = 1;
  function node(id) {
    if(!nodes.has(id)) nodes.set(id, {id,textContent:id==='app'?'Opening your home…':'',innerHTML:'',hidden:false,dataset:{},
      addEventListener(){},focus(){},close(){},showModal(){},classList:{toggle(){},remove(){},add(){}}});
    return nodes.get(id);
  }
  const origin = options.origin || 'http://127.0.0.1:8787';
  const address = new URL(origin + '/' + (options.preview?'?welcome=preview':''));
  const location = {protocol:address.protocol,hostname:address.hostname,pathname:address.pathname,origin:address.origin,search:address.search,hash:''};
  const context = {Date,Intl,Promise,URL,Blob,AbortController,crypto:{randomUUID},location,
    FormData:class {constructor(form){this.values=form.values||{};}get(key){return this.values[key]??null;}entries(){return Object.entries(this.values)[Symbol.iterator]();}},
    document:{activeElement:null,hidden:false,getElementById:node,querySelectorAll(){return [];},querySelector(){return node('kit-continue');},
      addEventListener(type,fn){const handlers=documentListeners.get(type)||[];handlers.push(fn);documentListeners.set(type,handlers);},
      documentElement:{dataset:{}},body:{classList:{toggle(){},remove(){},add(){}}}},
    history:{replaceState(_value,_title,url){const target=new URL(url,location.origin);location.pathname=target.pathname;location.search=target.search;location.hash=target.hash;}},
    localStorage:{getItem(){return null;},setItem(){throw new Error('Setup must not save owner credentials in browser storage.');}},
    setTimeout(fn,delay){const id=nextTimer++;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},
    setInterval(fn,delay){intervals.push({fn,delay});},addEventListener(){},
    fetch:async(route,config={})=>{
      const method=config.method||'GET';
      requests.push({route,method,body:config.body?JSON.parse(config.body):undefined,headers:{...config.headers}});
      let data;
      if(route==='/api/me') data={authenticated:store.authenticated,initialized:store.initialized,user:{id:'owner',name:'Alex Morgan',role:'admin'},csrf:'session-csrf'};
      else if(route==='/api/setup/local') data={setupKey:'local-device-setup-code-for-tests'};
      else if(route==='/api/setup'&&method==='POST') {
        if(options.setupGate) await options.setupGate;
        store.authenticated=true;store.initialized=true;
        data={user:{id:'owner',name:'Alex Morgan',role:'admin'},csrf:'new-session-csrf',recoveryCode:'HB-once-only-recovery-code'};
      }
      else if(route==='/api/state') {
        if(options.failState) throw new Error('Connection dropped after creating the owner');
        data={state:clone(store.state),revision:1};
      }
      else if(route==='/api/system'||route==='/api/product') {
        if(options.failStatus) throw new Error('Status is temporarily unavailable');
        data={version:'0.2.0-rc.1',networkUrls:['http://192.168.1.20:8787'],backup:{}};
      }
      else throw new Error('Unexpected onboarding request: '+method+' '+route);
      return {ok:true,status:200,json:async()=>data};
    }
  };
  context.window=context;vm.createContext(context);
  let exposed=false;
  for(const source of scripts) {
    let runnable=source;
    if(source.includes('function advanceOnboarding(')) {
      const expose=`globalThis.__onboardingTests={boot,sync,render,startOnboarding,advanceOnboarding,
        getWizard:()=>wizard,getKit:()=>securityKit,getState:()=>state};boot();})();`;
      runnable=source.replace(/boot\(\);\s*\}\)\(\);\s*$/,expose);
      assert.notEqual(runnable,source,'Expose the real controller while retaining automatic boot.');
      exposed=true;
    }
    vm.runInContext(runnable,context,{filename:'index.html:onboarding',timeout:1000});
  }
  assert(exposed,'The actual HTML must contain its onboarding controller.');
  const api=context.__onboardingTests;
  const submit=values=>api.advanceOnboarding({id:'onboarding-form',values:values||{}});
  return {api,root:node('app'),requests,intervals,store,context,submit,
    async dispatch(type,target){for(const handler of documentListeners.get(type)||[])await handler({target,preventDefault(){}});}};
}

async function throughOwner(h,values=owner) {
  await tick();await h.submit();await h.submit(home);await h.submit(values);
  assert.equal(h.api.getWizard().step,3);
}
async function throughStyle(h,values=owner) {
  await throughOwner(h,values);
  await h.submit({'person-name-0':'  Jamie  ','person-color-0':'blue'});
  assert.equal(h.api.getWizard().step,4);
}

test('automatic first boot welcomes the household and claims setup only on localhost',async()=>{
  const h=harness();await tick();
  assert.match(h.root.innerHTML,/Welcome to Homeboard/);
  assert.match(h.root.innerHTML,/Set up Homeboard/);
  assert.doesNotMatch(h.root.innerHTML,/name="password"/);
  assert.equal(h.api.getWizard().timezone,Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC');
  assert.equal(h.api.getWizard().localClaim,true);
  assert.deepEqual(h.requests.map(r=>r.route),['/api/me','/api/setup/local']);
  const remote=harness({origin:'http://homeboard.test:8787'});await tick();
  assert.equal(remote.api.getWizard().localClaim,false);
  assert.deepEqual(remote.requests.map(r=>r.route),['/api/me']);
});

test('home step requires a name and valid timezone without submitting setup',async()=>{
  const h=harness();await tick();await h.submit();
  for(const [values,message] of [[{...home,household:'   '},/Give your home a name/],[{...home,timezone:'Not/A_Timezone'},/valid time zone/]]) {
    await h.submit(values);assert.equal(h.api.getWizard().step,1);assert.match(h.root.innerHTML,message);
  }
  await h.submit(home);
  assert.equal(h.api.getWizard().step,2);
  assert.equal(h.api.getWizard().home,'The Morgan home');
  assert.equal(h.api.getWizard().hour24,false);
  assert.equal(h.requests.filter(r=>r.method==='POST').length,0);
});

test('owner step validates name, username, password length and confirmation before advancing',async()=>{
  const h=harness();await tick();await h.submit();await h.submit(home);
  for(const [values,message] of [
    [{...owner,ownerName:' '},/Enter your name/],
    [{...owner,username:'has spaces'},/3–40 letters/],
    [{...owner,password:'short',confirm:'short'},/at least 12 characters/],
    [{...owner,confirm:'Something different'},/passwords don’t match/]
  ]) {
    await h.submit(values);assert.equal(h.api.getWizard().step,2);assert.match(h.root.innerHTML,message);
  }
  await h.submit(owner);assert.equal(h.api.getWizard().step,3);
  assert.equal(h.api.getWizard().username,'alex.morgan');
  assert.equal(h.requests.filter(r=>r.method==='POST').length,0);
});

test('remote setup requires its first-run device code, while local setup keeps its automatic claim',async()=>{
  const h=harness({origin:'http://homeboard.test:8787'});await tick();await h.submit();await h.submit(home);
  assert.match(h.root.innerHTML,/name="setupKey"/);
  await h.submit(owner);assert.equal(h.api.getWizard().step,2);
  assert.match(h.root.innerHTML,/enter its device setup code/);
  await h.submit({...owner,setupKey:'  a supplied first-run device code  '});
  assert.equal(h.api.getWizard().step,3);
  assert.equal(h.api.getWizard().setupKey,'a supplied first-run device code');
});

test('final setup sends exactly the chosen household, owner and nonblank people',async()=>{
  const h=harness();await throughOwner(h);
  h.api.getWizard().people.push({name:'',color:'sage'});
  await h.submit({'person-name-0':'  Jamie  ','person-color-0':'blue','person-name-1':'   ','person-color-1':'sage'});
  await h.submit({theme:'warm'});
  const writes=h.requests.filter(r=>r.method==='POST');assert.equal(writes.length,1);
  assert.equal(writes[0].route,'/api/setup');
  assert.deepEqual(writes[0].body,{setupKey:'local-device-setup-code-for-tests',name:'Alex Morgan',username:'alex.morgan',password:owner.password,
    household:{name:'The Morgan home',timezone:'Europe/London',hour24:false,theme:'warm'},members:[{name:'Jamie',color:'blue'}]});
  assert.equal(h.api.getWizard(),null);
  assert.equal(h.api.getKit().saved,false);
  assert.match(h.root.innerHTML,/HB-once-only-recovery-code/);
  assert.match(h.root.innerHTML,/http:\/\/192\.168\.1\.20:8787/);
  assert.doesNotMatch(h.root.innerHTML,/A long family passphrase|local-device-setup-code-for-tests/);
});

test('a repeated final submit cannot create a second owner while setup is pending',async()=>{
  let release;const setupGate=new Promise(resolve=>{release=resolve;});
  const h=harness({setupGate});await throughStyle(h);
  const first=h.submit({theme:'smart'});await tick();
  assert.equal(h.api.getWizard().busy,true);
  assert.match(h.root.innerHTML,/Creating your home…/);
  await h.submit({theme:'smart'});release();await first;
  assert.equal(h.requests.filter(r=>r.route==='/api/setup').length,1);
});

test('setup preview hides the device code and completes without any POST or household changes',async()=>{
  const h=harness({authenticated:true,preview:true});await tick();
  const original=clone(h.store.state);
  assert.match(h.root.innerHTML,/Setup preview/);
  await h.submit();await h.submit(home);
  assert.doesNotMatch(h.root.innerHTML,/name="setupKey"|Device setup code/);
  await h.submit(owner);await h.submit({'person-name-0':'Jamie','person-color-0':'blue'});
  assert.match(h.root.innerHTML,/Finish preview/);
  await h.submit({theme:'warm'});
  assert.equal(h.api.getWizard(),null);
  assert.equal(h.api.getKit(),null);
  assert.equal(h.requests.filter(r=>r.method==='POST').length,0);
  assert.equal(h.requests.filter(r=>r.route==='/api/setup/local').length,0);
  assert.deepEqual(h.store.state,original);
  assert.equal(h.context.location.search,'');
  assert.match(h.root.innerHTML,/Existing home/);
});

test('once-only recovery kit survives state and status failures until saved and explicitly continued',async()=>{
  const h=harness({failState:true,failStatus:true});await throughStyle(h);await h.submit({theme:'premium'});
  assert.equal(h.api.getKit().code,'HB-once-only-recovery-code');
  assert.match(h.root.innerHTML,/Your home is ready/);
  assert.match(h.root.innerHTML,/data-product="kit-continue" disabled/);
  await h.submit({theme:'premium'});h.api.render();
  for(const timer of h.intervals.filter(t=>t.delay!==1000))await timer.fn();
  await tick();
  assert.match(h.root.innerHTML,/HB-once-only-recovery-code/);
  assert.equal(h.requests.filter(r=>r.route==='/api/setup').length,1);
  const target={dataset:{product:'kit-continue'},closest(selector){return selector==='[data-product]'?this:null;}};
  await h.dispatch('click',target);
  assert.equal(h.api.getKit().code,'HB-once-only-recovery-code','Unsaved kit cannot be dismissed.');
  await h.dispatch('change',{id:'kit-saved',checked:true});
  assert.equal(h.api.getKit().saved,true);
  await h.dispatch('click',target);
  assert.equal(h.api.getKit(),null);
  assert.equal(h.requests.filter(r=>r.route==='/api/setup').length,1);
});

test('background sync cannot replace an in-progress wizard or a recovery kit',async()=>{
  const h=harness();await tick();
  let requests=h.requests.length;await h.api.sync();assert.equal(h.requests.length,requests);
  await throughStyle(h);await h.submit({theme:'premium'});
  requests=h.requests.length;await h.api.sync();assert.equal(h.requests.length,requests);
  assert.match(h.root.innerHTML,/HB-once-only-recovery-code/);
});
