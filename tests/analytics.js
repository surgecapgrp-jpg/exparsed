// ---- computed analytics: unnumbered-file linking, printed itemization, statement ADB,
// month sums, printed figures passed through (synthetic data; mirrors a real case where a bank CSV
// with no account number followed a PDF statement, and only its balances tied the two together)
function t(name, cond, got){ print((cond?'PASS ':'FAIL ')+'analytics: '+name+(cond?'':'   got '+JSON.stringify(got))); }
function R(date, signed, desc, balance){ return { date:date, signed:signed, cents:Math.abs(signed), section:signed<0?'elec':'dep', desc:desc, page:1, balance:balance==null?null:balance }; }
function stmt(){
  var rows=[R('2026-01-05',100000,'INCOMING WIRE ACME STORES LLC'), R('2026-01-06',-3000,'Paid Item Fee'), R('2026-01-06',-3000,'Returned Item Fee'),
            R('2026-01-07',3000,'Reverse Paid/Return Item Fee'), R('2026-01-08',-17560,'GUSTO FEE 126613 6seml74 9138864007 ACME'),
            R('2026-01-12',9000000,'INCOMING WIRE MDF HOLDINGS'), R('2026-01-13',540000,'OLB Transfer from *864 to *960 Transfer'),
            R('2026-01-14',-9542440,'OUTGOING WIRE SUPPLIER')];
  var end=200000; rows.forEach(function(r){ end+=r.signed; });
  return { name:'jan.pdf', _ledger:{ cls:'statement', status:'verified', fileName:'jan.pdf', account:'****1234', period:{ start:'2026-01-01', end:'2026-01-31' },
    summary:{ beginning:200000, ending:end, sections:{} }, rows:rows, daily:{},
    printed:{ avgBalance:123456, feePeriod:6000, feeYtd:null } } };
}
function csvAfter(S, delta){
  var open=S._ledger.summary.ending+(delta||0);
  // newest first, like a bank download
  var r1=R('2026-02-02',125000,'OLB Transfer from *864 to *960 Transfer', open+125000);
  var r2=R('2026-02-03',-2500,'SRG CAP 51636945 12 ACME', open+122500);
  return { name:'download.csv', _ledger:{ cls:'printout', status:'verified', fileName:'download.csv', account:null, rows:[r2,r1], summary:null, daily:null } };
}

var S1=stmt(), P1=csvAfter(S1);
var cross=lgCrossFile([S1,P1]);
t('CSV with no account number links when its opening balance = prior statement ending', lgAcct4(P1._ledger)==='1234' && cross.some(function(c){ return /linked to account/.test(c.check) && c.result==='pass'; }), cross);
t('linked CSV oldest day counts as complete', P1._ledger.oldestDayComplete===true);
var C=lgComputed([S1,P1]);
t('linked files are computed as one account', C.length===1 && C[0].account==='1234' && C[0].window.end==='2026-02-03', C.map(function(a){ return a.account; }));
t('no partial-day note for a chained oldest day', !C[0].notes.some(function(n){ return /partial day/.test(n); }), C[0].notes);
var S2=stmt(), P2=csvAfter(S2, 1);
lgCrossFile([S2,P2]);
t('a balance off by one cent does not link', /^unknown:/.test(lgAcct4(P2._ledger)), lgAcct4(P2._ledger));

var jan=C[0].months.filter(function(m){ return m.month==='2026-01'; })[0];
var avg=C[0].checks.filter(function(c){ return /printed average balance/.test(c.check); })[0];
t('printed fee itemization passed through as printed', C[0].statements[0].printedNsfFees===6000, C[0].statements[0]);
t('computed figures carry no labels', !('debitFamilies' in C[0]) && !('creditSources' in C[0]) && !('feeBurn' in jan) && !('netOperatingInflows' in jan), Object.keys(C[0]));
t('month gross in / out are plain sums', jan.grossInflows===100000+3000+9000000+540000 && jan.grossOutflows===3000+3000+17560+9542440, jan);
t('printed average balance checked over the statement period', avg && avg.result==='break' && C[0].statements[0].printedAvgBalance===123456, avg);



