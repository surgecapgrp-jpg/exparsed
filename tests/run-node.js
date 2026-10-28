// Node equivalent of run.sh (for machines without macOS JavaScriptCore). Usage: node tests/run-node.js [page]
const fs=require('fs'), vm=require('vm'), path=require('path'), cp=require('child_process');
const dir=__dirname, page=process.argv[2]||path.join(dir,'..','exparsed.html');
cp.execFileSync('python3',[path.join(dir,'extract.py'),page,path.join(dir,'.build')]);
const out=[]; const ctx={ TESTS:dir, print:(...a)=>out.push(a.join(' ')), readFile:f=>fs.readFileSync(f,'utf8'), console };
if(process.env.UPDATE_GOLDEN) ctx.writeFile=(f,t)=>fs.writeFileSync(f,t);
vm.createContext(ctx); let crash=0;
try{ new vm.Script(fs.readFileSync(path.join(dir,'.build','all.js'),'utf8')); }catch(e){ out.push('FAIL whole-page syntax: '+e.message); }
vm.runInContext(fs.readFileSync(path.join(dir,'.build','lg.js'),'utf8'),ctx,{filename:'lg.js'});
for(const f of ['fixtures.js','desktop.js','edge.js','formats.js','macocr.js','analytics.js','ocr.js','contract.js','parsers.js']){
  const p=path.join(dir,f); if(!fs.existsSync(p)) continue;
  try{ vm.runInContext(fs.readFileSync(p,'utf8'),ctx,{filename:f}); }catch(e){ crash++; out.push('Exception: '+f+': '+(e.stack||e).toString().split('\n').slice(0,3).join(' | ')); }
}
const pass=out.filter(l=>/^PASS/.test(l)).length, fail=out.filter(l=>/^FAIL/.test(l)).length;
out.filter(l=>!/^PASS/.test(l) || process.env.V).forEach(l=>console.log(l));
console.log(`\n${pass} passed, ${fail} failed${crash?`, ${crash} test file(s) crashed`:''}`);
process.exit(fail||crash?1:0);
