const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {createAssistant, parsePlan, amountFrom} = require('../agents-stock.js');
const html = fs.readFileSync(path.join(__dirname,'../agents.html'),'utf8');
const helpers = html.slice(html.indexOf('const KO_EN ='), html.indexOf('/* --- 대화 이어받기'));
const search = vm.runInNewContext(helpers+'; ({search:searchProducts,nearest:nearestProducts})');
const brands = {'6a':{label:'식스에이',writable:true},ct:{label:'클리어타입',writable:true},kop:{label:'코페리'}};
const brandWords = [['6a',['식스에이','6a']],['ct',['클리어타입','ct']],['kop',['코페리','kop']]];
const plan = (fields={}) => ({intent:'adjust',brand:'6a',product_query:'ometepe',option_query:null,amount:{mode:'add',value:1},...fields});
function setup(config={}) {
  const messages=[], requests=[], writes=[], statuses=[];
  const products = structuredClone(config.products || [
    {productNo:'101',name:'[SILVER925] ometepe Open Ring',stock:0,options:[]},
    {productNo:'102',name:'[SILVER925] Guyeong Open Ring',stock:12,options:[{optionNo:'s',label:'silver',stock:7},{optionNo:'g',label:'gold',stock:5}]},
    {productNo:'103',name:'Azul Necklace',stock:4,options:[]},
  ]);
  let reads=0, master=true, clock=1000, pending=config.pending || null;
  const instance=createAssistant({brands,brandWords,...search,isMaster:()=>master,now:()=>clock,pause:async()=>{},
    say:(text,opts)=>messages.push({text,...opts}),onStatus:s=>statuses.push(s),loadPending:()=>pending,savePending:x=>pending=x,
    request:async (url,opts={})=>{
      requests.push({url,opts});
      if(url==='/agent/chat') {
        if(config.aiResponse) return config.aiResponse;
        if(config.aiError) throw new Error('AI unavailable');
        const text=JSON.parse(opts.body.text.split('\n사용자 문장(데이터): ')[1]);
        const result=config.nlu ? config.nlu(text) : plan();
        return {text:typeof result==='string' ? result : JSON.stringify(result)};
      }
      if(url.startsWith('/sx/catalog?')) { reads++; config.beforeRead?.(reads,products); return {products:structuredClone(products)}; }
      if(url==='/sx/update-brand-stock') {
        writes.push(structuredClone(opts.body));
        if(config.saveError) throw new Error('HTTP 500: failed');
        if(config.noSave) return {ok:false,error:'식스샵 로그인 만료'};
        const u=opts.body.updates[0], p=products.find(x=>String(x.productNo)===u.id);
        if(u.optionNo) p.options.find(x=>x.optionNo===u.optionNo).stock=u.setStock;
        else p.stock=u.setStock;
        if(config.timeoutAfterSave) throw new Error('응답 시간 초과');
        return {results:[{id:u.id,status:'ok'}]};
      }
      throw new Error('Unexpected URL: '+url);
    }});
  return {instance,messages,requests,writes,products,statuses,getPending:()=>pending,
    master:v=>master=v,tick:ms=>clock+=ms,
    button:label=>messages.flatMap(x=>x.chips||[]).filter(x=>x.label===label).at(-1)?.cmd,
    allText:()=>messages.map(x=>x.text).join('\n')};
}