var P=lgPrintedExtras({ pages:[{ hasText:true, lines:[
  { text:'Average Balance This Statement $810.89 Annual Percentage Yield Earned' },
  { text:'Total NSF/Overdraft Paid Item Fees $630.00 $5,790.00' },
  { text:'Total NSF/Overdraft Returned Item Fees $300.00 $1,980.00' },
  { text:'Total Overdraft Fees $0.00 $35.00' }] }] });
t('printed average balance and fee itemization read from statement text', P && P.avgBalance===81089 && P.feePeriod===93000 && P.feeYtd===780500, P);
var R2=function(c){ return { cents:c }; };
t('a gap equal to one row is named', /one row/.test(lgClassify(500,[R2(100),R2(500)])));
t('a gap equal to two rows is named', /two rows/.test(lgClassify(750,[R2(100),R2(250),R2(500)])));
t('a gap no row combination explains stays a break', lgClassify(999,[R2(100),R2(250),R2(500)])==='BREAK');

// ---- lgDocKind: what an unread file is ----
function dkPages(arr){ return arr.map(function(t){ var ls=t.split('\n').filter(function(x){ return x.trim(); }).map(function(x){ return { text:x, items:[] }; }); return { lines:ls, hasText:ls.length>0 }; }); }
var dkCR=lgDocKind({ type:'pdf', pages:dkPages(['Surge Capital Group LLC\nApplication Number: 393\nEquifax score 701\nExperian 690\nTransUnion 702\nTradelines 14\n01/2024 Auto loan 12,000.00']) });
t('a credit report is not a statement', dkCR && dkCR.status==='not-statement' && dkCR.kind==='credit report');
var dkST=lgDocKind({ type:'pdf', pages:dkPages(['Account Summary\nBeginning balance 1,000.00\n06/01 Deposit 200.00\n06/02 Check 101 50.00\n06/03 ACH debit 25.00\nEnding balance 1,125.00']) });
t('a page with beginning, ending balance and dated rows stays a statement', dkST && dkST.status==='unparsed');
var dkOCR=lgDocKind({ type:'pdf', pages:dkPages(['ACME LLC 1 Main St','','','']) });
t('a file whose pages mostly have no text needs OCR', dkOCR && dkOCR.status==='needs-ocr');
var dkPR=lgDocKind({ type:'pdf', pages:dkPages(['Business Checking ...1234\nAvailable balance $500.00\nPosting date\n04/29/2026\nCheck 1033\n-$800.00\n04/28/2026\nTransfer\n$5,000.00\n04/27/2026\nDeposit\n$100.00\nPending']) });
t('an online account printout stays a statement', dkPR && dkPR.status==='unparsed');
var dkCT=lgDocKind({ type:'pdf', pages:dkPages(['AGREEMENT FOR THE PURCHASE AND SALE OF FUTURE RECEIVABLES\nMerchant agrees to sell...\nPersonal Guaranty']) });
t('a funding contract is not a statement', dkCT && dkCT.status==='not-statement' && dkCT.kind==='funding contract');

