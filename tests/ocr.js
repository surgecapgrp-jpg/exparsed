// What a file needs (fileOcrNeed) and the Mac OCR reader (macOcrRead) run against a fake server port.
// Loaded after formats.js, whose derivedKey stub ('1') lets a test hand a file a ready ledger.
function t(name, cond, info){ print((cond?'PASS ':'FAIL ')+name+(info?'  '+info:'')); }
function withLedger(f, status){ f._ledgerKey='1:'+(f.ocrMarkdown?1:0); f._ledger={ status:status }; return f; }
var PG=function(){ return { hasText:false, lines:[] }; };

// ---- O1: the decision table, one record per state
(function(){
  var done={ status:'done', type:'pdf', pages:[PG(),PG()], scanned:0 };
  function rec(o){ var f={}; for(var k in done) f[k]=done[k]; for(var k2 in o) f[k2]=o[k2]; return f; }
  var cases=[
    ['busy file is reading',               rec({ status:'busy' }),                               'reading', null, 'busy'],
    ['read error',                         rec({ error:'bad' }),                                 'read-error', null, 'err'],
    ['OCR running',                        rec({ ocrStatus:'ocring' }),                          'ocring', null, 'busy'],
    ['OCR queued',                         rec({ ocrStatus:'queued' }),                          'queued', null, 'busy'],
    ['OCR done',                           rec({ ocrMarkdown:'x', scanned:2 }),                  'ocr-done', null, 'ok'],
    ['OCR failed offers a retry',          rec({ ocrStatus:'error: 500' }),                      'ocr-failed', 'Retry OCR', 'err'],
    ['damaged PDF',                        rec({ pdfOpenFailed:'bad xref', pages:[] }),          'damaged', 'Run OCR', 'err'],
    ['image file',                         rec({ type:'image', pages:[] }),                      'image', 'Run OCR', 'err'],
    ['every page scanned',                 rec({ scanned:2 }),                                   'scanned', 'Run OCR', 'err'],
    ['image page but the text reconciles', withLedger(rec({ scanned:1 }), 'verified'),           'image-pages-verified', null, 'ok'],
    ['image page and text does not',       withLedger(rec({ scanned:1 }), 'breaks'),             'scanned-pages', 'OCR full doc', 'warn'],
    ['whole text layer broken',            rec({ suspectText:true }),                            'broken-text', 'Run OCR', 'err'],
    ['broken pages, text reconciles',      withLedger(rec({ suspectPages:[2] }), 'verified'),    'readable', null, 'ok'],
    ['broken pages, text does not',        withLedger(rec({ suspectPages:[2] }), 'untestable'),  'broken-pages', 'OCR full doc', 'warn'],
    ['clean text layer',                   withLedger(rec({}), 'untestable'),                    'readable', null, 'ok'],
    ['text the ledger cannot read',        withLedger(rec({}), 'needs-ocr'),                     'unreadable-text', 'Run OCR', 'err']
  ];
  cases.forEach(function(c){
    var n=fileOcrNeed(c[1]);
    t('O1 '+c[0], n.state===c[2] && n.button===c[3] && n.dot===c[4], JSON.stringify([n.state, n.button, n.dot]));
  });
  t('O1 auto-OCR for a fully scanned file', fileOcrNeed(rec({ scanned:2 })).autoOcr===true);
  t('O1 auto-OCR for a broken text layer', fileOcrNeed(rec({ suspectText:true })).autoOcr===true);
  t('O1 auto-OCR when the ledger says needs-ocr', fileOcrNeed(withLedger(rec({}), 'needs-ocr')).autoOcr===true);
  t('O1 no auto-OCR after a failed OCR', fileOcrNeed(rec({ scanned:2, ocrStatus:'error: 500' })).autoOcr===false);
  t('O1 auto-OCR for a photo', fileOcrNeed(rec({ type:'image', pages:[] })).autoOcr===true);
  t('O1 auto-OCR for a damaged PDF', fileOcrNeed(rec({ pdfOpenFailed:'bad xref', pages:[] })).autoOcr===true);
  t('O1 no auto-OCR while reading', fileOcrNeed(rec({ status:'busy', scanned:2 })).autoOcr===false);
  t('O1 no auto-OCR for one scanned page', fileOcrNeed(rec({ scanned:1 })).autoOcr===false);
  t('O1 no auto-OCR for a removed file', fileOcrNeed(rec({ scanned:2, removed:true })).autoOcr===false);
  t('O1 broken banner until OCR starts', fileOcrNeed(rec({ suspectText:true })).brokenBanner===true && fileOcrNeed(rec({ suspectText:true, ocrStatus:'queued' })).brokenBanner===false);
  // the broken-text level shared with the ledger (lgDocKind refuses 'whole' and 'most')
  t('O1 broken-text level', [brokenTextLevel({ suspectText:true }, 4), brokenTextLevel({ suspectPages:[1,2] }, 4), brokenTextLevel({ suspectPages:[1] }, 4), brokenTextLevel({}, 4)].join()==='whole,most,some,none');
})();