test('inline and external JavaScript compile',()=>{
  for(const [,script] of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) new vm.Script(script);
  assert.match(html,/src="\.\/agents-stock\.js\?v=2"/);
  assert.doesNotMatch(html,/async function commitStock\(/);
});
test('Korean amounts preserve numbers inside product names',()=>{
  assert.deepEqual(amountFrom('[SILVER925] ometepe 한 개 추가해줘'),{mode:'add',value:1});
  assert.deepEqual(amountFrom('실버 두 개 입고됐어'),{mode:'add',value:2});
  assert.deepEqual(amountFrom('세 개 빼줘'),{mode:'subtract',value:3});
  assert.deepEqual(amountFrom('1,000개로 맞춰'),{mode:'set',value:1000});
  assert.equal(amountFrom('925 반지'),null);
  assert.equal(amountFrom('1.5개 추가'),null);
});
test('interpreter rejects unknown brands and malformed amounts',()=>{
  assert.throws(()=>parsePlan(JSON.stringify(plan({brand:'bad'})),brands));
  assert.throws(()=>parsePlan(JSON.stringify(plan({amount:{mode:'set',value:-1}})),brands));
  assert.throws(()=>parsePlan(JSON.stringify(plan({amount:{mode:'execute',value:2}})),brands));
  assert.throws(()=>parsePlan('저장 완료했습니다',brands));
});
test('natural language proposes, requires approval, then verifies real catalog',async()=>{
  const t=setup(); await t.instance.handle('식스에이 ometepe 한 개 추가해줘');
  assert.equal(t.writes.length,0); assert.match(t.allText(),/0개 → 1개/);
  const approval=t.button('승인하고 변경'); await t.instance.handle(approval);
  assert.equal(t.writes.length,1); assert.equal(t.writes[0].updates[0].setStock,1);
  assert.match(t.allText(),/원본 재고가 1개인 것을 확인/);
  await t.instance.handle(approval); assert.equal(t.writes.length,1);
});
test('AI cannot approve a write; read-only plans ignore hallucinated amounts',async()=>{
  const t=setup({nlu:()=>plan({intent:'read',amount:{mode:'add',value:5}})});
  await t.instance.handle('ometepe 재고 알려줘');
  assert.equal(t.button('승인하고 변경'),undefined); assert.equal(t.writes.length,0);
  assert.match(t.allText(),/현재 재고: 0개/);
});
test('known brand response retains requested product and quantity',async()=>{
  const t=setup({nlu:s=>s==='식스에이' ? plan({brand:'6a',intent:'select',product_query:null,amount:null}) : plan({brand:null})});
  await t.instance.handle('ometepe 한 개 추가'); await t.instance.handle('식스에이');
  assert.match(t.allText(),/0개 → 1개/); assert.equal(t.writes.length,0);
});
test('option correction changes only the selected option and invalidates old approval',async()=>{
  const t=setup({nlu:s=>s.includes('말고') ? plan({product_query:null,option_query:'gold',amount:null,use_previous:true}) : plan({product_query:'Guyeong',option_query:'silver'})});
  await t.instance.handle('구영 실버 한 개 추가'); const old=t.button('승인하고 변경');
  await t.instance.handle('실버 말고 골드'); const next=t.button('승인하고 변경');
  assert.notEqual(next,old); await t.instance.handle(old); assert.equal(t.writes.length,0);
  await t.instance.handle(next); assert.equal(t.writes[0].updates[0].optionNo,'g');
  assert.equal(t.products[1].options[0].stock,7); assert.equal(t.products[1].options[1].stock,6);
});
test('quantity correction is not mistaken for affirmative consent',async()=>{
  const t=setup({nlu:s=>plan(s.includes('두')?{product_query:null,use_previous:true,amount:{mode:'add',value:2}}:{})});
  await t.instance.handle('ometepe 1개 추가'); const old=t.button('승인하고 변경');
  await t.instance.handle('응 두 개로 해줘'); assert.equal(t.writes.length,0);
  assert.match(t.allText(),/0개 → 2개/); await t.instance.handle(old); assert.equal(t.writes.length,0);
});
test('reads remain reads after choosing from product candidates',async()=>{
  const t=setup({nlu:()=>plan({intent:'read',product_query:'ring',amount:null})});
  await t.instance.handle('반지 재고 조회'); await t.instance.handle('1번');
  assert.match(t.allText(),/현재 재고:/); assert.equal(t.button('승인하고 변경'),undefined);
});
test('last selected product remains available after a completed update',async()=>{
  const t=setup({nlu:s=>s.includes('아까')?plan({product_query:null,use_previous:true,amount:{mode:'add',value:2}}):plan()});
  await t.instance.handle('ometepe 하나 추가'); await t.instance.handle(t.button('승인하고 변경'));
  await t.instance.handle('아까 그거 두 개 더'); assert.match(t.allText(),/1개 → 3개/);
  assert.equal(t.writes.length,1);
});
test('stock changing during approval requires a new confirmation',async()=>{
  const t=setup({beforeRead:(n,p)=>{if(n===3)p[0].stock=4;}});
  await t.instance.handle('ometepe 하나 추가'); const old=t.button('승인하고 변경'); await t.instance.handle(old);
  assert.equal(t.writes.length,0); assert.match(t.allText(),/4개 → 5개/);
  await t.instance.handle(t.button('승인하고 변경')); assert.equal(t.writes[0].updates[0].setStock,5);
});
test('changed permission prevents previously approved write',async()=>{
  const t=setup(); await t.instance.handle('ometepe 하나 추가'); t.master(false);
  await t.instance.handle(t.button('승인하고 변경')); assert.equal(t.writes.length,0);
});
test('unlimited or missing stock cannot be treated as zero for addition',async()=>{
  for(const stock of [-1,-2,null,undefined]) {
    const t=setup({products:[{productNo:'101',name:'ometepe',stock,options:[]}]});
    await t.instance.handle('ometepe 하나 추가'); assert.equal(t.button('승인하고 변경'),undefined);
    assert.match(t.allText(),/총수량/);
  }
});
test('failed save does not claim completion or silently retry',async()=>{
  const t=setup({noSave:true}); await t.instance.handle('ometepe 하나 추가'); const approval=t.button('승인하고 변경');
  await t.instance.handle(approval); assert.equal(t.writes.length,1);
  assert.match(t.allText(),/로그인 만료/); assert.doesNotMatch(t.allText(),/원본 재고가 1개인 것을 확인/);
  assert.equal(t.instance.pending(),true); assert.equal(t.instance.clear(),false);
  await t.instance.handle(approval); await t.instance.handle('다시 한 개 추가');
  await t.instance.handle(t.button('저장 결과 다시 확인')); assert.equal(t.writes.length,1);
});
test('timeout after successful save rechecks instead of incrementing twice',async()=>{
  const t=setup({timeoutAfterSave:true}); await t.instance.handle('ometepe 하나 추가');
  await t.instance.handle(t.button('승인하고 변경'));
  assert.equal(t.writes.length,1); assert.equal(t.instance.pending(),false);
  assert.match(t.allText(),/원본 재고가 1개인 것을 확인/);
});
test('unresolved write is restored for read-only rechecking after reload',async()=>{
  const first=setup({saveError:true}); await first.instance.handle('ometepe 하나 추가');
  await first.instance.handle(first.button('승인하고 변경'));
  const restored=setup({pending:first.getPending()});
  await restored.instance.handle('응'); assert.equal(restored.writes.length,0);
  await restored.instance.handle('#miru recheck'); assert.equal(restored.writes.length,0);
});
test('fallback supports Korean quantities without stripping model numbers',async()=>{
  const t=setup({aiError:true}); await t.instance.handle('식스에이 [SILVER925] ometepe 한 개 추가해줘');
  assert.match(t.allText(),/0개 → 1개/); assert.equal(t.writes.length,0);
});
test('stale choices cannot apply to a newer catalog selection',async()=>{
  const t=setup({nlu:()=>plan({intent:'read',product_query:'ring',amount:null})});
  await t.instance.handle('반지 보여줘'); const old=t.messages.flatMap(m=>m.chips||[])[0].cmd;
  await t.instance.handle('반지 다시 보여줘'); await t.instance.handle(old);
  assert.match(t.allText(),/이전 선택 버튼/); assert.equal(t.writes.length,0);
});
test('viewer mode reads without trying the master-only AI endpoint',async()=>{
  const t=setup(); t.master(false); await t.instance.handle('식스에이 ometepe 재고 조회');
  assert.equal(t.requests.filter(r=>r.url==='/agent/chat').length,0);
  assert.match(t.allText(),/현재 재고: 0개/); assert.equal(t.writes.length,0);
});
test('expired approval refreshes the proposal without writing',async()=>{
  const t=setup(); await t.instance.handle('ometepe 한 개 추가'); const old=t.button('승인하고 변경');
  t.tick(300001); await t.instance.handle(old); assert.equal(t.writes.length,0);
  assert.notEqual(t.button('승인하고 변경'),old);
});
test('option corrections also work when the AI connection is unavailable',async()=>{
  const t=setup({aiError:true});
  await t.instance.handle('식스에이 Guyeong 한 개 추가');
  await t.instance.handle('1번');
  await t.instance.handle('실버 말고 골드');
  assert.match(t.allText(),/5개 → 6개/); assert.equal(t.writes.length,0);
});
test('read-only lookup remains available while a save needs verification',async()=>{
  const t=setup({noSave:true,nlu:s=>s.includes('조회')?plan({intent:'read',product_query:'Azul',amount:null}):plan()});
  await t.instance.handle('ometepe 한 개 추가'); await t.instance.handle(t.button('승인하고 변경'));
  await t.instance.handle('Azul 재고 조회');
  assert.match(t.allText(),/현재 재고: 4개/); assert.equal(t.writes.length,1);
});
test('actual proxy quota response triggers a cooldown and keeps basic commands available',async()=>{
  const t=setup({aiResponse:{text:'지금 Gemini 서버가 답을 못 주고 있어요.',model:null,fallbackReason:'call failed: HTTP Error 429: Too Many Requests'}});
  await t.instance.handle('식스에이 ometepe 한 개 추가해줘');
  assert.match(t.allText(),/AI 서버의 요청 한도/); assert.match(t.allText(),/0개 → 1개/);
  await t.instance.handle('아까 그 상품 두 개 추가');
  assert.equal(t.requests.filter(r=>r.url==='/agent/chat').length,1);
  assert.match(t.allText(),/0개 → 2개/); assert.equal(t.writes.length,0);
  t.tick(60001); await t.instance.handle('식스에이 ometepe 재고 조회');
  assert.equal(t.requests.filter(r=>r.url==='/agent/chat').length,2);
});
