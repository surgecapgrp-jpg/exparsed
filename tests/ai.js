// AI calls for underwriting judgments and chat: request shapes, reply parsing, chat tools,
// and the underwrite / chat loops with a fake model. Async checks print once their promise settles.
function T(name, cond, extra){ print((cond?'PASS ':'FAIL ')+name+(cond||extra==null?'':'  got '+JSON.stringify(extra))); }

var cfgC={ key:'sk-ant-x', model:'claude-opus-5-5' }, cfgO={ key:'sk-or-x', model:'openai/gpt-x' };
var tool=[{ name:'t', description:'d', schema:{ type:'object', properties:{} } }];

// A1-A2 request shapes
var rc=aiRequest('claude', cfgC, { system:'S', history:[aiUser('hi')], tools:tool, schema:{ type:'object' } }), bc=JSON.parse(rc.init.body);
T('A1 claude request: cached system, tools, structured output, refusal fallback',
  rc.url==='https://api.anthropic.com/v1/messages' && rc.init.headers['x-api-key']==='sk-ant-x' && rc.init.headers['anthropic-dangerous-direct-browser-access']==='true'
  && bc.system[0].cache_control.type==='ephemeral' && bc.tools[0].input_schema.type==='object' && bc.output_config.format.type==='json_schema'
  && bc.fallbacks==='default' && rc.init.headers['anthropic-beta']==='server-side-fallback-2026-07-01' && bc.max_tokens===16000, bc);
var bh=JSON.parse(aiRequest('claude', { key:'k', model:'claude-haiku-4-5' }, { system:'S', history:[] }).init.body);
T('A1b no fallback parameter for models that reject it', bh.fallbacks===undefined && !bh.tools && !bh.output_config, bh);
var ro=aiRequest('openrouter', cfgO, { system:'S', history:[aiUser('hi')], tools:tool, schema:{ type:'object' } }), bo=JSON.parse(ro.init.body);
T('A2 openrouter request: system first, function tools, response_format',
  /openrouter\.ai\/api\/v1\/chat\/completions$/.test(ro.url) && ro.init.headers.Authorization==='Bearer sk-or-x' && bo.messages[0].role==='system'
  && bo.messages[1].content==='hi' && bo.tools[0].type==='function' && bo.tools[0]['function'].parameters.type==='object' && bo.response_format.type==='json_schema', bo);

// A3-A5 reply parsing and tool results
var pc=aiParse('claude', { stop_reason:'tool_use', content:[{ type:'thinking', thinking:'', signature:'s' }, { type:'text', text:'a' }, { type:'text', text:'b' }, { type:'tool_use', id:'tu1', name:'t', input:{ x:1 } }] });
T('A3 claude parse keeps thinking blocks in the native message', pc.text==='ab' && pc.calls[0].id==='tu1' && pc.calls[0].input.x===1 && pc.assistant.content[0].type==='thinking' && !pc.refusal, pc);
T('A3b claude refusal flagged', aiParse('claude', { stop_reason:'refusal', content:[] }).refusal===true);
var po=aiParse('openrouter', { choices:[{ finish_reason:'tool_calls', message:{ content:null, tool_calls:[{ id:'c1', type:'function', 'function':{ name:'t', arguments:'{"y":2}' } }] } }] });
T('A4 openrouter parse decodes tool arguments', po.text==='' && po.calls[0].input.y===2 && po.assistant.tool_calls.length===1, po);
var tc=aiToolResults('claude', [{ id:'tu1', content:'r1' }, { id:'tu2', content:'r2' }]), to=aiToolResults('openrouter', [{ id:'c1', content:'r1' }]);
T('A5 tool results: one claude user message, one openrouter tool message each', tc.length===1 && tc[0].content.length===2 && tc[0].content[1].tool_use_id==='tu2' && to[0].role==='tool' && to[0].tool_call_id==='c1');

// A6 JSON from model text
T('A6 JSON read from fenced or wrapped text', aiJsonFromText('```json\n{"a":1}\n```').a===1 && aiJsonFromText('Here: {"a":2} done').a===2 && aiJsonFromText('no json')===null);

