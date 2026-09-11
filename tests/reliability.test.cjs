'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const reliability=require('../reliability.js');
const app=fs.readFileSync(__dirname+'/../index.html','utf8'),agents=fs.readFileSync(__dirname+'/../agents.html','utf8');
const part=(source,start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a+start.length);assert(a>=0&&b>a,start);return source.slice(a,b);};
const context=(source,vars={})=>{const c=vm.createContext({Date,JSON,Map,Set,Promise,console,...vars});vm.runInContext(source,c);return c;};
const json=(data,status=200)=>Response.json(data,{status});
test('both application pages contain valid JavaScript',()=>{
 for(const [name,source] of [['index',app],['agents',agents]])for(const m of source.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi))if(!/src=|application\//.test(m[1]))new vm.Script(m[2],{filename:name});
});
test('empty health and unknown source time are not healthy',()=>{
 assert.equal(reliability.health({ok:true,checks:[]}).ok,false);
 assert.equal(reliability.health({checks:[{category:'매출',ok:true}]}).ok,false);
});
test('freshness checks the original timestamp with tighter collection limits',()=>{
 const now=()=>1800000000000;
 const checks=[{category:'물류',ok:true,updated_at:now()/1000-1900},{category:'매출',ok:true,updated_at:now()/1000-300}];
 assert.deepEqual(reliability.health({ok:true,checks},now).checks.map(c=>c.ok),[false,true]);
});
test('sync waits for all results; rejected, missing and skipped results fail completion',async()=>{
 let release;const wait=new Promise(r=>release=r);let done=false;
 const run=reliability.runSync([{name:'delayed',run:()=>wait},{name:'failed',run:async()=>{throw Error('offline')}}]).then(r=>(done=true,r));
 await Promise.resolve();assert.equal(done,false);release({ok:true});const r=await run;assert.equal(r.ok,false);assert.equal(r.results[1].error,'offline');
 for(const result of [undefined,{ok:true,skipped:true},{ok:false}])assert.equal((await reliability.runSync([{name:'x',run:async()=>result}])).ok,false);
 assert.equal((await reliability.runSync([{name:'x',run:async()=>({ok:true})}])).ok,true);
});
test('failed proxy reads refresh tunnel and retry once at new address',async()=>{
 const calls=[];let base=0;
 const n=reliability.createNetwork({tunnelUrl:'https://test.invalid/tunnel',fetch:async(url)=>{calls.push(url);if(url.includes('/tunnel'))return json({url:++base===1?'https://old.invalid':'https://new.invalid'});if(url.startsWith('https://old'))throw Error('offline');return json({ok:true});}});
 const b=await n.base();assert.equal((await n.fetch(b+'/health')).status,200);assert(calls.at(-1).startsWith('https://new.invalid'));assert.equal(calls.length,4);
});
test('failed writes never retry or replay delta changes',async()=>{
 let calls=0;const n=reliability.createNetwork({tunnelUrl:'https://test.invalid/tunnel',fetch:async(url)=>{if(url.includes('/tunnel'))return json({url:'https://proxy.invalid'});calls++;throw Error('lost response');}});
 const base=await n.base();await assert.rejects(n.fetch(base+'/stock',{method:'POST'}));assert.equal(calls,1);
});
test('deadline covers slow response bodies, not only response headers',async()=>{
 const n=reliability.createNetwork({timeoutMs:15,tunnelUrl:'https://test.invalid/tunnel',fetch:async(_url,{signal})=>({arrayBuffer:()=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted'))))})});
 await assert.rejects(n.fetch('https://test.invalid/data'),/초과/);
});
test('tunnel cache expires and concurrent refreshes coalesce',async()=>{
 let now=1,calls=0;const n=reliability.createNetwork({now:()=>now,tunnelUrl:'https://test.invalid/tunnel',fetch:async()=>{calls++;return json({url:'https://proxy.invalid'});}});
 await Promise.all([n.base(),n.base()]);assert.equal(calls,1);await n.base();assert.equal(calls,1);now+=61000;await n.base();assert.equal(calls,2);
});
function putContext(remote,status=200){
 const versions=reliability.createVersions(),writes=[];
 const c=context(part(app,'  async function ghPut(','  async function ghDelete('),{_remoteVersions:versions,PO_BRANCH:'main',decodeGhJson:s=>JSON.parse(Buffer.from(s,'base64').toString()),ghGetSha:async()=>({sha:'current',data:remote}),ghFetch:async(url,opts)=>{writes.push(JSON.parse(opts.body));return {ok:status===200,status};}});
 return {c,versions,writes};
}
test('JSON write detects an edit made before the SHA fetch, sends no PUT',async()=>{
 const {c,versions,writes}=putContext({entries:['mine','other']});versions.remember('file.json',{entries:['mine']});
 assert.equal((await c.ghPut('file.json',Buffer.from('{"entries":["changed"]}').toString('base64'),'test')).ok,false);assert.equal(writes.length,0);
});
test('JSON conflict during write is not retried with a newer SHA',async()=>{
 const {c,versions,writes}=putContext({entries:[]},409);versions.remember('file.json',{entries:[]});
 assert.equal((await c.ghPut('file.json','e30=','test')).ok,false);assert.equal(writes.length,1);
});
test('unknown JSON baseline blocks writing, known missing file allows creation',async()=>{
 const {c,versions,writes}=putContext(null);assert.equal((await c.ghPut('file.json','e30=','test')).ok,false);versions.remember('file.json',null);assert.equal((await c.ghPut('file.json','e30=','test')).ok,true);assert.equal(writes.length,1);assert(versions.matches(versions.get('file.json'),{}));
});
test('agent missing, stale transport and manual workers have truthful states',()=>{
 const c=context(part(agents,'function deriveCharStatus(','function nextRunTime('),{statusMap:{a:{status:'running'}},statusFetchedAt:Date.now()});
 const now=new Date();assert.equal(c.deriveCharStatus({agentIds:['missing']},now),'unknown');assert.equal(c.deriveCharStatus({agentIds:['a']},now),'running');assert.equal(c.deriveCharStatus({agentIds:['a'],manual:true},now),'idle');c.statusFetchedAt=now.getTime()-60000;assert.equal(c.deriveCharStatus({agentIds:['a']},now),'unknown');
});
test('integrated sync never flashes completion when logistics fails',async()=>{
 const statuses=[];const el={set textContent(v){statuses.push(v)},title:''};const vars={BrightbeedReliability:reliability,document:{getElementById:()=>el},renderKDOrders:async()=>({ok:false,error:'offline'})};
 for(const key of ['syncSalesPptFromRemote','syncSalesArchiveFromRemote','syncNoticeFromRemote','syncLeaveFromRemote','syncCsFromRemote','syncMdEventsFromRemote'])vars[key]=async()=>({ok:true});
 const c=context(part(app,'  let _syncInFlight=null;','  /* === 자동 폴링'),vars);
 assert.equal((await c.syncFromRemote()).ok,false);assert(!statuses.some(s=>s.includes('동기화 완료')));assert(statuses.some(s=>s.includes('실패')));
});
test('logistics fetch failure returns a failed result while retaining existing rows',async()=>{
 const e={children:[{}],style:{},classList:{add(){},remove(){},toggle(){}},querySelector:()=>null};
 const c=context(part(app,'  async function renderKDOrders(','  function attachKDHistoryChips('),{document:{getElementById:()=>e},fetchKDOrders:async()=>{throw Error('offline')}});
 assert.equal((await c.renderKDOrders()).ok,false);assert.notEqual(e.style.display,'none');
});

test('home counts desks while missing jobs and manual staff never count as running',()=>{
 const desks=[{agentIds:['a','b']},{manual:true,agentIds:[]},{agentIds:['c']}];
 assert.deepEqual(reliability.agentDesks(desks,[{id:'a',status:'running'},{id:'c',status:'warn'}]),['unknown','idle','warn']);
 assert.deepEqual(reliability.agentDesks(desks,[{id:'a',status:'running'},{id:'b',status:'running'},{id:'c',status:'stale'}]),['running','idle','stale']);
});
