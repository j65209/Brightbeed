/* Shared transport and freshness rules. No automatic retries of writes. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BrightbeedReliability=api;})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function createNetwork({fetch:rawFetch,tunnelUrl,now=Date.now,timeoutMs=20000}){
    let cached=null,loadedAt=0,pending=null;
    async function bounded(url,options={}){
      const {timeoutMs:limit=timeoutMs,...init}=options;
      const ctrl=new AbortController();
      const abort=()=>ctrl.abort(init.signal?.reason);
      if(init.signal?.aborted)abort();else init.signal?.addEventListener('abort',abort,{once:true});
      const timer=setTimeout(()=>ctrl.abort(new Error('요청 제한 시간 초과')),limit);
      try{
        const response=await rawFetch(url,{...init,signal:ctrl.signal});
        // Keep the deadline active until the response body has finished arriving.
        const bytes=await response.arrayBuffer();
        return new Response(response.status===204||response.status===205||response.status===304?null:bytes,{status:response.status,statusText:response.statusText,headers:response.headers});
      }catch(error){
        if(ctrl.signal.aborted)throw new Error('서버 응답 시간이 초과됐습니다. 변경 요청이었다면 재조회로 결과를 확인하세요.');
        throw error;
      }finally{clearTimeout(timer);init.signal?.removeEventListener('abort',abort);}
    }
    async function base(force=false){
      if(!force&&cached&&now()-loadedAt<60000)return cached;
      if(pending)return pending;
      pending=(async()=>{
        const r=await bounded(tunnelUrl+'?cb='+now(),{cache:'no-store',timeoutMs:10000});
        if(!r.ok)throw new Error('서버 주소 조회 실패 (HTTP '+r.status+')');
        const d=await r.json();
        if(!d||typeof d.url!=='string'||!/^https:\/\//.test(d.url))throw new Error('서버 주소 응답 형식 오류');
        cached=d.url.replace(/\/$/,'');loadedAt=now();return cached;
      })();
      try{return await pending;}finally{pending=null;}
    }
    async function request(url,options={}){
      const method=(options.method||'GET').toUpperCase();
      const retryable=method==='GET'||method==='HEAD';
      const previous=cached;
      const isProxy=previous&&String(url).startsWith(previous+'/');
      let response,error;
      try{response=await bounded(url,options);}catch(e){error=e;}
      if(isProxy&&retryable&&!options.signal?.aborted&&(error||[502,503,504].includes(response?.status))){
        const updated=await base(true);
        // Retry a read once; mutation calls are never replayed here.
        return bounded(updated+String(url).slice(previous.length),options);
      }
      if(error)throw error;
      return response;
    }
    return {base,fetch:request};
  }
  function health(data,now=Date.now){
    if(!data||!Array.isArray(data.checks)||data.checks.length===0)return {ok:false,error:data?.error||'수집 상태를 확인할 항목이 없습니다.',checks:[]};
    const limits={'물류':30,'매출':60,'벤더':30,'마케팅':60};
    const checks=data.checks.map(c=>{
      const age=Number.isFinite(c.updated_at)?(now()/1000-c.updated_at)/60:Number.isFinite(c.age_hours)?c.age_hours*60:null;
      const limit=limits[c.category]??(Number.isFinite(c.stale_after_hours)?c.stale_after_hours*60:60);
      const known=age!==null&&age>=-2;
      const ok=c.ok===true&&known&&age<=limit;
      return {...c,ok,status:!known?'missing':ok?'fresh':c.status==='missing'?'missing':'stale',age_hours:known?Math.max(0,age)/60:null,stale_after_hours:limit/60};
    });
    return {...data,ok:checks.every(c=>c.ok),checks};
  }
  async function runSync(tasks){
    const settled=await Promise.allSettled(tasks.map(async t=>({name:t.name,result:await t.run()})));
    const results=settled.map((s,i)=>s.status==='fulfilled'?{name:tasks[i].name,...(s.value.result||{ok:false,error:'완료 여부 미확인'})}:{name:tasks[i].name,ok:false,error:s.reason?.message||'연결 실패'});
    return {ok:results.length>0&&results.every(r=>r.ok===true&&!r.skipped),results};
  }
  function agentDesks(desks,agents){
    const byId=new Map(agents.map(a=>[a.id,a]));
    return desks.map(d=>{
      if(d.manual||!d.agentIds?.length)return 'idle';
      const states=d.agentIds.map(id=>byId.get(id)?.status);
      if(states.some(s=>!s))return 'unknown';
      if(states.includes('stale'))return 'stale';
      if(states.includes('warn'))return 'warn';
      return states.every(s=>s==='running')?'running':'unknown';
    });
  }
  function canonical(value){
    if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
    if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
    return JSON.stringify(value);
  }
  function createVersions(){
    const versions=new Map();
    return {remember:(key,value)=>versions.set(key,canonical(value)),get:key=>versions.get(key),matches:(expected,value)=>expected!==undefined&&expected===canonical(value)};
  }
  return {createNetwork,health,runSync,createVersions,agentDesks};
});