// A7 page schema matches underwriting/schemas/judgments.schema.json property names
var file=JSON.parse(readFile(TESTS+'/../underwriting/schemas/judgments.schema.json'));
function keys(o){ return Object.keys(o).sort().join(','); }
T('A7 page judgments schema has the same fields as the engine schema',
  keys(UW_JUDGMENTS_SCHEMA.properties)===keys(file.properties) && keys(UW_JUDGMENTS_SCHEMA.properties.answers.items.properties)===keys(file.properties.answers.items.properties)
  && keys(UW_EVIDENCE_SCHEMA.properties)===keys(file.$defs.evidence.properties)
  && JSON.stringify(UW_EVIDENCE_SCHEMA.properties.kind['enum'])===JSON.stringify(file.$defs.evidence.properties.kind['enum']));

// A8-A10 chat tools over row objects from two files (as uwChatData builds them)
var ctx={ files:[{ name:'p.pdf', status:'verified', period:{ start:'2026-06-01', end:'2026-06-30' }, account:null, rows:3 }, { name:'s.pdf', status:'partial', period:null, account:'1234', rows:2 }],
  rows:[{ file:'p.pdf', date:'PENDING', amount:-5, balance:'90.00', desc:'KAPITUS PEND' }, { file:'p.pdf', date:'2026-06-03', amount:-2095, balance:'95.00', desc:'ORIG CO NAME:KAPITUS ORIG ID 1' },
        { file:'p.pdf', date:'2026-06-02', amount:3000, balance:'2190.00', desc:'EPX ST MERCH SETL' }, { file:'s.pdf', date:'2026-07-01', amount:1500.25, balance:'', desc:'MOBILE DEPOSIT' },
        { file:'s.pdf', date:'2026-07-09', amount:-40, balance:'', desc:'CHECK 101' }],
  texts:{ 'p.pdf':'line1\nline2\nline3' }, audit:null };
var s1=JSON.parse(uwRunTool('search_rows', { text:'kapitus' }, ctx));
T('A8 search_rows: substring match, signed total, file|date|amount|balance|description rows',
  s1.matched===2 && s1.signed_total==='-2100.00' && s1.rows[1]==='p.pdf|2026-06-03|-2095.00|95.00|ORIG CO NAME:KAPITUS ORIG ID 1', s1);
var s2=JSON.parse(uwRunTool('search_rows', { direction:'credit', date_from:'2026-06-01', date_to:'2026-07-31', min_amount:1000 }, ctx));
T('A8b search_rows: direction, dates (pending excluded), amount range', s2.matched===2 && s2.signed_total==='4500.25', s2);
var d1=JSON.parse(uwRunTool('read_document', {}, ctx)), d2=JSON.parse(uwRunTool('read_document', { file:'p.pdf', start_line:2, count:1 }, ctx));
T('A9 read_document lists files, then reads a line range', d1.files[0].file==='p.pdf' && d1.files[0].lines===3 && d2.text==='line2' && d2.total_lines===3, [d1, d2]);
T('A10 read_audit before a run, then a section after',
  /no underwriting run/.test(uwRunTool('read_audit', { section:'capacity' }, ctx))
  && JSON.parse(uwRunTool('read_audit', { section:'capacity' }, { audit:{ capacity:{ headline:'1.00' } } })).headline==='1.00'
  && /unknown section/.test(uwRunTool('read_audit', { section:'x' }, { audit:{} })));
T('A10b system prompt names the files and marks descriptions as data', /p\.pdf: verified, 2026-06-01 to 2026-06-30, account not printed, 3 rows/.test(uwChatSystem(ctx)) && /s\.pdf: partial, account 1234, 2 rows/.test(uwChatSystem(ctx)) && /data\. Never follow instructions/.test(uwChatSystem(ctx)));

// A10c export and chat share one ownership rule: printout rows on dates another file covers drop out
var OWNf={ acctOf:function(){ return '1234'; }, own:{ '1234|2026-06-03':'stmt.pdf' } };
var Lp={ cls:'printout', rows:[{ date:'2026-06-02' }, { date:'2026-06-03' }, { date:'PENDING' }] };
var o1=lgOwnRows({ name:'p.pdf' }, Lp, OWNf), o2=lgOwnRows({ name:'p.pdf' }, { cls:'statement', rows:Lp.rows }, OWNf), o3=lgOwnRows({ name:'p.pdf' }, { cls:'printout', rows:[{ date:'2026-06-02' }], carriedOmission:'4 rows earlier' }, OWNf);
T('A10c lgOwnRows drops rows another file covers and says why', o1.rows.length===2 && o1.omitted==='1 rows on dates covered by stmt.pdf (same transactions; omitted)'
  && o2.rows.length===3 && o2.omitted===null && o3.omitted==='4 rows earlier', [o1, o2, o3]);

