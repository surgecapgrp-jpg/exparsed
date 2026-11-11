/* Batch harness hook. tests/harness/run.py injects this at the end of the page's main closure,
   so it calls the page's own readFileContent, recFromContent and lgBuild (the same path a dropped
   file takes, including the per-account split). Runs only when the page URL has ?harness=1.
   One result per ledger: { file, status, rows, breaks, note }. */
(function(){
  var q=new URLSearchParams(location.search);
  if(!q.has('harness')) return;
  var shard=+q.get('shard')||0, of=+q.get('of')||1, LIMIT=90000;
  function post(url, body){ return fetch(url, { method:'POST', body:JSON.stringify(body) }); }
  function timeout(p){ return Promise.race([p, new Promise(function(_, no){ setTimeout(function(){ no(new Error('timeout after '+LIMIT/1000+'s')); }, LIMIT); })]); }
  function ledger(name, rec){
    var L=lgBuild(rec), checks=L.checks||[];
    var failed=checks.filter(function(c){ return c.result==='break'; });
    return { file:name, status:L.status, rows:(L.rows||[]).length, breaks:failed.length,
             failed:failed.map(function(c){ return (c.check+': '+(c.detail||'')).slice(0,160); }),
             note:L.note||L.error||rec.error||null };
  }
  // A re-imported Ledger JSON export: one record per file it holds, as expandChildren builds them.
  function imported(key, k){
    var r=makeRec(k.name, (k.markdown||'').length, null);
    r.status='done'; r.type='import'; r.markdown=k.markdown||''; r.ledgerMarkdown=k.ledgerMarkdown||null; r.parsedLedger=k.parsedLedger||null;
    return ledger(key+' · '+k.name, r);
  }
  async function one(key){
    var base=key.split('/').pop(), dir=key.slice(0, key.length-base.length);
    try{
      var blob=await (await fetch('/file/'+encodeURIComponent(key))).blob();
      var file=new File([blob], base), c;
      try{ c=await timeout(readFileContent(file)); }
      catch(e){ if(!(e && e.content)) throw e; c=e.content; c.error=(e.name==='PasswordException')?'password-protected PDF':String(e.message||e); }
      if(!c.children) return [ledger(key, recFromContent(base, file.size, c))];
      return c.children.map(function(k){
        return k.content ? ledger(dir+k.name, recFromContent(k.name, file.size, k.content)) : imported(key, k); });
    }catch(e){ return [{ file:key, status:'error', rows:0, breaks:0, note:String(e && e.message || e) }]; }
  }
  window.addEventListener('load', async function(){
    var keys=await (await fetch('/list?shard='+shard+'&of='+of)).json();
    for(var i=0;i<keys.length;i++) await post('/result', await one(keys[i]));
    await post('/done?shard='+shard, {});
  });
})();
