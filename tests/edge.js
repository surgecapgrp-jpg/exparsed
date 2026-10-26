// syntax of the whole inline script
try{ new Function(readFile(TESTS+"/.build/all.js")); print('PASS whole-page script parses'); }catch(e){ print('FAIL syntax: '+e); }
// E1: section closed by Total on page 1 must not swallow date+amount lines on page 2
var e1=[{ lines:[ L([at('January 1, 2026 through January 31, 2026',300)]), L([at('CHECKING SUMMARY',50)]), L([at('Beginning Balance',50),A('1,000.00')]), L([at('Deposits',50),at('1',300),A('100.00')]), L([at('Ending Balance',50),A('1,100.00')]),
  L([at('DEPOSITS',50)]), L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]), L([at('01/05',50),at('Deposit',100),A('100.00')]), L([at('Total Deposits',50),A('100.00')]) ]},
 { lines:[ L([at('01/31',50),at('Interest rate this period',100),A('0.05')]) ]}];
ok('E1 closed section does not carry over a page', fin(lgParseColumnar(e1)), { status:'verified', rows:1, unclaimed:1 });
// E2: a Title Case footer inside a table does not end it
var e2=[{ lines:[ L([at('January 1, 2026 through January 31, 2026',300)]), L([at('CHECKING SUMMARY',50)]), L([at('Beginning Balance',50),A('1,000.00')]), L([at('Deposits',50),at('2',300),A('300.00')]), L([at('Ending Balance',50),A('1,300.00')]),
  L([at('DEPOSITS',50)]), L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]), L([at('01/05',50),at('Deposit',100),A('100.00')]), L([at('Call Customer Service',200)]), L([at('01/12',50),at('Deposit',100),A('200.00')]) ]}];
ok('E2 Title Case footer keeps the section', fin(lgParseColumnar(e2)), { status:'verified', rows:2 });
// E3: a real error is still caught (a row with the wrong amount) and points at the page
var e3=[{ lines:[ L([at('Statement Period 01/01/2026 to 01/31/2026',300)]), L([at('Beginning Balance',50),B('1,000.00')]), L([at('Account Activity',50)]),
  L([at('Date',50),at('Description',110),D('Debits'),C('Credits'),B('Balance')]),
  L([at('01/05',50),at('Deposit',110),C('100.00'),B('1,100.00')]),
  L([at('01/06',50),at('POS',110),D('52.00'),B('1,075.00')]), L([at('Ending Balance',50),B('1,075.00')]) ]}];
var E3=fin(lgParseColumnar(e3)); ok('E3 wrong amount still breaks', E3, { status:'breaks', rows:2 });
// E4: two equal unsigned amounts on one balance segment cannot be settled -> flagged for review, not guessed
var e4='Statement Period 01/01/2026 to 01/31/2026\n\n## Transactions\n\n| Date | Description | Amount | Balance |\n|---|---|---|---|\n| 01/01 | Beginning Balance | | 1,000.00 |\n| 01/05 | Transfer in | 25.00 | |\n| 01/05 | Transfer out | 25.00 | 1,000.00 |\n';
var E4=fin(lgParseOcrTables(e4)); print((E4.checks.some(function(c){ return c.check==='row direction' && c.result==='review'; })?'PASS ':'FAIL ')+'E4 ambiguous directions flagged for review  status='+E4.status);
// E5: daily balances printed with full dates
var e5=[{ lines:[ L([at('January 1, 2026 through January 31, 2026',300)]), L([at('CHECKING SUMMARY',50)]), L([at('Beginning Balance',50),A('1,000.00')]), L([at('Ending Balance',50),A('1,100.00')]),
  L([at('DEPOSITS',50)]), L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]), L([at('01/05/2026',50),at('Deposit',100),A('100.00')]),
  L([at('DAILY BALANCES',50)]), L([at('01/05/2026',50),at('1,100.00',120)]) ]}];