// ---- O2: macOcrRead through a fake port
var MD={ hf:false, hyph:false, head:false, page:false };
var WORDS='Statement of account for the period shown below with deposits and withdrawals listed by date and the balance carried forward from the previous statement period for your business checking account';
function vision(text){ return { w:1224, h:1584, pxPerPt:2, heightPt:792, lines:[{ t:text, x:112, y:200, w:900, h:20 }] }; }
function textPage(text){ var p=visionToPage(vision(text+' '+text+' '+text), 2, 792); p.hasText=true; return p; }
function res(ok, body){ return { ok:ok, status:ok?200:500, json:function(){ return Promise.resolve(body); } }; }
// pages: a map of page index -> vision JSON, or 'fail'; serverPages: the page count the server reports
function fakePort(pages, serverPages){
  var log=[];
  return { log:log,
    upload:function(blob){ log.push('upload'); return Promise.resolve(res(true, { id:'u1', pages:serverPages })); },
    page:function(id, i){ log.push('page '+i); var p=pages[i];
      if(p==='down') return Promise.reject(new TypeError('Failed to fetch'));
      if(p==='busy-once'){ pages[i]='ok-now'; return Promise.resolve({ ok:false, status:503, json:function(){ return Promise.resolve({}); } }); }
      if(p==='ok-now') return Promise.resolve(res(true, vision('AFTER RETRY')));
      if(p==='busy') return Promise.resolve({ ok:false, status:503, json:function(){ return Promise.resolve({}); } });
      return Promise.resolve(p==='fail' ? { ok:false, status:404, json:function(){ return Promise.resolve({}); } } : res(true, p)); },
    image:function(f){ log.push('image'); return Promise.resolve(res(true, vision('PHOTO LINE ONE'))); },
    release:function(id){ log.push('release '+id); },
    fail:function(r, pageNo, total){ log.push('fail '+pageNo+'/'+total); return Promise.resolve({ ok:false, message:'HTTP '+r.status }); }
  };
}
var waits=[];
function hooks(cancelAfter, port){ return { md:MD, now:function(){ return 0; }, progress:function(){}, wait:function(ms){ waits.push(ms); return Promise.resolve(); },
  cancelled:function(){ return cancelAfter!=null && port.log.filter(function(l){ return /^page/.test(l); }).length>=cancelAfter; } }; }
function run(name, f, port, cancelAfter, check){
  macOcrRead(f, port, hooks(cancelAfter, port)).then(function(r){ var c=check(r, port.log); t('O2 '+name, c===true, JSON.stringify({ log:port.log, ok:r.ok, cancelled:r.cancelled, text:r.text })); },
    function(e){ t('O2 '+name, false, 'threw '+e); });
}
var scanned={ hasText:false, lines:[] };
run('kept text page stays, image pages are asked for in order',
  { name:'a.pdf', type:'pdf', pages:[textPage(WORDS), scanned, scanned] },
  fakePort({ 1:vision('PAGE TWO TEXT'), 2:vision('PAGE THREE TEXT') }, 3), null,
  function(r, log){ return r.ok && r.recognized===2 && log.join()==='upload,page 1,page 2,release u1' && r.text.indexOf('Statement of account')<r.text.indexOf('PAGE TWO')&&r.text.indexOf('PAGE TWO')<r.text.indexOf('PAGE THREE'); });
run('every page readable: nothing is sent',
  { name:'b.pdf', type:'pdf', pages:[textPage(WORDS)] },
  fakePort({}, 1), null,
  function(r, log){ return r.ok && r.recognized===0 && log.length===0; });
run('scanner PDF: its own text layer is read again',
  { name:'c.pdf', type:'pdf', prov:{ producer:'Canon iR-ADV' }, pages:[textPage(WORDS)] },
  fakePort({ 0:vision('RESCANNED') }, 1), null,
  function(r, log){ return r.ok && log.join()==='upload,page 0,release u1' && /RESCANNED/.test(r.text); });
run('a failed page reports its number and still releases the upload',
  { name:'d.pdf', type:'pdf', pages:[scanned, scanned] },
  fakePort({ 0:vision('ONE'), 1:'fail' }, 2), null,
  function(r, log){ return r.ok===false && log.join()==='upload,page 0,page 1,fail 2/2,release u1'; });
run('cancel stops the run and still releases the upload',
  { name:'e.pdf', type:'pdf', pages:[scanned, scanned, scanned] },
  fakePort({ 0:vision('ONE'), 1:vision('TWO'), 2:vision('THREE') }, 3), 1,
  function(r, log){ return r.cancelled===true && log.join()==='upload,page 0,release u1'; });
run('PDF that pdf.js could not open uses the server page count',
  { name:'f.pdf', type:'pdf', pages:[] },
  fakePort({ 0:vision('ONE'), 1:vision('TWO') }, 2), null,
  function(r, log){ return r.ok && r.recognized===2 && log.join()==='upload,page 0,page 1,release u1'; });
