var $optRedact={checked:false}, $optCompactDesc={checked:false};
function derivedKey(f){ return '1'; } function fileMarkdownFinal(f){ return f.md||''; } function redactStructuredPII(t){ return { text:t, hits:{} }; }
function t(name, cond, info){ print((cond?'PASS ':'FAIL ')+name+(info?'  '+info:'')); }
// ---- CSV: preamble lines above the header, signed amount + running balance (Chase-style CSV)
var c1=parseCsvText('Account Name:,Business Checking\nAccount Number:,XXXXXX1234\n\nDetails,Posting Date,Description,Amount,Type,Balance,Check or Slip #\nDEBIT,01/07/2026,"ACH DEBIT ACME FUNDING",-1500.00,ACH_DEBIT,1975.00,\nDEBIT,01/06/2026,"POS PURCHASE STARBUCKS",-25.00,DEBIT_CARD,3475.00,\nCREDIT,01/05/2026,"DEPOSIT",2500.00,DEPOSIT,3500.00,\n', ',');
var C1=lgFromTableRows(c1,'csv-transactions'); C1&&lgFinalize(C1); t('CSV with preamble + balance', C1 && C1.status==='verified' && C1.rows.length===3, C1&&(C1.status+' '+C1.rows.length+' rows'));
// ---- CSV: separate Debit / Credit columns, "$" and blanks, oldest first
var c2=parseCsvText('Date,Description,Debit,Credit,Balance\n1/5/26,Deposit,,"$2,500.00","$3,500.00"\n1/6/26,POS Starbucks,$25.00,,"$3,475.00"\n', ',');
var C2=lgFromTableRows(c2,'csv-transactions'); C2&&lgFinalize(C2); t('CSV debit/credit columns', C2 && C2.status==='verified' && C2.rows.filter(function(r){ return r.signed<0; }).length===1, C2&&(C2.status+' '+C2.rows.map(function(r){ return r.signed; }).join(',')));
// ---- CSV: no header row at all (Wells Fargo download)
var c3=parseCsvText('"01/05/2026","2500.00","*","","DEPOSIT"\n"01/06/2026","-25.00","*","","PURCHASE AUTHORIZED ON 01/05 STARBUCKS"\n"01/07/2026","-1500.00","*","","ACME FUNDING PAYMENT"\n', ',');
var C3=lgFromTableRows(c3,'csv-transactions'); t('headerless CSV read by content', C3 && C3.rows.length===3 && C3.rows.some(function(r){ return /STARBUCKS/.test(r.desc); }), C3&&(C3.rows.length+' rows, '+C3.coverageFlags.join('; ')));
// ---- account numbers
var A=[['Account Number: 000000123456789','6789'],['Member Number 0000123456','3456'],['Checking Account 1234567890','7890'],['Your account ending in 4321','4321'],['Primary Account XXXXXX5555','5555'],['Acct # 9876-5432','5432'],['TRUIST SIMPLE BUSINESS CHECKING 1340008762936 10,036.03 page 1','2936'],['Account Summary 01/01/2026 - 01/31/2026',null],['Account Balance 1,234.56',null],['Customer Service 1-800-555-1234',null]];
A.forEach(function(a){ var got=lgFindAccount(a[0]); got=got?got.slice(-4):null; t('account: '+a[0], got===a[1], 'got '+got); });
t('no account -> own group', lgAcct4({ fileName:'a.pdf' })!==lgAcct4({ fileName:'b.pdf' }));
// ---- OCR page numbers
function pages(md){ return lgParseOcrTables(md).rows.map(function(r){ return r.page; }).join(','); }
var rowP=function(d){ return '| '+d+' | Deposit | 100.00 |\n'; }, hdr='## DEPOSITS\n\n| Date | Description | Amount |\n|---|---|---|\n';
t('OCR pages from --- separators', pages(hdr+rowP('01/05')+'\n---\n\n'+hdr+rowP('01/12')+'\n---\n\n'+hdr+rowP('01/20'))==='1,2,3', pages(hdr+rowP('01/05')+'\n---\n\n'+hdr+rowP('01/12')+'\n---\n\n'+hdr+rowP('01/20')));
var foot=hdr+rowP('01/05')+'\nPage 1 of 2\n\n---\n\n'+hdr+rowP('01/12')+'\nPage 2 of 2\n';
t('OCR footer markers + separators', pages(foot)==='1,2', pages(foot));
var headM='Page 1 of 2\n\n'+hdr+rowP('01/05')+'\nPage 2 of 2\n\n'+hdr+rowP('01/12');
t('OCR header markers, no separators', pages(headM)==='1,2', pages(headM));
var footM=hdr+rowP('01/05')+rowP('01/06')+'\nPage 1 of 2\n\n'+hdr+rowP('01/12')+'\nPage 2 of 2\n';
t('OCR footer markers, no separators', pages(footM)==='1,1,2', pages(footM));
// ---- broken text
var good='Statement Period 01/01/2026 to 01/31/2026 Beginning Balance 1,000.00 Deposits 100.00 Ending Balance 1,100.00';
t('legible statement passes', legibilityScore(good).score===1);
t('private-use glyph codes flagged', legibilityScore(good.replace(/[a-z]/g,'')).score===0);
var cipher=[]; for(var i=0;i<30;i++) cipher.push('01/0'+(i%9+1)+' Ghsrvlw Wudqvihu Vwduexfnv Txdo 1'+i+'.00'); 
t('letters garbled, figures intact, flagged', legibilityScore(cipher.join(' ')).reason==='letters-garbled', legibilityScore(cipher.join(' ')).reason);
var nod=[]; for(var j=0;j<40;j++) nod.push('the account balance statement deposit payment for your business');
t('words but no figures flagged', legibilityScore(nod.join(' ')).reason==='no-figures', legibilityScore(nod.join(' ')).reason);
t('merchant-code statement not flagged', legibilityScore(cipher.join(' ').replace(/Ghsrvlw/g,'Card Purchase')).score===1);
// ---- markdown keeps table rows on their own lines with aligned columns
function opt(){ return { hf:false, hyph:true, head:true, page:false }; }
var pg=m1.map(function(p){ return { lines:p.lines.map(function(l,i){ return { text:l.text, y:700-i*12, size:9, items:l.items }; }) }; });
var md=buildMarkdown(pg, opt());
t('markdown keeps table rows', /```[\s\S]*01\/05\/2026[^\n]*100\.00[^\n]*1,100\.00\n01\/06\/2026/.test(md));

// ---- re-reading that markdown (All markdown export dropped back in) still rebuilds the ledger
var R=lgFinalize(lgParseOcrTables(md,'statement-text')); t('ledger rebuilds from exported markdown', R.status==='verified' && R.rows.length===3, R.status+' '+R.rows.length+' rows');
// ---- statement periods
[['Statement Period: May 04 2026-Jun 03 2026','2026-05-04','2026-06-03'],['January 1, 2026 through January 31, 2026','2026-01-01','2026-01-31'],
 ['January 1 - January 31, 2026','2026-01-01','2026-01-31'],['01/01/26 thru 01/31/26','2026-01-01','2026-01-31']].forEach(function(p){
  var got=lgFindPeriod(p[0]); t('period: '+p[0], got && got.start===p[1] && got.end===p[2], JSON.stringify(got)); });
// ---- icon-font glyphs on a browser-printed banking page are not broken text (TD Bank)
var rowsIco=[]; for(var k=0;k<20;k++) rowsIco.push('9/'+(k+1)+'/2026 SERVICE CHARGE -$3.00 ');
t('icon glyphs between rows not flagged', legibilityScore('Accounts Available Balance $1,136.28  Card Pay a Bill '+rowsIco.join(' ')).score===1);
t('unmapped letters inside words still flagged', legibilityScore(rowsIco.join(' ').replace(/[A-Z]/g,'')).score===0);
// ---- Spanish statements (Chase prints them on request)
t('account: Número De Cuenta', (lgFindAccount('P O Box 44959 Número De Cuenta: 000000687062565')||'').slice(-4)==='2565', lgFindAccount('P O Box 44959 Número De Cuenta: 000000687062565'));
var sp=lgFindPeriod('Agosto 01, 2026 a Agosto 31, 2026'); t('period: Agosto 01, 2026 a Agosto 31, 2026', sp && sp.start==='2026-08-01' && sp.end==='2026-08-31', JSON.stringify(sp));
t('Spanish headings', ['DEPÓSITOS Y ADICIONES','CHEQUES PAGADOS','RETIROS ELECTRÓNICOS','CARGOS','SALDO FINAL DIARIO'].map(function(h){ var x=lgSectionOf(h); return x&&x.key; }).join(',')==='dep,chk,elec,fee,daily');
t('Spanish summary labels', ['Saldo inicial','Depósitos y Adiciones','Retiros de cajeros automáticos y','Retiros Electrónicos','Cargos','Saldo final'].map(lgSummaryKey).join(',')==='beg,dep,atm,elec,fee,end', ['Saldo inicial','Depósitos y Adiciones','Retiros de cajeros automáticos y','Retiros Electrónicos','Cargos','Saldo final'].map(lgSummaryKey).join(','));
// ---- CSV: rows the bank marks "Pending:" are pending, not posted (Pinnacle online download)
var c4=parseCsvText('"Date","Ref/Check","Description","Amount","Balance","Memo","Category"\n10/08/2026,,"Pending: 10/08/2026 - Memo Credit STRIPE TRANSFER ACH Entry Memo Posted Today",3500,3575.35,"",""\n10/08/2026,,"Pending: 10/08/2026 - Memo Debit SRG CAP ACH Entry Memo Posted Today",-25,75.35,"",""\n10/07/2026,,"Daily Ledger Bal",,100.35,"",""\n10/07/2026,,"SRG CAP 51636945 12",-25,100.35,"",""\n10/07/2026,,"OLB Transfer from *960 to *997 Transfer",-2246.75,125.35,"",""\n10/06/2026,1076,"Check",-100,2372.10,"",""\n', ',');
var C4=lgFromTableRows(c4,'csv-transactions'); C4&&lgFinalize(C4);
t('CSV pending rows kept out of the posted rows', C4 && C4.status==='verified' && C4.rows.filter(function(r){ return r.date==='PENDING' && r.section==='pending'; }).length===2 && C4.period.end==='2026-10-07', C4&&(C4.status+' '+C4.rows.map(function(r){ return r.date+':'+r.section; }).join(',')+' '+JSON.stringify(C4.period)));
// ---- DecisionLogic XML report: the checking account with the most transactions is the ledger
// (JavaScriptCore has no DOMParser: a small reader gives the nodes lgXKids / lgXAll / lgXText use)
function xmlDoc(src){
  function N(type, name){ this.nodeType=type; this.localName=name; this.nodeName=name; this.childNodes=[]; this.text=''; }
  N.prototype.getElementsByTagNameNS=function(ns, name){ var out=[]; (function walk(n){ n.childNodes.forEach(function(c){ if(c.nodeType===1){ if(c.localName===name) out.push(c); walk(c); } }); })(this); return out; };
  Object.defineProperty(N.prototype, 'textContent', { get:function(){ return this.nodeType===3?this.text:this.childNodes.map(function(c){ return c.textContent; }).join(''); } });
  var doc=new N(9,'#document'), stack=[doc], re=/<(\/?)([\w:.-]+)[^>]*?(\/?)>|([^<]+)/g, m;
  src=src.replace(/<\?[\s\S]*?\?>/g,'');
  while((m=re.exec(src))){ var top=stack[stack.length-1];
    if(m[4]!=null){ var tx=new N(3,'#text'); tx.text=m[4].replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&'); top.childNodes.push(tx); }
    else if(m[1]) stack.pop();
    else { var el=new N(1, m[2].replace(/^.*:/,'')); top.childNodes.push(el); if(!m[3]) stack.push(el); } }
  return doc;
}
function dlTx(d, amt, bal, desc, st){ return '<TransactionSummary><TransactionDate>'+d+'T00:00:00</TransactionDate><Amount>'+amt+'</Amount><Description>'+desc+'</Description><RunningBalance>'+bal+'</RunningBalance><Status>'+(st||'Posted')+'</Status></TransactionSummary>'; }
function dlAcct(type, no, cur, cr, db, txs){ return '<ReportDetail7><InstitutionName>Test Bank</InstitutionName><AccountNumberFound>xxxx'+no+'</AccountNumberFound><AccountType>'+type+'</AccountType><CurrentBalance>'+cur+'</CurrentBalance><TotalCredits>'+cr+'</TotalCredits><TotalDebits>'+db+'</TotalDebits><ActivityStartDate>2026-09-01T00:00:00</ActivityStartDate><ActivityEndDate>2026-09-04T00:00:00</ActivityEndDate><TransactionSummaries>'+txs.join('')+'</TransactionSummaries></ReportDetail7>'; }
var dlx='<?xml version="1.0" encoding="utf-8"?><ArrayOfReportDetail7 xmlns="http://www.decisionlogic.com/">'
  +dlAcct('Savings','1111','500.00','0','0',[dlTx('2026-09-01','5.00','500.00','INTEREST'),dlTx('2026-09-02','5.00','505.00','INTEREST'),dlTx('2026-09-03','5.00','510.00','INTEREST'),dlTx('2026-09-04','5.00','515.00','INTEREST'),dlTx('2026-09-04','5.00','520.00','INTEREST')])
  +dlAcct('Checking','2222','80.00','100.00','20.00',[dlTx('2026-09-02','-20.00','80.00','POS'),dlTx('2026-09-01','100.00','100.00','DEPOSIT')])
  +dlAcct('Checking','3333','1249.75','1000.00','250.25',[dlTx('2026-09-04','-10.00','1239.75','ACH HOLD','InstitutionPending'),dlTx('2026-09-03','-50.25','1249.75','POS STARBUCKS &amp; CO'),dlTx('2026-09-02','-200.00','1300.00','ACH DEBIT'),dlTx('2026-09-01','1000.00','1500.00','DEPOSIT')])
  +'</ArrayOfReportDetail7>';
var DL=lgFromDecisionLogicXml(xmlDoc(dlx)); DL&&lgFinalize(DL);
t('DecisionLogic XML verified on its busiest checking account', DL && DL.status==='verified' && DL.account==='****3333' && DL.rows.length===4 && DL.rows.filter(function(r){ return r.date==='PENDING'; }).length===1
  && DL.checks.filter(function(c){ return c.result==='pass'; }).length===3 && /2 other account\(s\).*Savings \*\*\*\*1111.*Checking \*\*\*\*2222/.test(DL.note) && DL.period.start==='2026-09-01',
  DL&&(DL.status+' '+DL.account+' '+DL.rows.length+' rows; '+DL.checks.map(function(c){ return '['+c.result+'] '+c.check; }).join('; ')+'; '+DL.note));
var DLb=lgFromDecisionLogicXml(xmlDoc(dlx.replace('<TotalDebits>250.25','<TotalDebits>999.99'))); DLb&&lgFinalize(DLb);
t('DecisionLogic XML total mismatch breaks', DLb && DLb.status==='breaks', DLb&&DLb.status);
t('non-DecisionLogic XML not claimed', lgFromDecisionLogicXml(xmlDoc('<Document><Stmt/></Document>'))===null);