var E5=fin(lgParseColumnar(e5)); print((E5.checks.some(function(c){ return /daily/.test(c.check) && c.result==='pass'; })?'PASS ':'FAIL ')+'E5 daily balances with full dates  status='+E5.status);
// E6: JSON transactions and camt still verify through the shared chain
var J=lgFromJsonTransactions({ transactions:[ {date:'2026-01-07',amount:50,balance:1125}, {date:'2026-01-06',amount:-25,balance:1075}, {date:'2026-01-05',amount:100,balance:1100} ] });
ok('E6 JSON transactions', fin(J), { status:'verified', rows:3 });
// E7: export -> re-import of a combined-table statement keeps its checks
var X=fin(lgParseOcrTables(m9));
var exp={ name:'m9', class:'statement', layout:X.layout, period:X.period, status:X.status, combinedTable:true, columns:'date|section|amount|balance|page|description',
  summary:{ beginning:X.summary.beginning/100, ending:X.summary.ending/100, sections:Object.keys(X.summary.sections).reduce(function(o,k){ var q=X.summary.sections[k]; o[k]={label:q.label,count:q.count,total:q.total/100}; return o; },{}) },
  rows:X.rows.map(function(r){ return [r.date,r.section,(r.signed/100).toFixed(2),r.balance==null?'':(r.balance/100).toFixed(2),r.page,r.desc].join('|'); }) };
ok('E7 re-imported combined table', fin(lgFromLedgerExportFile(exp)), { status:'verified', rows:3 });
// E8: one statement, two accounts (credit union: "BUSINESS INTEREST CHECKING - 0011" then
// "BUSINESS NON-INTEREST CHECKING - 0012"): split into one ledger per account, each reconciles
var e8=[{ lines:[ L([at('Statement Period: Jul 01 - Jul 31, 2026',300)]), L([at('BUSINESS INTEREST',300),A('$14,879.13'),B('$3,644.70')]),
  L([at('BUSINESS INTEREST CHECKING - 0011',50)]),
  L([at('Date',50),at('Transaction Description',110),D('Withdrawal'),C('Deposit'),B('Balance')]),
  L([at('Jul 01',50),at('Previous Balance',110),B('$1,000.00')]),
  L([at('Jul 02',50),at('Deposit ACH',110),C('500.00'),B('1,500.00')]),
  L([at('Jul 03',50),at('Withdrawal POS',110),D('-200.00'),B('1,300.00')]),
  L([at('Jul 31',50),at('Ending Balance',110),B('$1,300.00')]) ]},
 { lines:[ L([at('BUSINESS NON-INTEREST CHECKING - 0012',50)]),
  L([at('Date',50),at('Transaction Description',110),D('Withdrawal'),C('Deposit'),B('Balance')]),
  L([at('Jul 01',50),at('Previous Balance',110),B('$-50.00')]),
  L([at('Jul 02',50),at('Deposit Transfer From Share 0011',110),C('300.00'),B('250.00')]),
  L([at('Jul 31',50),at('Ending Balance',110),B('$250.00')]) ]}];