// ---- round 6: readers for the last unparsed FUNDED layouts ----
// a statement period with no activity (Chase commercial: "Opening/Ending Ledger Balance")
var naL=lgNoActivity(dkPages(['April 01, 2026 through April 30, 2026\nAccount Number: 000000660087696\nSummary\nOpening Ledger Balance $0.00\nDeposits and Credits 0 $0.00\nWithdrawals and Debits 0 $0.00\nEnding Ledger Balance $0.00']), null);
t('no activity: equal opening and ending balances read as an empty period', naL && naL.layout==='no-activity' && naL.summary.beginning===0 && naL.period.start==='2026-04-01');
var naX=lgNoActivity(dkPages(['April 01, 2026 through April 30, 2026\nOpening Ledger Balance $10.00\n04/02 Deposit 5.00\n04/03 Check 5.00\nEnding Ledger Balance $10.00']), null);
t('no activity: dated rows with amounts are never called an empty period', naX===null);
// amount, date, balance on each row (Fremont Bank)
var fbL=lgFinalize(lgParseAmtDateBal(dkPages(['Balance Last Statement Credits Debits Balance This Statement\n$100.00 (1) $50.00 (1) $20.00 $130.00\nDescription Transaction Amount Date Balance\nBALANCE LAST STATEMENT 07/31 100.00\nOnline Transfer from X7805 50.00 08/06 150.00\nPAYROLLTAX TAX DEBIT -20.00 08/07 130.00\nBALANCE THIS STATEMENT 08/31 130.00\nTOTAL DAYS IN STATEMENT PERIOD 08/01/26 THROUGH 08/31/26: 31'])));
t('amount-date-balance rows reconcile to the summary counts and totals', fbL.status==='verified' && fbL.rows.length===2 && fbL.rows[1].signed===-2000);
// the day over the month (Jefferson Bank)
var jbL=lgFinalize(lgParseDayMonth(dkPages(['Statement Dates 4/01/26 thru 4/30/26\nPrevious Balance $100.00\n1 Deposits/Credits $50.00\n2 Checks /Debits $30.00\nService Charge $0.00\nCurrent Balance $120.00\nDeposits & Other Credits\n01\nAPR Deposit $50.00\nOther Items - Charges\n02\nAPR ONLINE PMT CAPITAL ONE--CCD $10.00\nChecks\n03 Check# 101 $20.00\nAPR\n04 Check# 102 $0.00\nAPR\nDaily Balance\nDate Balance Date Balance\n4/01 $150.00 4/02 $140.00 4/03 $120.00\n*** End of Statement ***\nAmount: $50.00 Date: 04/01/26'])));
t('day-month rows reconcile; a zero-amount check is not a row', jbL.status==='verified' && jbL.rows.length===3);
// a balances-only online page is not a statement
var bpK=lgDocKind({ type:'pdf', pages:dkPages(['2/9/26, 6:56 PM Account Details | Bank of Hope\nKNIT GENERATION 1559\n$86,004.58$84,148.32\nCurrent BalanceAvailable Balance\nAvailable Balance $84,148.32Current Balance $86,004.58\nAccount Number 16321559Routing Number 122041235\nLast Statement Date Apr 30, 2026']) });
t('an account details page with balances only is not a statement', bpK && bpK.status==='not-statement' && bpK.kind==='account balance page', bpK);
// deposits and withdrawals in columns, placed by position (Wells Fargo online)
function itl(y, parts){ return { y:y, text:parts.map(function(p){ return p[1]; }).join(' '), items:parts.map(function(p){ return { x:p[0], s:p[1], w:p[1].length*5 }; }) }; }
var wfL=lgFinalize(lgParseCreditDebitColumns([{ hasText:true, lines:[
  itl(700,[[43,'Date'],[112,'Description'],[364,'Deposits/Credits'],[473,'Withdrawals/Debits'],[599,'Ending Daily Balance']]),
  itl(680,[[43,'07/14/26'],[112,'ACH DEPOSIT'],[400,'$'],[406,'100.00'],[650,'-'],[655,'$'],[663,'250.00']]),
  itl(660,[[43,'07/14/26'],[112,'PURCHASE'],[536,'$'],[545,'50.00']]),
  itl(640,[[43,'07/13/26'],[112,'CHECK # 1'],[526,'$'],[545,'20.00'],[650,'-'],[655,'$'],[663,'300.00']]),
  itl(620,[[43,'07/12/26'],[112,'TRANSFER'],[400,'$'],[406,'10.00'],[650,'-'],[655,'$'],[663,'280.00']])]}]));
t('credit/debit columns: direction by column, a "- $" balance is negative, the chain holds', wfL.rows.length===4 && wfL.rows[1].kind==='debit' && wfL.rows[2].balance===-30000 && wfL.status!=='breaks', { st:wfL.status, rows:wfL.rows.map(function(r){ return [r.kind,r.signed,r.balance]; }), ch:wfL.checks.map(function(c){ return c.detail; }) });
// the chain lets a day's rows follow their balances in any order
var rch=lgBalanceChain([{ date:'2026-06-04', signed:500, balance:1700 },{ date:'2026-06-04', signed:200, balance:1200 }], 1000, false);
t('running balance: a day listed out of posting order still chains', rch.breaks.length===0 && rch.tested===2, rch);