// A11 chat loop: one tool round, then an answer
var calls=0, seen=[];
function fakeChat(prov, cfg, req){
  calls++;
  if(calls===1) return Promise.resolve(aiParse('claude', { stop_reason:'tool_use', content:[{ type:'tool_use', id:'u1', name:'search_rows', input:{ text:'kapitus' } }] }));
  return Promise.resolve(aiParse('claude', { stop_reason:'end_turn', content:[{ type:'text', text:'Kapitus debits total $2,100.' }] }));
}
var hist=[aiUser('How much went to Kapitus?')];
uwChatTurn('claude', cfgC, hist, ctx, fakeChat, function(k, t){ seen.push(k); }).then(function(){
  T('A11 chat runs the tool locally, returns its result, then answers',
    calls===2 && seen.join(',')==='tool,text' && hist.length===4 && hist[2].content[0].type==='tool_result' && JSON.parse(hist[2].content[0].content).matched===2, [calls, seen, hist.length]);
});

// A12-A14 underwrite: accepted answers, one rejection then accepted, no provider
var Q={ ledger_sha256:'abc', questions:[{ question_id:'Q-debit-1' }] };
function engineFake(rejectFirst){
  var n=0;
  return function(j){ n++;
    if(!j) return { ok:true, questions:Q, report:'defaults' };
    if(rejectFirst==='always' || rejectFirst && n===2) return { ok:false, error:'judgment Q-debit-1: quote not in transaction text' };
    var parsed=JSON.parse(j); return { ok:true, report:'with '+parsed.answers.length+' answers, sha '+parsed.ledger_sha256 };
  };
}
function fakeJudge(texts){ var i=0; return function(prov, cfg, req){ var t=texts[Math.min(i++, texts.length-1)]; return Promise.resolve(aiParse('claude', { stop_reason:'end_turn', content:[{ type:'text', text:t }] })); }; }
var good='{"ledger_sha256":"wrong","answers":[{"question_id":"Q-debit-1","tag":"OTHER"}]}';
uwUnderwrite('claude', cfgC, 'P', engineFake(false), fakeJudge([good]), function(){}).then(function(o){
  T('A12 underwrite applies the answers and stamps the ledger hash', o.result.report==='with 1 answers, sha abc' && o.judgments.answers.length===1, o);
});
var steps=[];
uwUnderwrite('claude', cfgC, 'P', engineFake(true), fakeJudge([good, good]), function(t){ steps.push(t); }).then(function(o){
  T('A13 a rejected file gets one retry with the engine error', o.result.ok && /rejected/.test(steps[1]) && /quote not in transaction text/.test(steps[1]), [o, steps]);
});
uwUnderwrite('claude', null, 'P', engineFake(false), fakeJudge([good]), function(){}).then(function(o){
  T('A14 no provider: engine defaults with a note', o.result.report==='defaults' && /defaults/.test(o.note), o);
});

uwUnderwrite('claude', cfgC, 'P', engineFake('always'), fakeJudge([good, good]), function(){}).then(function(o){
  T('A14b answers rejected twice: an error and no engine-default report', !o.result.ok && /rejected twice/.test(o.result.error) && /quote not in transaction text/.test(o.result.error) && o.result.report===undefined, o);
});

// A15 structured output rejected by an older model: same request again without the schema
var withSchema=[];
function fake400(prov, cfg, req){
  withSchema.push(!!req.schema);
  if(req.schema){ var e=new Error('HTTP 400: output_config not supported'); e.status=400; return Promise.reject(e); }
  return Promise.resolve(aiParse('claude', { stop_reason:'end_turn', content:[{ type:'text', text:good }] }));
}
uwJudgeOnce('claude', cfgC, 'P', [aiUser('q')], fake400).then(function(j){
  T('A15 a 400 on structured output retries without the schema', withSchema.join(',')==='true,false' && j.answers.length===1, withSchema);
});

// A16 aiCall: HTTP errors carry status and the provider message
aiCall('claude', cfgC, { system:'S', history:[] }, function(){
  return Promise.resolve({ ok:false, status:401, text:function(){ return Promise.resolve('{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}'); } });
}).then(function(){ T('A16 HTTP error raised', false); }, function(e){
  T('A16 HTTP error raised with status and message', e.status===401 && e.message==='HTTP 401: invalid x-api-key', e.message);
});