var S8=lgSplitAccounts(e8);
print((S8 && S8.length===2 && S8[0].id==='0011' && S8[1].id==='0012' ? 'PASS ' : 'FAIL ')+'E8 two account headings split the statement  '+(S8?S8.map(function(p){ return p.id; }).join(','):'null'));
if(S8 && S8.length===2){ ok('E8a account 0011 on its own', fin(lgParseColumnar(S8[0].pages)), { status:'verified', rows:2 }); ok('E8b account 0012 on its own', fin(lgParseColumnar(S8[1].pages)), { status:'verified', rows:1 }); }
print((lgSplitAccounts([e8[0]])===null ? 'PASS ' : 'FAIL ')+'E8c one account with rows is not split');
// E9: the reading choice: a later reading replaces an earlier one only when it ranks higher;
// verified ends the search; ifNone readings run only when nothing was read; final ends it when taken
(function(){
  var ran=[], R=function(name, status, opt){ return Object.assign({ name:name, read:function(){ ran.push(name); return status?{ status:status, name:name }:null; } }, opt||{}); };
  var t1=lgChooseReading([R('a','breaks'), R('b','breaks'), R('c','partial'), R('d','ok',{ifNone:true})]);
  print((t1.name==='c' && ran.join()==='a,b,c' ? 'PASS ' : 'FAIL ')+'E9a tie keeps the earlier reading, higher rank replaces it, ifNone skipped  '+t1.name+' ran '+ran.join());
  ran=[]; var t2=lgChooseReading([R('a','verified'), R('b','verified')]);
  print((t2.name==='a' && ran.join()==='a' ? 'PASS ' : 'FAIL ')+'E9b a verified reading ends the search  ran '+ran.join());
  ran=[]; var t3=lgChooseReading([R('a',null), R('b','breaks',{final:true}), R('c','partial')]);
  print((t3.name==='b' && ran.join()==='a,b' ? 'PASS ' : 'FAIL ')+'E9c a final reading ends the search when taken  ran '+ran.join());
  ran=[]; var errs=[]; var t4=lgChooseReading([{ name:'x', read:function(){ throw new Error('boom'); } }, R('y',null), R('z','breaks',{ifNone:true})], function(e){ errs.push(e.message); });
  print((t4.name==='z' && errs.join()==='boom' ? 'PASS ' : 'FAIL ')+'E9d a reading that throws counts as none and is reported');
})();
// E10: one check-register line, three checks across, the number after or before the amount
var r10=lgChkLineRows([at('1056',50),at('09-09',90),A('2,638.87'),at('1058',300),at('09-17',340),at('14.95',400)], true);
print((r10.length===2 && r10[0].cents===263887 && r10[0].desc==='1056' && r10[1].mmdd==='09/17' && r10[0].register===true ? 'PASS ' : 'FAIL ')+'E10 check-register line read on its own  '+JSON.stringify(r10.map(function(r){ return [r.mmdd,r.cents,r.desc]; })));
// E11: check results carry numbers. The chain check reports tested and breakCount; the reading
// choice adds them up and applies the "mostly holds" rule from the numbers, whatever the detail says.
(function(){
  var ch=lgChainCheck({ tested:20, untested:0, order:'oldest first', breaks:[{ date:'01/02', page:1, diff:500 }, { date:'01/09', page:2, diff:-500 }] }, '30 rows');
  print((ch.tested===20 && ch.breakCount===2 && ch.result==='break' && /20 printed balances tested.*2 breaks/.test(ch.detail) ? 'PASS ' : 'FAIL ')+'E11a chain check carries tested and breakCount  '+JSON.stringify([ch.tested, ch.breakCount]));
  var L={ checks:[ch, { check:'totals', result:'break', detail:'off by $5.00' }, { check:'x', result:'pass', detail:'99 breaks' }] };
  print((lgBreakTotal(L)===3 ? 'PASS ' : 'FAIL ')+'E11b break total: 2 chain breaks + 1 failed check, pass text ignored  '+lgBreakTotal(L));
  ch.detail='reworded entirely'; print((lgBreakTotal(L)===3 && lgChainMostlyHolds(L) ? 'PASS ' : 'FAIL ')+'E11c rewording the detail changes nothing');
  var few=lgChainCheck({ tested:9, untested:0, order:'oldest first', breaks:[] }, 'x'), many=lgChainCheck({ tested:20, untested:0, order:'oldest first', breaks:[1,2,3].map(function(i){ return { date:'01/0'+i, page:1, diff:1 }; }) }, 'x');
  print((!lgChainMostlyHolds({ checks:[few] }) && !lgChainMostlyHolds({ checks:[many] }) && !lgChainMostlyHolds({ checks:[] }) ? 'PASS ' : 'FAIL ')+'E11d under 10 tested, or over 1 in 10 broken, does not mostly hold');
  print((lgRowsRank({ status:'verified', rows:[] })===0 && lgRowsRank({ status:'breaks', rows:[1] })===1 && lgRowsRank({ status:'verified', rows:[1] })===3 ? 'PASS ' : 'FAIL ')+'E11e a reading with no rows ranks below any with rows');
})();
// E12: Valley Strong CU: accounts listed with "ID nnnn" on page 1, each section opened by
// "<NAME> BEGINNING BALANCE", counted credit and debit totals, debit and credit sections; margin
// marks before a date ("13/76 06/17 ...") and glued to a header ("1DATE CREDIT ...")
(function(){
  var T=function(s){ return L([at(s,36)]); };
  var e12=[{ lines:[ T('STATEMENT FOR 06/01/2026 - 06/30/2026'),
    T('BUSINESS SHARE SAVINGS ID 0001 $4.08-'), T('BUS PLUS CHECKING ID 0002 $2,777.58-'), T('ACCOUNT BALANCE TOTAL $2,781.66-'),
    T('BUSINESS SHARE SAVINGS BEGINNING BALANCE $25.50-'), T('1 TOTAL CREDITS $0.02-'), T('1 TOTAL DEBITS $21.44-'), T('ENDING BALANCE $4.08-'),
    T('DATE DEBIT TRANSACTION DESCRIPTION $0.00 1 1 - AMOUNT-'), T('06/04 WITHDRAWAL $21.44-'),
    T('DATE CREDIT TRANSACTION DESCRIPTION $0.00 1 1 - AMOUNT-'), T('06/30 DEPOSIT DIVIDEND $0.02') ]},
   { lines:[ T('BUS PLUS CHECKING BEGINNING BALANCE $1,000.00-'), T('1 TOTAL CREDITS $2,000.00-'), T('2 TOTAL DEBITS $222.42-'), T('ENDING BALANCE $2,777.58-'),
    T('DATE DEBIT TRANSACTION DESCRIPTION $14.00 2 1 - AMOUNT-'), T('06/01 DRAFT 1269 TRACER 000000000000000 $208.42-'), T('13/76 06/17 WITHDRAWAL NSF RETURN FEE IN THE AMOUNT $315.13. $14.00-'),
    T('1DATE CREDIT TRANSACTION DESCRIPTION $14.00 2 1 - AMOUNT-'), T('06/05 DEPOSIT HOME BANKING TRANSFER FROM SHARE 0001 $2,000.00'),
    T('SUMMARY BY CHECK NUMBER 1 CHECKS CLEARED FOR $208.42-'), T('1269 06/01 $208.42') ]}];
  var S12=lgSplitAccounts(e12);
  print((S12 && S12.length===2 && S12[0].id==='0001' && S12[1].id==='0002' ? 'PASS ' : 'FAIL ')+'E12a sections named by the ID list are split  '+(S12?S12.map(function(p){ return p.id; }).join(','):'null'));
  if(S12 && S12.length===2){
    var a=lgParseCuSections(S12[0].pages), b=lgParseCuSections(S12[1].pages);
    ok('E12b savings 0001 reconciles', a&&lgFinalize(a), { status:'verified', rows:2 });
    ok('E12c checking 0002 reconciles, check summary not read as a row', b&&lgFinalize(b), { status:'verified', rows:3 });
    print((b && b.rows[1].date==='2026-06-17' && b.rows[2].kind==='credit' ? 'PASS ' : 'FAIL ')+'E12d margin marks before a date and on a header are skipped  '+(b?JSON.stringify(b.rows.map(function(r){ return [r.date, r.kind, r.cents]; })):''));
  }
})();
// E13: the same statement with Numerica's headings ("FREE BUSINESS CHECKING-E WENAT ID: 10", a masked
// member number on every page) and with Chase / Wells Fargo's ("... Account Number: 000000536608521",
// "Statement period activity summaryAccount number: 2910038443 (primary account)"): one ledger per account
(function(){
  function swap(h1, h2, pageHead){ return e8.map(function(pg, i){ var ls=pg.lines.map(function(l){ var t=l.text;
      if(t==='BUSINESS INTEREST CHECKING - 0011') return L([at(h1,50)]);
      if(t==='BUSINESS NON-INTEREST CHECKING - 0012') return L([at(h2,50)]);
      return l; });
    return { lines:(pageHead?[L([at(pageHead,300)])]:[]).concat(ls) }; }); }
  var n=lgSplitAccounts(swap('FREE BUSINESS CHECKING-E WENAT ID: 10', 'FREE BUSINESS CHECKING-QUINCY ID: 11', 'Account Number: xxxxxx9901'));
  print((n && n.length===2 && n[0].id==='10' && n[1].id==='11' ? 'PASS ' : 'FAIL ')+'E13a "CHECKING-E WENAT ID: 10" shares split, a masked number opens nothing  '+(n?n.map(function(p){ return p.id; }).join(','):'null'));
  if(n && n.length===2){ ok('E13b share 10 on its own', fin(lgParseColumnar(n[0].pages)), { status:'verified', rows:2 }); ok('E13c share 11 on its own', fin(lgParseColumnar(n[1].pages)), { status:'verified', rows:1 }); }
  var c=lgSplitAccounts(swap('Statement period activity summaryAccount number: 2910038443 (primary account)', 'L & E PALLETS AND LUMBER, INC. Account Number: 000003799680815'));
  print((c && c.length===2 && c[0].id==='2910038443' && c[1].id==='3799680815' ? 'PASS ' : 'FAIL ')+'E13d a second full account number splits the statement  '+(c?c.map(function(p){ return p.id; }).join(','):'null'));
})();
// E14: the remaining Desktop breaks, one check each
(function(){
  function eq(name, got, want){ var g=JSON.stringify(got), w=JSON.stringify(want); print((g===w?'PASS ':'FAIL ')+name+'  '+g); }
  // wrapped cents (DecisionLogic): "$1,386,500." | "$1,601,323." over "00" | "12"
  var wp=lgJoinWrappedCents([{ lines:[ { text:'x', items:[{ s:'8/4/2026', x:26, w:40 }, { s:'$1,386,500.', x:492, w:45 }, { s:'$1,601,323.', x:543, w:45 }] },
    { text:'00 12', items:[{ s:'00', x:525, w:8 }, { s:'12', x:577, w:8 }] } ] }]);
  eq('E14a cents wrapped onto the next line go back on their figures', wp[0].lines.map(function(l){ return l.items.map(function(it){ return it.s; }); }), [['8/4/2026','$1,386,500.00','$1,601,323.12']]);
  eq('E14b two unlabelled dates on lines of their own give the period', lgFindPeriod('Statement of Account\nAugust 3,2026\nAugust 31,2026\n1001811833'), { start:'2026-08-03', end:'2026-08-31' });
  eq('E14c headings: returned checks are credits, a fee explanation and Comerica fees', [lgSectionOf('RETURNED CHECKS').key, lgSectionOf('Explanation of Service Fees').kind, lgSectionOf('Fees and service charges this statement period').key, lgSectionOf('Checks 73 checks totaling $479,663.79').key], ['ret','other','fee','chk']);
  eq('E14d pending amounts and "(EFT)" in summary labels', [lgSummaryKey('Pending withdrawals/debits'), lgSummaryKey('Electronic (EFT) withdrawals'), lgSummaryKey('Paper deposits')], [null,'elec','dep']);
  eq('E14e a month and day run together ("Apr06")', lgDateTok('Apr06'), { mmdd:'04/06', iso:null });
})();
// E15: the Mac OCR scans in the Desktop set: months scanned into one file, a phone app's three-line rows
(function(){
  function eq(name, got, want){ var g=JSON.stringify(got), w=JSON.stringify(want); print((g===w?'PASS ':'FAIL ')+name+'  '+g); }
  function P(ls){ return { hasText:true, lines:ls.map(function(t){ return { text:t, items:[{ s:t, x:50, w:200 }] }; }) }; }
  var ks=lgSplitStatements([P(['July 31, 2026','page 1 of 2','07/02 DEPOSIT 100.00']), P(['page 2 of 2']), P(['August 31, 2026','page 1 of 1','08/03 DEPOSIT 50.00'])]);
  eq('E15a a second "page 1 of N" opens the next statement', ks && ks.map(function(k){ return [k.statement, k.pages.map(function(p){ return p.lines.length; })]; }), [[true,[3,1,0]],[true,[0,0,3]]]);
  eq('E15b one "page 1 of N" is one statement', lgSplitStatements([P(['page 1 of 2','07/02 DEPOSIT 100.00']), P(['page 2 of 2','07/03 DEPOSIT 5.00'])]), null);
  var st=lgParseStackedRows([P(['Silver Business Checking ...3272','Pending','10/20/2026 Fast $271.25','Posted',
    '$36.00','10/13/2026 Overdraft Fee','-$306.95', '$271.25','10/09/2026 Fast','-$270.95', '+$500.00','10/08/2026 Deposit','$0.30',
    'Transfer To 7055','10/08/2026 $-499.70', '$1,000.00$1,000.00','10/07/2026 Zelle To Kalamata $500.30', '$2.18','Ncr Ps $1,500.30','10/06/2026'])]);
  eq('E15c phone-app rows: amount, date and payee, balance (and the orders OCR mixes up)', st && st.rows.map(function(r){ return [r.date, r.kind, r.cents, r.balance]; }),
    [['PENDING','debit',27125,null],['2026-10-13','debit',3600,-30695],['2026-10-09','debit',27125,-27095],['2026-10-08','credit',50000,30],['2026-10-07','debit',100000,50030],['2026-10-06','debit',218,150030]]);
})();