run('photo goes through the image call',
  { name:'g.jpg', type:'image', pages:[] },
  fakePort({}, 0), null,
  function(r, log){ return r.ok && log.join()==='image' && /PHOTO LINE ONE/.test(r.text); });
run('a 503 on a page is retried after 2 s',
  { name:'h.pdf', type:'pdf', pages:[scanned] },
  fakePort({ 0:'busy-once' }, 1), null,
  function(r, log){ return r.ok && /AFTER RETRY/.test(r.text) && log.join()==='upload,page 0,page 0,release u1' && waits.indexOf(2000)>=0; });
run('a page still busy after 3 tries is reported',
  { name:'i.pdf', type:'pdf', pages:[scanned] },
  fakePort({ 0:'busy' }, 1), null,
  function(r, log){ return r.ok===false && log.join()==='upload,page 0,page 0,page 0,fail 1/1,release u1'; });
(function(){
  var port=fakePort({ 0:vision('ONE'), 1:'down' }, 2);
  macOcrRead({ name:'j.pdf', type:'pdf', pages:[scanned, scanned] }, port, hooks(null, port)).then(function(){ t('O2 network error mid-read rejects', false); },
    function(e){ t('O2 network error mid-read rejects and still releases the upload', /Failed to fetch/.test(e.message) && port.log.join()==='upload,page 0,page 1,release u1', port.log.join()); });
})();

// ---- O3: cloudOcrRead (Claude, OpenRouter) through a fake port
function cloudPort(responses, text, reason){
  var log=[], n=0;
  return { log:log, label:'OCR/Fake',
    check:function(f){ return f.badModel ? { ok:false, message:'bad model' } : null; },
    encode:function(f, isImg){ log.push(isImg?'encode image':'encode pdf'); return Promise.resolve('B64'); },
    send:function(){ var st=responses[Math.min(n, responses.length-1)]; n++; log.push('send '+st); return Promise.resolve({ ok:st===200, status:st }); },
    read:function(){ log.push('read'); return Promise.resolve({ text:text, reason:reason, usage:{ out:1 }, truncated:reason==='max_tokens' }); },
    fail:function(r){ log.push('fail '+r.status); return Promise.resolve({ ok:false, message:'HTTP '+r.status }); },
    emptyHelp:function(why){ return 'empty because '+why; } };
}
function cloud(name, f, port, check, cancel){
  var h={ cancelled:function(){ return !!cancel && port.log.length>=cancel; }, wait:function(){ return Promise.resolve(); }, now:function(){ return 0; } };
  cloudOcrRead(f, port, h).then(function(r){ t('O3 '+name, check(r, port.log)===true, JSON.stringify({ log:port.log, r:r })); }, function(e){ t('O3 '+name, false, 'threw '+e); });
}
cloud('PDF read in one request, fences stripped', { name:'a.pdf', type:'pdf', size:1000 }, cloudPort([200], '```markdown\n# Statement\n```', 'end_turn'),
  function(r, log){ return r.ok && r.text==='# Statement' && log.join()==='encode pdf,send 200,read' && r.truncated===false; });
cloud('429 then 200 retries once', { name:'b.pdf', type:'pdf', size:1000 }, cloudPort([429, 200], 'text', 'end_turn'),
  function(r, log){ return r.ok && log.join()==='encode pdf,send 429,send 200,read'; });
cloud('401 fails fast', { name:'c.pdf', type:'pdf', size:1000 }, cloudPort([401], 'text', 'end_turn'),
  function(r, log){ return r.ok===false && log.join()==='encode pdf,send 401,fail 401'; });
cloud('empty output reported with its reason', { name:'d.pdf', type:'pdf', size:1000 }, cloudPort([200], '  ', 'max_tokens'),
  function(r){ return r.ok===false && r.message==='empty output (max_tokens)' && r.fullDiagnostic==='empty because max_tokens'; });
cloud('max_tokens marks the text truncated', { name:'e.pdf', type:'pdf', size:1000 }, cloudPort([200], 'part', 'max_tokens'),
  function(r){ return r.ok && r.truncated===true; });
cloud('PDF over 25 MB refused before encoding', { name:'f.pdf', type:'pdf', size:30*1048576 }, cloudPort([200], 'x', 'end_turn'),
  function(r, log){ return r.ok===false && /too large .*30\.0 MB/.test(r.message) && log.length===0; });
cloud('bad model refused before encoding', { name:'g.pdf', type:'pdf', size:1000, badModel:true }, cloudPort([200], 'x', 'end_turn'),
  function(r, log){ return r.ok===false && r.message==='bad model' && log.length===0; });
cloud('photo encoded as an image', { name:'h.jpg', type:'image', size:30*1048576 }, cloudPort([200], 'photo text', 'end_turn'),
  function(r, log){ return r.ok && log[0]==='encode image'; });
cloud('cancel during the request', { name:'i.pdf', type:'pdf', size:1000 }, cloudPort([200], 'x', 'end_turn'),
  function(r, log){ return r.cancelled===true && log.join()==='encode pdf,send 200'; }, 2);
