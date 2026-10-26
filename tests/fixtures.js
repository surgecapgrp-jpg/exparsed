// ---- helpers: build pdf.js-shaped pages (lines of positioned items) ----
function I(s,x,w){ return { s:s, x:x, w:(w==null?s.length*5:w) }; }
function L(items){ var it=items.map(function(a){ return typeof a==='string'?I(a,50):a; }); return { text:it.map(function(i){return i.s;}).join(' '), y:0, items:it }; }
function R(x){ return function(s){ return I(s, x - s.length*5, s.length*5); }; }      // right-aligned at x
var at=function(s,x){ return I(s,x); };
function ok(name, L, want){
  var got={ status:L.status, rows:(L.rows||[]).length, unclaimed:(L.unclaimed||[]).length };
  var pass=Object.keys(want).every(function(k){ return got[k]===want[k]; });
  print((pass?'PASS ':'FAIL ')+name+'  '+JSON.stringify(got)+(pass?'':'   want '+JSON.stringify(want)));
  if(!pass && L.checks) L.checks.forEach(function(c){ print('       ['+c.result+'] '+c.check+': '+c.detail); });
  if(!pass && L.unclaimed) L.unclaimed.forEach(function(u){ print('       unclaimed p'+u.page+' '+u.text+' -- '+u.why); });
  return pass;
}
function fin(L){ return lgFinalize(L); }
var A=R(500), B=R(560), D=R(420), C=R(480);

// ---- REGRESSION: Chase-style sectioned statement (must stay verified) ----
var chase=[{ lines:[
  L([at('January 01, 2026 through January 31, 2026',300)]),
  L([at('Account Number:',300),at('000000123456789',380)]),
  L([at('CHECKING SUMMARY',50)]),
  L([at('Beginning Balance',50),A('$1,000.00')]),
  L([at('Deposits and Additions',50),at('2',300),A('300.00')]),
  L([at('Checks Paid',50),at('1',300),A('50.00')]),
  L([at('ATM & Debit Card Withdrawals',50),at('1',300),A('25.00')]),
  L([at('Ending Balance',50),A('$1,225.00')]),
  L([at('DEPOSITS AND ADDITIONS',50)]),
  L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]),
  L([at('01/05',50),at('Deposit',100),A('100.00')]),
  L([at('01/12',50),at('ACH Credit Stripe Transfer',100),A('200.00')]),
  L([at('Total Deposits and Additions',50),A('$300.00')]),
  L([at('CHECKS PAID',50)]),
  L([at('CHECK NO.',50),at('DESCRIPTION',120),at('DATE PAID',380),A('AMOUNT')]),
  L([at('1001',50),at('^',80),at('01/15',380),A('50.00')]),
  L([at('Total Checks Paid',50),A('$50.00')]),
  L([at('Page 1 of 2',450)]) ]},
 { lines:[
  L([at('ATM & DEBIT CARD WITHDRAWALS',50)]),
  L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]),
  L([at('01/20',50),at('Card Purchase 01/19 Starbucks Card 1234',100),A('25.00')]),
  L([at('Total ATM & Debit Card Withdrawals',50),A('$25.00')]),
  L([at('DAILY ENDING BALANCE',50)]),
  L([at('DATE',50),at('AMOUNT',120),at('DATE',250),at('AMOUNT',320)]),
  L([at('01/05',50),at('1,100.00',120),at('01/12',250),at('1,300.00',320)]),
  L([at('01/15',50),at('1,250.00',120),at('01/20',250),at('1,225.00',320)]),
  L([at('Page 2 of 2',450)]) ]}];
ok('REG chase sectioned statement', fin(lgParseColumnar(chase)), { status:'verified', rows:4 });

// ---- REGRESSION: Chase printout, newest first ----
var pr=[{ lines:[
  L([at('Date',50),at('Description',120),at('Amount',380),at('Type',450),at('Balance',520)]),
  L([at('Jan 20, 2026',50),at('Card purchase Starbucks',120),at('-25.00',380),at('Debit',450),at('$1,225.00',520)]),
  L([at('Jan 15, 2026',50),at('Check 1001',120),at('-50.00',380),at('Check',450),at('$1,250.00',520)]),
  L([at('Jan 12, 2026',50),at('ACH credit Stripe',120),at('200.00',380),at('ACH',450),at('$1,300.00',520)]),
  L([at('Jan 5, 2026',50),at('Deposit',120),at('100.00',380),at('Deposit',450),at('$1,100.00',520)]) ]}];
ok('REG printout newest-first', fin(lgParsePrintout(pr)), { status:'verified', rows:4 });

// ---- REGRESSION: Chase OCR markdown, upper-case headings ----
var chaseMd='January 01, 2026 through January 31, 2026\n\n## CHECKING SUMMARY\n\n| | Instances | Amount |\n|---|---|---|\n| Beginning Balance | | $1,000.00 |\n| Deposits and Additions | 2 | 300.00 |\n| Checks Paid | 1 | 50.00 |\n| Ending Balance | | $1,250.00 |\n\n## DEPOSITS AND ADDITIONS\n\n| DATE | DESCRIPTION | AMOUNT |\n|---|---|---|\n| 01/05 | Deposit | 100.00 |\n| 01/12 | ACH Credit Stripe | 200.00 |\n\n## CHECKS PAID\n\n| CHECK NO. | DESCRIPTION | DATE PAID | AMOUNT |\n|---|---|---|---|\n| 1001 | ^ | 01/15 | 50.00 |\n';
ok('REG OCR chase upper-case', fin(lgParseOcrTables(chaseMd)), { status:'verified', rows:3 });

// ---- MESSY 1: credit union, numeric period, combined Withdrawals|Deposits|Balance table, no heading, full dates, balance-forward rows ----
var m1=[{ lines:[
  L([at('Statement Period: 01/01/2026 - 01/31/2026',300)]),
  L([at('Share Draft',50)]),
  L([at('Date',50),at('Description',110),D('Withdrawals'),C('Deposits'),B('Balance')]),
  L([at('01/01/2026',50),at('Beginning Balance',110),B('1,000.00')]),
  L([at('01/05/2026',50),at('Deposit Shared Branch',110),C('100.00'),B('1,100.00')]),
  L([at('01/06/2026',50),at('POS Purchase Starbucks',110),D('25.00'),B('1,075.00')]),
  L([at('01/09/2026',50),at('ACH Debit Acme Funding',110),D('1500.00'),B('-425.00')]),
  L([at('01/31/2026',50),at('Ending Balance',110),B('-425.00')]) ]}];
ok('M1 combined table, no heading, full dates', fin(lgParseColumnar(m1)), { status:'verified', rows:3 });

// ---- MESSY 2: same statement, every line one text run (line-printer style) ----
function run(s){ return L([I(s,50,s.length*5)]); }
var m2=[{ lines:[ run('STATEMENT PERIOD 01/01/26 THRU 01/31/26'), run('DATE        DESCRIPTION                 WITHDRAWALS     DEPOSITS      BALANCE'),
  run('01/01/26    BEGINNING BALANCE                                          1,000.00'),
  run('01/05/26    DEPOSIT                                      100.00        1,100.00'),
  run('01/06/26    POS PURCHASE STARBUCKS          25.00                      1,075.00') ]}];
// column header is one run too, so columns cannot be placed by header: balance decides direction
ok('M2 one text run per line', fin(lgParseColumnar(m2)), { status:'verified', rows:2 });

// ---- MESSY 3: per-glyph items ----
function glyphs(s,x){ var out=[]; for(var i=0;i<s.length;i++) if(s[i]!==' ') out.push(I(s[i],x+i*5,5)); return out; }
var m3=[{ lines:[ L([at('January 1, 2026 through January 31, 2026',300)]), L([at('DEPOSITS',50)]), L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]),
  L(glyphs('01/05',50).concat(glyphs('DEPOSIT',100)).concat([A('1,234.56')])), L([at('Total Deposits',50),A('1,234.56')]) ]}];
ok('M3 per-glyph items', fin(lgParseColumnar(m3)), { rows:1 });

// ---- MESSY 4: signed single Amount column + Balance, title-case heading ----
var m4=[{ lines:[ L([at('Statement Period 01/01/2026 to 01/31/2026',300)]), L([at('Beginning Balance',50),B('1,000.00')]), L([at('Account Activity',50)]),
  L([at('Date',50),at('Description',110),C('Amount'),B('Balance')]),
  L([at('01/05',50),at('Mobile Deposit',110),C('100.00'),B('1,100.00')]),
  L([at('01/06',50),at('Debit Card Purchase',110),C('-25.00'),B('1,075.00')]),
  L([at('Ending Balance',50),B('1,075.00')]) ]}];
ok('M4 signed Amount + Balance', fin(lgParseColumnar(m4)), { status:'verified', rows:2 });

// ---- MESSY 5: unsigned Amount column + Balance: direction must come from the balance ----
var m5=[{ lines:[ L([at('Statement Period 01/01/2026 to 01/31/2026',300)]), L([at('Beginning Balance',50),B('1,000.00')]), L([at('TRANSACTIONS',50)]),
  L([at('Date',50),at('Description',110),C('Amount'),B('Balance')]),
  L([at('01/05',50),at('Mobile Deposit',110),C('100.00'),B('1,100.00')]),
  L([at('01/06',50),at('Debit Card Purchase',110),C('25.00'),B('1,075.00')]),
  L([at('Ending Balance',50),B('1,075.00')]) ]}];
var L5=fin(lgParseColumnar(m5)); ok('M5 unsigned Amount, balance decides', L5, { status:'verified', rows:2 });
print('       directions: '+(L5.rows||[]).map(function(r){ return r.desc+'='+r.kind; }).join(', '));

// ---- MESSY 6: section continues on page 2 with no heading repeated ----
var m6=[{ lines:[ L([at('January 1, 2026 through January 31, 2026',300)]), L([at('CHECKING SUMMARY',50)]), L([at('Beginning Balance',50),A('1,000.00')]), L([at('Deposits',50),at('2',300),A('300.00')]), L([at('Ending Balance',50),A('1,300.00')]),
  L([at('DEPOSITS',50)]), L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]), L([at('01/05',50),at('Deposit',100),A('100.00')]) ]},
 { lines:[ L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]), L([at('01/20',50),at('Deposit',100),A('200.00')]), L([at('Total Deposits',50),A('300.00')]) ]}];
ok('M6 page 2 without re-heading', fin(lgParseColumnar(m6)), { status:'verified', rows:2 });

// ---- MESSY 7: amounts without thousands separators, CR/DR suffix ----
var m7=[{ lines:[ L([at('Statement Period 01/01/2026 to 01/31/2026',300)]), L([at('Beginning Balance',50),B('1000.00')]), L([at('Account Activity',50)]),
  L([at('Date',50),at('Description',110),C('Amount'),B('Balance')]),
  L([at('01/05',50),at('Deposit',110),C('1500.00CR'),B('2500.00')]),
  L([at('01/06',50),at('Withdrawal',110),C('250.00DR'),B('2250.00')]),
  L([at('Ending Balance',50),B('2250.00')]) ]}];
ok('M7 no-comma + CR/DR', fin(lgParseColumnar(m7)), { status:'verified', rows:2 });

// ---- MESSY 8: OCR, title-case headings, full dates in cells ----
var m8='Statement Period: 01/01/2026 - 01/31/2026\n\n## Account Summary\n\n| | Amount |\n|---|---|\n| Beginning Balance | $1,000.00 |\n| Deposits and Other Credits | 300.00 |\n| Withdrawals and Other Debits | 25.00 |\n| Ending Balance | $1,275.00 |\n\n## Deposits and Other Credits\n\n| Date | Description | Amount |\n|---|---|---|\n| 01/05/2026 | Deposit | 100.00 |\n| 01/12/2026 | ACH Credit | 200.00 |\n\n## Withdrawals and Other Debits\n\n| Date | Description | Amount |\n|---|---|---|\n| 01/20/2026 | POS Purchase | 25.00 |\n';
ok('M8 OCR title-case + full dates', fin(lgParseOcrTables(m8)), { status:'verified', rows:3 });

// ---- MESSY 9: OCR combined table Debit|Credit|Balance, balance-forward row, summary splits checks vs other debits ----
var m9='Statement Period 01/01/2026 to 01/31/2026\n\n**Summary**\n\n| | Count | Amount |\n|---|---|---|\n| Beginning Balance | | 1,000.00 |\n| Deposits | 1 | 100.00 |\n| Checks | 1 | 50.00 |\n| Other Debits | 1 | 25.00 |\n| Ending Balance | | 1,025.00 |\n\n**Transaction Detail**\n\n| Date | Description | Debit | Credit | Balance |\n|---|---|---|---|---|\n| 01/01 | Balance Forward | | | 1,000.00 |\n| 01/05 | Deposit | | 100.00 | 1,100.00 |\n| 01/07 | Check 1001 | 50.00 | | 1,050.00 |\n| 01/09 | ACH Debit Acme | 25.00 | | 1,025.00 |\n';
ok('M9 OCR combined table', fin(lgParseOcrTables(m9)), { status:'verified', rows:3 });

// ---- MESSY 10: OCR table with Credit|Balance and no AMOUNT header ----
var m10='## DEPOSITS\n\n| Date | Description | Credit | Balance |\n|---|---|---|---|\n| 01/05 | DEPOSIT | 100.00 | 1,100.00 |\n';
var L10=fin(lgParseOcrTables(m10)); print(((L10.rows[0]||{}).cents===10000?'PASS ':'FAIL ')+'M10 OCR amount is not the balance  cents='+(L10.rows[0]||{}).cents);

// ---- MESSY 11: printout oldest-first ----
var p11=[{ lines:[ L([at('Date',50),at('Description',120),at('Amount',380),at('Balance',520)]),
  L([at('01/05/2026',50),at('Deposit',120),at('100.00',380),at('1,100.00',520)]),
  L([at('01/06/2026',50),at('Card purchase',120),at('-25.00',380),at('1,075.00',520)]),
  L([at('01/07/2026',50),at('Deposit',120),at('50.00',380),at('1,125.00',520)]) ]}];
ok('M11 printout oldest-first', fin(lgParsePrintout(p11)), { status:'verified', rows:3 });

// ---- MESSY 12: "verified" must need a check that covers every row ----
var q={ cls:'statement', rows:[ {date:'2026-01-05',section:'dep',kind:'credit',cents:10000,signed:10000,page:1} ], summary:{ sections:{ dep:{label:'Deposits',count:1,total:10000} } }, daily:{} };
ok('M12 deposits-only check is partial', fin(q), { status:'partial' });

// ---- MESSY 13: unclaimed lines are reported ----
var m13=[{ lines:[ L([at('January 1, 2026 through January 31, 2026',300)]), L([at('DEPOSITS',50)]), L([at('DATE',50),at('DESCRIPTION',100),A('AMOUNT')]), L([at('01/05',50),at('Deposit',100),A('100.00')]),
  L([at('SERVICE CHARGE SUMMARY',50)]), L([at('01/31',50),at('Monthly service fee waived',100),A('12.00')]) ]}];
ok('M13 unread rows listed', fin(lgParseColumnar(m13)), { rows:1, unclaimed:1 });

// ---- MESSY 14: TD Bank layout ----
// "Statement Period: May 04 2026-Jun 03 2026" (no comma); a summary with no heading whose credit
// lines (Deposits / Electronic Deposits / Other Credits) all map to dep; a "Checks Paid" heading
// sharing its line with a note; a two-across check grid; fees under a bare "Service Charges".
var P=R(560);
var td=[{ lines:[
  L([at('Statement Period: May 04 2026-Jun 03 2026',300)]),
  L([at('Primary Account #: 443-4161234',300)]),
  L([at('Beginning Balance',65),R(250)('1,000.00'),at('Average Collected Balance',350),R(560)('900.00')]),
  L([at('Deposits',65),R(250)('500.00'),at('Interest Earned This Period',350),R(560)('0.00')]),
  L([at('Electronic Deposits',65),R(250)('300.00')]),
  L([at('Other Credits',65),R(250)('200.00')]),
  L([at('Checks Paid',65),R(250)('150.00')]),
  L([at('Electronic Payments',65),R(250)('400.00')]),
  L([at('Other Withdrawals',65),R(250)('230.00')]),
  L([at('Service Charges',65),R(250)('23.00')]),
  L([at('Ending Balance',65),R(250)('1,197.00')]),
  L([at('DAILY ACCOUNT ACTIVITY',65)]),
  L([at('Deposits',65)]),
  L([at('POSTING DATE',65),at('DESCRIPTION',145),P('AMOUNT')]),
  L([at('05/06',65),at('DEPOSIT',145),P('500.00')]),
  L([at('Subtotal:',420),P('500.00')]),
  L([at('Electronic Deposits',65)]),
  L([at('POSTING DATE',65),at('DESCRIPTION',145),P('AMOUNT')]),
  L([at('05/12',65),at('eTransfer Credit, Online Xfer',145),P('300.00')]),
  L([at('Other Credits',65)]),
  L([at('POSTING DATE',65),at('DESCRIPTION',145),P('AMOUNT')]),
  L([at('05/13',65),at('WIRE TRANSFER INCOMING',145),P('200.00')]),
  L([I('Checks Paid',65,59),I('No. Checks: 2',145,48),I('*Indicates break in serial sequence or check processed electronically',216,328)]),
  L([I('DATE',65,22),I('SERIAL NO.',137,46),I('AMOUNT',246,35),I('DATE',365,22),I('SERIAL NO.',437,46),I('AMOUNT',546,35)]),
  L([I('05/14',65,25),I('1367',145,22),I('100.00',250,31),I('05/15',370,25),I('1368',450,22),I('50.00',556,26)]),
  L([at('Electronic Payments',65)]),
  L([at('POSTING DATE',65),at('DESCRIPTION',145),P('AMOUNT')]),
  L([at('05/18',65),at('CCD DEBIT, AMEX EPAYMENT ACH PMT',145),P('400.00')]),
  L([at('Other Withdrawals',65)]),
  L([at('POSTING DATE',65),at('DESCRIPTION',145),P('AMOUNT')]),
  L([at('05/20',65),at('WIRE TRANSFER OUTGOING',145),P('200.00')]),
  L([at('05/20',65),at('WIRE TRANSFER FEE',145),P('30.00')]),
  L([at('Service Charges',65)]),
  L([at('POSTING DATE',65),at('DESCRIPTION',145),P('AMOUNT')]),
  L([at('06/03',65),at('MAINTENANCE FEE',145),P('20.00')]),
  L([at('06/03',65),at('PAPER STATEMENT FEE',145),P('3.00')]),
  L([at('DAILY BALANCE SUMMARY',65)]),
  L([at('DATE',65),at('BALANCE',200)]),
  L([at('05/03',65),R(250)('1,000.00')]),
  L([at('06/03',65),R(250)('1,197.00')]) ]}];
var TD=fin(lgParseColumnar(td));
ok('M14 TD Bank layout', TD, { status:'verified', rows:10 });
print((TD.period && TD.period.start==='2026-05-04' && TD.rows.every(function(r){ return /^2026-/.test(r.date); }) ? 'PASS ':'FAIL ')+'M14 period without a comma dates the rows  '+JSON.stringify(TD.period));

// ---- MESSY 15: printout with PENDING TRANSACTIONS / ACCOUNT HISTORY headings (TD Bank online) ----
var p15=[{ lines:[ L([at('Date',50),at('Description',120),at('Amount',380)]),
  L([at('PENDING TRANSACTIONS',50)]),
  L([at('10/1/2026',50),at('VCC DBA NDCC-CO',120),at('-$30,483.45',380)]),
  L([at('ACCOUNT HISTORY',50)]),
  L([at('9/30/2026',50),at('SERVICE CHARGE',120),at('-$3.00',380)]),
  L([at('9/1/2026',50),at('DEPOSIT',120),at('$4,785.78',380)]) ]}];
var P15=fin(lgParsePrintout(p15));
print((P15.rows.length===3 && P15.rows[0].date==='PENDING' && P15.rows[1].date==='2026-09-30' && P15.period && P15.period.end==='2026-09-30' ? 'PASS ':'FAIL ')+'M15 pending heading keeps pending rows out of the period  '+P15.rows.map(function(r){ return r.date; }).join(','));

// ---- MESSY 16: First Security Bank layout (through lgBuild, which picks statement vs printout) ----
// "PREVIOUS STATEMENT BALANCE AS OF ..." summary with PLUS / LESS lines, a "LESS CYCLE SERVICE
// CHARGE" kept out of the debits total, and a Date | Description | Debits | Credits table -- a
// header the printout reader also accepts, so the statement summary has to win the tie.
var Dr=R(420), Cr=R(520);
var fsb={ type:'pdf', name:'fsb.pdf', pages:[{ hasText:true, lines:[
  L([at('Monthly Statement Summary',65),at('ACCOUNT NUMBER 0021160147',300)]),
  L([at('PREVIOUS STATEMENT BALANCE AS OF 06/30/26',65),R(560)('$1,000.00')]),
  L([at('PLUS',65),at('2',100),at('DEPOSITS AND OTHER CREDITS',120),R(560)('$300.00')]),
  L([at('LESS',65),at('2',100),at('CHECKS AND OTHER DEBITS',120),R(560)('$150.00')]),
  L([at('LESS',65),at('CYCLE SERVICE CHARGE',120),R(560)('$16.40')]),
  L([at('CURRENT STATEMENT BALANCE AS OF 07/31/26',65),R(560)('1,133.60')]),
  L([at('Checking Account Transactions',65)]),
  L([at('Date',65),at('Description',120),Dr('Debits'),Cr('Credits')]),
  L([at('07/01',65),at('AC-ATT -PAYMENT',120),Dr('$100.00')]),
  L([at('07/02',65),at('AC-HRTLAND PMT SYS -TXNS/FEES',120),Cr('$200.00')]),
  L([at('07/03',65),at('XFER TO ACCT CK-XXXXXXXX7647',120),Dr('$50.00')]),
  L([at('07/06',65),at('AC-HRTLAND PMT SYS -TXNS/FEES',120),Cr('$100.00')]),
  L([at('07/31',65),at('CYCLE SERVICE CHARGE',120),Dr('$16.40')]) ]}]};
var FSB=lgBuild(fsb);
ok('M16 First Security layout', FSB, { status:'verified', rows:5 });
print((FSB.cls==='statement' && FSB.period && FSB.period.start==='2026-07-01' ? 'PASS ':'FAIL ')+'M16 read as a statement, not a printout  '+FSB.cls+' '+JSON.stringify(FSB.period));

// ---- MESSY 17: Truist layout ----
// Summary "Your previous balance as of ... / Checks - / Other withdrawals, debits and service charges
// - / Deposits, credits and interest + / Your new balance as of ... =" (no period line: the as-of
// dates give it); sentence-case section headings with commas; and a second account (the money
// market) printed after the checking account, which must not be read into this ledger.
var Am=R(400);
var tr=[{ lines:[
  L([at('ACCOUNT NAME',65),at('ACCOUNT NUMBER',250),at('BALANCE($)',380),at('DETAILS ON',450)]),
  L([at('TRUIST SIMPLE BUSINESS CHECKING',65),at('1340008762936',250),Am('1,050.00'),at('page 1',450)]),
  L([at('TRUIST BUSINESS MONEY MARKET',65),at('1340030104411',250),Am('0.58'),at('page 4',450)]),
  L([at('¡ TRUIST SIMPLE BUSINESS CHECKING 1340008762936',65)]),
  L([at('Your previous balance as of 04/30/2026',65),Am('$1,000.00')]),
  L([at('Checks',65),at('-',330),Am('100.00')]),
  L([at('Other withdrawals, debits and service charges',65),at('-',330),Am('50.00')]),
  L([at('Deposits, credits and interest',65),at('+',330),Am('200.00')]),
  L([at('Your new balance as of 05/29/2026',65),at('=',330),Am('$1,050.00')]),
  L([at('Checks',65)]),
  L([at('DATE',65),at('CHECK #',120),P('AMOUNT($)')]),
  L([at('05/05',65),at('1743',120),P('100.00')]),
  L([at('Total checks',300),P('= $100.00')]),
  L([at('Other withdrawals, debits and service charges',65)]),
  L([at('DATE',65),at('DESCRIPT ION',120),P('AMOUNT($)')]),
  L([at('05/01',65),at('DEBIT CARD PURCHASE BONEFISH GRILL',120),P('50.00')]),
  L([at('Total other withdrawals, debits and service charges',120),P('= $50.00')]),
  L([at('Deposits, credits and interest',65)]),
  L([at('DATE',65),at('DESCRIPT ION',120),P('AMOUNT($)')]),
  L([at('05/04',65),at('DEPOSIT',120),P('200.00')]),
  L([at('Total deposits, credits and interest',120),P('= $200.00')]),
  L([at('¡ TRUIST BUSINESS MONEY MARKET 1340030104411',65)]),
  L([at('Your previous balance as of 04/30/2026',65),Am('$290.44')]),
  L([at('Your new balance as of 05/29/2026',65),at('=',330),Am('$0.58')]),
  L([at('Other withdrawals, debits and service charges',65)]),
  L([at('DATE',65),at('DESCRIPT ION',120),P('AMOUNT($)')]),
  L([at('05/18',65),at('TRUIST ONLINE TRANSFER MOBILE TO ****2936',120),P('290.00')]) ]}];
var TR=fin(lgParseColumnar(tr));
ok('M17 Truist layout', TR, { status:'verified', rows:3 });
print((TR.account==='1340008762936' && TR.period && TR.period.start==='2026-05-01' && TR.period.end==='2026-05-29' && /second account .*4411/.test(TR.note||'') ? 'PASS ':'FAIL ')+'M17 account, period from as-of dates, second account left out  '+TR.account+' '+JSON.stringify(TR.period)+' '+TR.note);

// ---- MESSY 18: FNB of Hartford layout ----
// Dated "Beginning Balance" / "Ending Balance" lines give the period (first and last day); totals as
// "2 Credit(s) This Period"; a combined activity table with running balances whose descriptions
// are printed centred on the date line (one line above, one below); and a "Checks Cleared" list
// plus a check-image index that only repeat activity rows.
var Db=R(420), Cb=R(500), Bb=R(580);
var fnb=[{ lines:[
  L([at('Business Low Vol - XXXXXX4463 Account Summary',65)]),
  L([at('Date',65),at('Description',140),R(560)('Amount')]),
  L([at('05/30/2026',65),at('Beginning Balance',140),R(560)('$1,000.00')]),
  L([at('2',100),at('Credit(s) This Period',140),R(560)('$600.00')]),
  L([at('2',100),at('Debit(s) This Period',140),R(560)('$350.00')]),
  L([at('06/30/2026',65),at('Ending Balance',140),R(560)('$1,250.00')]),
  L([at('Account Activity',65)]),
  L([at('Post Date',65),at('Description',140),Db('Debits'),Cb('Credits'),Bb('Balance')]),
  L([at('05/30/2026',65),at('Beginning Balance',140),Bb('$1,000.00')]),
  L([at('400876268 ONLINE BANKING TRANSFER FROM Business',140)]),
  L([at('06/01/2026',65),Cb('$400.00'),Bb('$1,400.00')]),
  L([at('Low Vol 424269 ON 5/30/26',140)]),
  L([at('834290 PURCHASE-PIN DISNEY PLUS RECU BURBANK',140)]),
  L([at('06/01/2026',65),Db('$50.00'),Bb('$1,350.00')]),
  L([at('CA 00001000 834290',140)]),
  L([at('06/10/2026',65),at('CHECK # 1153',140),Db('$300.00'),Bb('$1,050.00')]),
  L([at('06/15/2026',65),at('DEPOSIT',140),Cb('$200.00'),Bb('$1,250.00')]),
  L([at('06/30/2026',65),at('Ending Balance',140),Bb('$1,250.00')]),
  L([at('Checks Cleared',65)]),
  L([at('1153',80),at('06/10/2026',140),R(260)('$300.00')]),
  L([at('#0000',65),at('06/15/2026',140),R(260)('$200.00')]) ]}];
var FN=fin(lgParseColumnar(fnb));
ok('M18 FNB of Hartford layout', FN, { status:'verified', rows:4 });
print((FN.period && FN.period.start==='2026-05-30' && FN.period.end==='2026-06-30' && /repeat/.test(FN.note||'') &&
  /^400876268 ONLINE BANKING TRANSFER FROM Business Low Vol/.test(FN.rows[0].desc) && /^834290 PURCHASE-PIN DISNEY .*CA 00001000/.test(FN.rows[1].desc) ? 'PASS ':'FAIL ')+
  'M18 period from dated balances, recap not counted, centred descriptions  '+JSON.stringify(FN.period)+' | '+FN.rows.slice(0,2).map(function(r){ return r.desc; }).join(' | '));

// ---- MESSY 19: balance lines read inside a summary block never become summary sections ----
// (BofA prints a second column of statistics beside them, and pdf.js joins that line's text with no
// space -- "$29,948.96# of deposits/credits: 25" -- so they reach the summary-block reader)
function LT(text, items){ var l=L(items); l.text=text; return l; }
var sb=[{ lines:[
  L([at('August 1, 2026 through August 31, 2026',300)]),
  L([at('Account summary',65)]),
  LT('Beginning balance on August 1, 2026 $1,000.00# of deposits/credits: 1', [at('Beginning balance on August 1, 2026',36),R(300)('$1,000.00'),at('# of deposits/credits: 1',364)]),
  L([at('Deposits and other credits',65),R(300)('100.00'),at('# of withdrawals/debits: 1',350)]),
  L([at('Withdrawals and other debits',65),R(300)('-40.00')]),
  LT('Ending balance on August 31, 2026 $1,060.00¹Includes checks paid', [at('Ending balance on August 31, 2026',36),R(300)('$1,060.00'),at('¹Includes checks paid',364)]),
  L([at('Deposits and other credits',65)]),
  L([at('Date',65),at('Description',140),A('Amount')]),
  L([at('08/05/26',65),at('DEPOSIT',140),A('100.00')]),
  L([at('Withdrawals and other debits',65)]),
  L([at('Date',65),at('Description',140),A('Amount')]),
  L([at('08/06/26',65),at('CARD PURCHASE',140),A('-40.00')]) ]}];
var SB=fin(lgParseColumnar(sb));
ok('M19 summary balance lines stay balances', SB, { status:'verified', rows:2 });
print((!SB.summary.sections.beg && !SB.summary.sections.end ? 'PASS ':'FAIL ')+'M19 no beg/end summary sections  '+Object.keys(SB.summary.sections).join(','));

// ---- MESSY 20: Chase statement printed in Spanish ----
// Chase's hidden "*start*..." markers name each section in English; the visible headings are
// Spanish and printed one run per word ("RETIROS" | "DE" | "CAJEROS" ...) with a barcode glued on.
function W(phrase, x){ var out=[], xx=x; phrase.split(' ').forEach(function(w){ out.push(I(w, xx, w.length*5)); xx+=w.length*5+3; }); return out; }
var es=[{ lines:[
  L([at('Agosto 01, 2026 a Agosto 31, 2026',300)]),
  L([at('P O Box 44959 Número De Cuenta: 000000687062565',300)]),
  L([at('*start*summary',40)]),
  L(W('RESUMEN DE CUENTA DE CHEQUES',42)),
  L(W('Saldo inicial',40).concat([R(380)('-$1,000.00')])),
  L(W('Depósitos y Adiciones',40).concat([at('1',249),R(380)('500.00')])),
  L(W('Retiros de cajeros automáticos y',40).concat([at('1',249),R(380)('-20.00')])),
  L(W('compras con tarjeta de débito',40)),
  L(W('Cargos',40).concat([at('1',249),R(380)('-15.00')])),
  L(W('Saldo final',40).concat([at('3',244),R(380)('-$535.00')])),
  L([at('*end*summary',40)]),
  L([at('*start*deposits and additions',40)]),
  L(W('DEPÓSITOS Y ADICIONES',40)),
  L(W('FECHA',40).concat(W('DESCRIPCIÓN',90),[A('CANTIDAD')])),
  L([at('08/04',40),at('DepÓsito. Deposit 1390140463',90),A('$500.00')]),
  L([at('Total de depósitos y adiciones',40),A('$500.00')]),
  L([at('*end*deposits and additions',40)]),
  L([at('*start*atm debit withdrawal',40)]),
  L(W('RETIROS DE CAJEROS AUTOMÁTICOS Y COMPRAS CON TARJETA DE DÉBITO10759370402000000064',40)),
  L(W('FECHA',40).concat(W('DESCRIPCIÓN',90),[A('CANTIDAD')])),
  L([at('08/05',40),at('Compra con tarjeta. Card purchase 08/05 wal-mart phoenix AZ card',90),A('20.00')]),
  L([at('*end*atm debit withdrawal',40)]),
  L([at('*start*fees section',40)]),
  L(W('CARGOS',40)),
  L([at('08/31',40),at('Cargo mensual por servicio',90),A('15.00')]),
  L([at('*end*fees section',40)]),
  L([at('*start*daily ending balance2 SALDO FINAL DIARIO FECHA CANTIDAD',40)]),
  L([at('08/04',40),R(200)('-$500.00'),at('08/05',260),R(420)('-520.00'),at('08/31',460),R(600)('-535.00')]),
  L([at('*end*daily ending balance2',40)]) ]}];
var ES=fin(lgParseColumnar(es));
ok('M20 Chase in Spanish', ES, { status:'verified', rows:3 });
print((ES.account && ES.account.slice(-4)==='2565' && ES.period && ES.period.start==='2026-08-01' && ES.rows.filter(function(r){ return r.section==='atm'; }).length===1 ? 'PASS ':'FAIL ')+'M20 account, period, card purchases under atm  '+ES.account+' '+JSON.stringify(ES.period)+' '+ES.rows.map(function(r){ return r.section; }).join(','));

// ---- MESSY 23: HSBC online export ("Statement details") ----
// Bank reference | Customer reference | TRN type | TRN status | Value date | Credit amount | Debit amount |
// Balance | Time | Post date, newest first, each label at the start of its cell and each figure ending
// just short of the next label (a credit's right edge sits under "Debit amount"); day-first dates;
// a "Narrative" line under each row; the header repeated on page 2, which opens with the tail of a
// narrative; the range's "Closing ledger balance brought forward" next to a later "Current ledger balance".
function hsbc(fromDate, closing){
  var head=L([at('Bank reference',31),at('Customer reference',110),at('TRN type',188),at('TRN status',266),at('Value date',345),at('Credit amount',423),at('Debit amount',502),at('Balance',580),at('Time',658),at('Post date',737)]);
  var row=function(ref, cust, type, date, cred, deb, bal){ var it=[at(ref,31),at(cust,110),at(type,188),at('Posted',266),at(date,345)]; if(cred) it.push(R(497)(cred)); if(deb) it.push(R(576)(deb)); it.push(R(654)(bal), at('15:51',658), at(date,737)); return L(it); };
  return [{ hasText:true, lines:[
    L([at('Statement details',128)]),
    L([at('Account name',34),at('AC NA - Operating',139),at('Closing ledger balance brought forward',416),at(closing,765)]),
    LT('Account number 199108714From'+fromDate, [at('Account number',34),at('199108714',139),at('From',416),at(fromDate,445)]),   // pdf.js joins this line without spaces
    L([at('Current ledger balance',416),at('13,892.23',761)]),
    L([at('As at',416),at('03 Aug 2026 08:17',445)]),
    L([at('Specified date range',416),at('01 Jul 2026 to 31 Jul 2026',707)]),
    head,
    row('212528158','Jun rent','921','31 Jul 2026',null,'-12,668.65','9,830.20'),
    L([at('Narrative',32),at('OUTGOING MONEY TRANSFER, 57SEND FED MANUFACTURERS TRADERS TRUST CO',82)]),
    row('212526968','INTERCO LOAN','540','31 Jul 2026','7,000.00',null,'22,498.85'),
    L([at('Narrative',32),at('BOOK TRANSFER CREDIT, 41BOOK CREDIT ACTIONCOACH',82)]),
    L([at('03 Aug 2026',31),at('Account number 199108714',60),at('Page',743),at('1',766),at('of',779),at('2',794)]) ]},
   { hasText:true, lines:[
    L([at('Statement details',128)]),
    head,
    L([at('Narrative',32),at('FOREIGN REMITTANCE DEBIT, 38SEND CHIP',82)]),
    row('212522721','BizX 2026','921','30 Jul 2026',null,'-31,062.50','15,498.85'),
    L([at('Narrative',32),at('OUTGOING MONEY TRANSFER, 57SEND FED BANK OF AMERICA',82)]),
    L([at('03 Aug 2026',31),at('Account number 199108714',60),at('Page',743),at('2',766),at('of',779),at('2',794)]) ]}];
}
var HS=lgBuild({ type:'pdf', name:'hsbc.pdf', pages:hsbc('31 Jul 2026','9,830.20') });
ok('M23 HSBC export', HS, { status:'verified', rows:3 });
print((HS.cls==='printout' && HS.rows.filter(function(r){ return r.kind==='credit'; }).length===1 && HS.rows[1].cents===700000 && HS.period && HS.period.start==='2026-07-30' && HS.account && /8714$/.test(HS.account)
  && HS.checks.some(function(c){ return c.check==='header balance ties to rows' && c.result==='pass'; }) ? 'PASS ':'FAIL ')+'M23 credit placed by cell, day-first dates, closing balance tied  '+HS.rows.map(function(r){ return r.date+' '+r.signed; }).join(', ')+' | '+JSON.stringify(HS.checks.map(function(c){ return c.result; })));
var HS2=lgBuild({ type:'pdf', name:'hsbc-aug.pdf', pages:hsbc('02 Aug 2026','11,967.12') });
print((HS2.status==='verified' && HS2.checks.some(function(c){ return c.check==='header balance ties to rows' && c.result==='untestable'; }) ? 'PASS ':'FAIL ')+'M23 closing balance dated after the range is not compared  '+HS2.status+' '+JSON.stringify(HS2.checks.map(function(c){ return c.check+':'+c.result; })));
// another balance's "From" line printed first is not the closing balance's date
var hp=hsbc('02 Aug 2026','11,967.12'); hp[0].lines.splice(1, 0, L([at('Opening ledger balance',416),at('22,000.00',765)]), L([at('Account type',34),at('Checking',139),at('From',416),at('01 Jul 2026',445)]));
var HS3=lgBuild({ type:'pdf', name:'hsbc-aug2.pdf', pages:hp });
print((HS3.checks.some(function(c){ return c.check==='header balance ties to rows' && c.result==='untestable'; }) ? 'PASS ':'FAIL ')+'M23 closing balance dated by its own From line  '+HS3.status+' '+JSON.stringify(HS3.checks.map(function(c){ return c.check+':'+c.result; })));

// ---- MESSY 24: DecisionLogic bank-data report (a lender's account-verification printout) ----
// Per account: a "Summary" (Account Number, Current Balance, Deposits/Credits, Withdrawals/Debits), then
// "Date | Codes | Description | Category | Amount | Balance" newest first with a running balance; labels
// start their cells; the font's "ti" ligature comes through as NUL; "(PENDING)" leads a pending row's
// description; a "Calendar View" of monthly totals ends the table; the next account follows in the file.
var DLm=R(535), DLb=R(586);
var DLhead=L([at('Date',26),at('Codes',77),at('Descrip\u0000on',129),at('Category',385),at('Amount',503),at('Balance',555)]);
var DL=lgBuild({ type:'pdf', name:'BankReport.pdf', pages:[{ hasText:true, lines:[
  L([at('DecisionLogic Bank Statement',29),at('WDVMJ4',521)]),
  L([at('Summary',24),at('Test Auto',507)]),
  L([at('Account Name',51),at('Test Auto',120),at('Account Number',323),at('237041146246',402)]),
  L([at('Available Balance',40),at('$50.00',120),at('As of Date',352),at('8/3/2026',402)]),
  L([at('Current Balance',46),at('$100.00',120),at('Average Balance',326),at('$80.00',402)]),
  L([at('Deposits/Credits',42),at('$70.00',120),at('Avg Bal Latest Mo',318),at('$80.00',402)]),
  L([at('Withdrawals/Debits',27),at('($85.00)',120),at('Workflow',354),at('New',402)]),
  L([at('Transac\u0000ons',26),at('8/1/2026 - 8/3/2026',504)]),
  DLhead,
  L([at('8/3/2026',26),at('ad',77),at('(PENDING) ACH HOLD SRG CAP ON 08/03',129),at('Other Expenses',385),DLm('($50.00)'),DLb('$100.00')]),
  L([at('8/3/2026',26),at('McKenzie Capital DES:Payment',129),at('INDN:A',329),at('Loan',385),DLm('($20.00)'),DLb('$100.00')]),
  L([at('Miracles Auto LLC CO ID:XXXXX61018 CCD',129)]),
  L([at('8/2/2026',26),at('dp',77),at('MOBILE DEPOSIT',129),at('Deposit',385),DLm('$70.00'),DLb('$120.00')]),
  L([at('8/1/2026',26),at('rq',77),at('PURCHASE 1001 RING',129),at('Home Improvement/',385),DLm('($10.00)'),DLb('$50.00')]),
  L([at('CA XXXXX0962 RECURRING',129),at('Maintenance',385)]),
  L([at('8/1/2026',26),at('SHELL OIL Microso\u0000',129),at('Automo\u0000ve Expense',385),DLm('($5.00)'),DLb('$60.00')]),
  L([at('Calendar View',26)]),
  L([at('Month',26),at('Avg Balance',86),at('Days Over',149),at('NSFs',227),at('Deposits',269),at('Withdrawals',310),at('Loan Debits',369),at('Loan Credits',423),at('Begin Bal',492),at('End Bal',556)]),
  L([at('Aug 2026',26),at('$80.00',94),at('0',187),at('0',243),at('$70.00',268),at('($85.00)',315),at('1',412),at('0',469),at('$65.00',505),at('$100.00',556)]),
  L([at('Summary',24),at('Business Adv Fundamentals',507)]),
  L([at('Account Name',51),at('Business Adv Fundamentals',120),at('Account Number',323),at('237056724417',402)]),
  L([at('Current Balance',46),at('$40.00',120)]),
  DLhead,
  L([at('8/2/2026',26),at('wd',77),at('WIRE TYPE:WIRE OUT',129),at('Transfers',385),DLm('($980.00)'),DLb('$40.00')]) ]}] });
ok('M24 DecisionLogic report', DL, { status:'verified', rows:5 });
var DLr=DL.rows||[], DLc=function(n){ return (DL.checks||[]).filter(function(c){ return c.check===n; })[0]||{}; };
print((DL.cls==='printout' && DLr[0].date==='PENDING' && /^McKenzie Capital DES:Payment INDN:A Miracles/.test(DLr[1].desc) && DLr[1].type==='Loan' && DLr[3].type==='Home Improvement/Maintenance'
  && DLr[4].type==='Automotive Expense' && /Microsoft$/.test(DLr[4].desc) && /^\*\*\*\*6246$/.test(DL.account) && /\.\.\.4417/.test(DL.note||'') ? 'PASS ':'FAIL ')
  +'M24 pending, long description, wrapped category, ligatures, first account only  '+DL.account+' | '+DL.note+' | '+DLr.map(function(r){ return r.date+' '+r.signed+' ['+r.type+'] '+r.desc; }).join(' / '));
print((DLc('header totals tie to rows').result==='pass' && DLc('monthly totals vs the report\'s calendar').result==='pass' && DLc('header balance ties to rows').result==='pass'
  && DL.viewMeta.requested && DL.viewMeta.requested.start==='2026-08-01' ? 'PASS ':'FAIL ')+'M24 report totals, calendar and current balance tie  '+JSON.stringify((DL.checks||[]).map(function(c){ return c.check+':'+c.result+' '+c.detail; })));

// ---- MESSY 25: Pinnacle Bank (pnfp.com) "Statement of Account" ----
// The summary box prints each balance under its label ("Balance 9/01/26" / "-$1,650.44"; the closing label
// shares its line with "Interest +$0.00") and one figure per direction ("Credits", "Debits"); page 2 is the
// blank back of page 1 (only its page number), with the credits running on after it; the Debits figure
// covers both "Other Debits" and "Checks"; a figure under a dollar prints without its zero (".75").
var PNm=R(569);
var PN=lgBuild({ type:'pdf', name:'Pinnacle.pdf', pages:[
  { hasText:true, lines:[
    L([at('XXXXXXXX8960',407)]),
    L([at('Statement of Account',70),at('Horizon 75',520)]),
    L([at('Balance 9/01/26',92),at('Summary',245)]),
    L([at('-$100.00',92)]),
    L([at('Credits',245),at('+$51.50',289)]),
    L([at('Balance 9/30/26',92),at('Interest +$0.00',245)]),
    L([at('Debits',245),at('-$40.75',289)]),
    L([at('-$89.25',92)]),
    L([at('Credit Transactions',70)]),
    L([at('Credits',70)]),
    L([at('9/01',70),at('CANAL - SUCCESS TRANSFER 4270465600 LITTLE PAPER',95),R(380)('0.51')]),
    L([at('KIDS',95)]),
    L([at('Page 1 of 4',526)]) ]},
  { hasText:true, lines:[ L([at('Page 2 of 4',526)]) ]},
  { hasText:true, lines:[
    L([at('Account Number: XXXXXXXX8960',35)]),
    L([at('9/02',43),at('STRIPE TRANSFER ST-X6Y7C5E4P7G7 1800948598 DANIELLE AMMON',90),PNm('50.99')]),
    L([at('Total Credits',43),R(569)('$51.50')]),
    L([at('Debit Transactions',43)]),
    L([at('Other Debits',43)]),
    L([at('9/02',43),at('Bill.com ACCTVERIFY 016QRMRDK49KCWK',90),PNm('.75')]),
    L([at('9/03',43),at('Paid Item Fee',90),PNm('30.00')]),
    L([at('Page 3 of 4',526)]) ]},
  { hasText:true, lines:[
    L([at('Account Number: XXXXXXXX8960',35)]),
    L([at('Checks',43)]),
    L([at('9/04',43),at('Check 1075',90),PNm('10.00')]),
    L([at('(*) Indicates gap in check number sequenece',43)]),
    L([at('Total Debits',43),R(569)('$40.75')]),
    L([at('Daily Balance Information',43)]),
    L([at('Date',43),at('Balance',177),at('Date',223),at('Balance',357)]),
    L([at('9/01',43),at('-99.49',174),at('9/03',223),at('-79.25',357)]),
    L([at('9/02',43),at('-49.25',174),at('9/04',223),at('-89.25',357)]),
    L([at('Page 4 of 4',526)]) ]} ] });
ok('M25 Pinnacle statement', PN, { status:'verified', rows:5 });
var PNc=function(n){ return (PN.checks||[]).filter(function(c){ return c.check===n; })[0]||{}; };
print((PN.period && PN.period.start==='2026-09-01' && PN.period.end==='2026-09-30' && PN.summary.beginning===-10000 && PN.summary.ending===-8925
  && PN.rows.filter(function(r){ return r.section==='dep'; }).length===2 && PN.rows.some(function(r){ return r.cents===75 && r.kind==='debit'; })
  && PNc('total debits vs summary').result==='pass' && PNc('beginning + credits - debits = ending').result==='pass' && PNc('daily roll-forward vs printed daily ending balance').result==='pass' ? 'PASS ':'FAIL ')
  +'M25 balances under their labels, credits across a blank page, checks inside Debits, ".75"  '+JSON.stringify(PN.period)+' '+PN.summary.beginning+'/'+PN.summary.ending+' '+JSON.stringify((PN.checks||[]).map(function(c){ return c.check+':'+c.result+' '+c.detail; })));

// ---- MESSY 26: Citadel Credit Union ----
// "ACCOUNT #" with the member number under it; an ACCOUNT SUMMARY; a savings share holding $1.00 with no
// activity, then the checking share's own "DATE | DESCRIPTION | DEPOSIT | WITHDRAWAL | BALANCE" table, its
// heading repeated "(Continued)" on later pages; dated BEGINNING / ENDING BALANCE lines; control totals
// "n DEPOSITS = $x   n WITHDRAWALS = $-y"; a cleared-check register repeating a check already listed.
var CTh=L([at('DATE',40),at('DESCRIPTION',97),at('DEPOSIT',366),at('WITHDRAWAL',428),at('BALANCE',534)]);
var CTd=R(406), CTw=R(490), CTb=R(576);
var CT=lgBuild({ type:'pdf', name:'Citadel.pdf', pages:[
  { hasText:true, lines:[
    L([at('ACCOUNT #',425),at('PAGE',546)]),
    L([at('0000994346',426),at('1 of 2',548)]),
    L([at('STATEMENT PERIOD',380),at('07/01/2026 to 07/31/2026',482)]),
    L([at('ACCOUNT SUMMARY',40)]),
    L([at('ACCOUNT TYPE',86),at('BALANCES',475)]),
    L([at('SAVINGS',86),R(525)('1.00')]),
    L([at('CHECKING',86),R(525)('1,500.00')]),
    L([at('TOTAL DEPOSITS',86),R(525)('$1,501.00')]),
    L([at('BUSINESS STAR SAVINGS - 0000',40),at('0.00',212)]),
    CTh,
    L([at('07/01/2026',40),at('BEGINNING BALANCE',97),CTb('$1.00')]),
    L([at('07/31/2026',40),at('ENDING BALANCE',97),CTb('$1.00')]),
    L([at('ELITE BUSINESS CHECKING - 0070',40),at('0.00',222)]),
    CTh,
    L([at('07/01/2026',40),at('BEGINNING BALANCE',97),CTb('$1,000.00')]),
    L([at('07/01/2026',40),at('Withdrawal Paper Stmt Fee',97),CTw('-2.00'),CTb('998.00')]),
    L([at('07/01/2026',40),at('Deposit ACH MERCHANT BANKCD',97),CTd('702.00'),CTb('1,700.00')]),
    L([at('TYPE: DEPOSIT CO: MERCHANT BANKCD',97)]) ]},
  { hasText:true, lines:[
    L([at('ACCOUNT #',297),at('STATEMENT PERIOD',392),at('PAGE',534)]),
    L([at('A',40),at('0000994346',298),at('07/01/2026 to 07/31/2026',386),at('2 of 2',536)]),
    L([at('ELITE BUSINESS CHECKING - 0070 (Continued)',40)]),
    CTh,
    L([at('07/20/2026',40),at('Check 1055',97),CTw('-200.00'),CTb('1,500.00')]),
    L([at('07/31/2026',40),at('ENDING BALANCE',97),CTb('$1,500.00')]),
    L([at('1 DEPOSIT = $702.00',106),at('2 WITHDRAWALS = $-202.00',237)]),
    L([at('Cleared Check Summary',58)]),
    L([at('Number',54),at('Date',107),at('Amount',165)]),
    L([at('1055',54),at('07-20',106),at('200.00',166)]) ]} ] });
ok('M26 Citadel statement', CT, { status:'verified', rows:3 });
print((CT.account==='0000994346' && CT.summary.beginning===100000 && CT.summary.ending===150000 && CT.summary.aggregate && CT.summary.aggregate.debit.count===2
  && (CT.checks||[]).filter(function(c){ return /vs summary|= ending/.test(c.check) && c.result==='pass'; }).length===3 ? 'PASS ':'FAIL ')
  +'M26 checking share read past the empty savings share, control totals with counts  '+CT.account+' '+CT.summary.beginning+'/'+CT.summary.ending+' '+JSON.stringify((CT.checks||[]).map(function(c){ return c.check+':'+c.result+' '+c.detail; })));

// ---- MESSY 27: United Bank ----
// The ConnectOne layout as a text PDF: a "Balance Summary" ("- Checks Posted (2)"), a page with only
// its mail-room footer, then a "Checks Posted" register (date, number, amount, across) on a page of its
// own ahead of Debits that list each check again ("CHECK 6570"); a 2D barcode's rows ("AKFPDIBK...") and
// the sheet's sequence number ("7151 0036637 0002-0010 ...") down the left margin share lines with
// headings and rows; "Balance By Date"; captions under the check images.
var UBw=R(558), UBd=R(558);
var UB=lgBuild({ type:'pdf', name:'United.pdf', pages:[
  { hasText:true, lines:[
    L([at('Account Number:',367),at('XXXXXX7077',509)]),
    L([at('Statement Date:',367),at('05/31/2026',520)]),
    L([at('FREE BUSINESS CHECKING',54),at('Account Number:',365),at('3107077',522)]),
    L([at('Balance Summary',58)]),
    L([at('Beginning Balance as of 05/01/26',58),R(563)('-$100.00')]),
    L([at('+ Deposits and Credits (2)',69),R(563)('$500.00')]),
    L([at('- Checks Posted (2)',72),R(563)('$150.00')]),
    L([at('- Withdrawals and Debits (1)',72),R(563)('$36.00')]),
    L([at('Ending Balance as of 05/31/26',58),R(563)('$214.00')]),
    L([at('3870 0036635 0001-0010 W18493REG05302603480 02 L 7151',288)]) ]},
  { hasText:true, lines:[ L([at('3870 0036636 0000-0010 W18493REG05302603480 02 L 7151',288)]) ]},
  { hasText:true, lines:[
    L([at('7151 0036637 0002-0010 0000000000000000',11),at('Checks Posted',58)]),
    L([at('Date',58),at('Check#',109),at('Amount',179),at('Date',231),at('Check#',282),at('Amount',352)]),
    L([at('May 04',58),at('6570R',127),R(213)('$100.00'),at('May 27',231),at('0',316),R(386)('$50.00')]),
    L([at('Debits',58)]),
    L([at('Date',58),at('Description',101),at('Withdrawals',503)]),
    L([at('May 04',58),at('CHECK 6570',101),UBw('-$100.00')]),
    L([at('May 04',58),at('NSF RETURN ITEM FEE',101),UBw('-$36.00')]),
    L([at('FOR RETURN OF CHECK #',101),at('6570',249)]),
    L([at('AKFPDIBKHLGPBMEOEPANEMDK',18),at('AFMEPCHGBPHNPLHOLKGPKPJK',18),at('May 27',58),at('CHECK',101),UBw('-$50.00')]),
    L([at('ALHMGINOKMIGBGGAHOLPKCOK',18),at('Credits',58)]),
    L([at('Date',58),at('Description',101),at('Deposits',520)]),
    L([at('May 04',58),at('NSF RETURNED ITEM',101),UBd('$100.00')]),
    L([at('CHECK 6570',101)]),
    L([at('May 22',58),at('ACH DEPOSIT',101),UBd('$400.00')]) ]},
  { hasText:true, lines:[
    L([at('7151 0036642 0007-0010 0000000000000000',11),at('Balance By Date',58)]),
    L([at('Date',58),at('Balance',179),at('Date',231),at('Balance',352)]),
    L([at('Apr 30',58),R(213)('-$100.00'),at('May 22',231),R(386)('$264.00')]),
    L([at('May 04',58),R(213)('-$136.00'),at('May 27',231),R(386)('$214.00')]) ]},
  { hasText:true, lines:[
    L([at('Check Images for Account',220),at('3107077',374)]),
    L([at('05/22/2026',61),R(310)('$400.00'),at('05/04/2026',324),at('# 6570',418),R(570)('$100.00')]) ]} ] });
ok('M27 United Bank statement', UB, { status:'verified', rows:5, unclaimed:0 });
var UBc=function(n){ return (UB.checks||[]).filter(function(c){ return c.check===n; }); };
print((UB.rows.filter(function(r){ return r.section==='chk'; }).length===2 && UB.rows.every(function(r){ return !/[A-P]{12}/.test(r.desc); })
  && UBc('section total vs summary').length===3 && UBc('section total vs summary').every(function(c){ return c.result==='pass'; })
  && UBc('daily roll-forward vs printed daily ending balance').every(function(c){ return c.result==='pass'; }) ? 'PASS ':'FAIL ')
  +'M27 margin barcodes dropped, check register not counted again, check-image captions not flagged  '+JSON.stringify((UB.checks||[]).map(function(c){ return c.check+':'+c.result+' '+c.detail; })));
// the next month's statement opens its "Balance By Date" with the day before its period, after an
// overdraft fee dated that day that only it lists: May keeps its own May 31, the fee falls in June
var UB2=lgBuild({ type:'pdf', name:'United-Jun.pdf', pages:[
  { hasText:true, lines:[
    L([at('Account Number:',367),at('XXXXXX7077',509)]),
    L([at('Statement Date:',367),at('06/30/2026',520)]),
    L([at('Balance Summary',58)]),
    L([at('Beginning Balance as of 06/01/26',58),R(563)('$214.00')]),
    L([at('+ Deposits and Credits (1)',69),R(563)('$100.00')]),
    L([at('- Withdrawals and Debits (1)',72),R(563)('$36.00')]),
    L([at('Ending Balance as of 06/30/26',58),R(563)('$278.00')]),
    L([at('Debits',58)]),
    L([at('Date',58),at('Description',101),at('Withdrawals',503)]),
    L([at('May 31',58),at('OVERDRAFT FEE',101),UBw('-$36.00')]),
    L([at('Credits',58)]),
    L([at('Date',58),at('Description',101),at('Deposits',520)]),
    L([at('Jun 15',58),at('DEPOSIT',101),UBd('$100.00')]),
    L([at('Balance By Date',58)]),
    L([at('Date',58),at('Balance',179),at('Date',231),at('Balance',352)]),
    L([at('May 31',58),R(213)('$178.00'),at('Jun 15',231),R(386)('$278.00')]) ]} ] });
var UBC=lgComputed([{ name:'United.pdf', _ledger:UB }, { name:'United-Jun.pdf', _ledger:UB2 }])[0]||{};
var UBm=function(m){ return (UBC.months||[]).filter(function(x){ return x.month===m; })[0]||{}; };
print((UB2.status==='verified' && UBm('2026-05').adb===-1155 && UBm('2026-06').adb===23133 ? 'PASS ':'FAIL ')
  +'M27 average balance: the next statement\'s figure for the day before its period does not replace this one\'s  '+UB2.status+' '+UBm('2026-05').adb+' '+UBm('2026-06').adb);

// ---- MESSY 28: First Community Bank, scanned ----
// "Previous Balance / 49 Deposits/Credits / 251 Checks/Debits / Current Balance"; "Deposits and
// Additions", then the debits' table under a heading the scan lost (printed on a shaded band): only the
// column header comes round again, and its figures carry a trailing minus; on the next page the heading
// reads "Chax ana y"; "Checks in Number Order" reads "Checka in Hi", so only the register's own header
// ("Date Check No | Amount Date Check No | Amount") names it; a date and check number read as one cell.
var FCh=L([at('Date',64),at('Description',121),at('Amount',380)]), FCa=R(420);
var FC=lgBuild({ type:'pdf', name:'FirstCommunity.pdf', pages:[
  { hasText:true, lines:[
    L([at('COMMUNITY COMMERCIAL CHECKING',61),at('Number of Enclosures',310),at('3',519)]),
    L([at('Account Number',62),at('Acct Ending 6098',195),at('Statement Dates',309),at('7/01/26 thru',408),at('8/02/26',483)]),
    L([at('Previous Balance',61),R(290)('1,000.00'),at('Days in the statement period',305),at('33',520)]),
    L([at('2 Deposits/Credits',77),R(290)('500.00')]),
    L([at('4 Checks/Debits',72),R(290)('362.12')]),
    L([at('Service Charge',61),R(290)('.00')]),
    L([at('Interest Paid',61),R(290)('.00')]),
    L([at('Current Balance',61),R(290)('1,137.88')]),
    L([at('Deposits and Additions',50)]),
    FCh,
    L([at('7/01',67),at('Customer Deposit',116),FCa('400.00')]),
    L([at('7/31',66),at('DEPOSIT',118),at('MERCHANT BANKCD',178),FCa('100.00')]),
    L([at('THE BIG PIG OF SPARTA',118)]),
    FCh,
    L([at('7/01',66),at('DISCOUNT',117),at('MERCHANT BANKCD',181),FCa('7.12-')]),
    L([at('THE BIG PIG OF SPARTA',117)]) ]},
  { hasText:true, lines:[
    L([at('COMMUNITY COMMERCIAL CHECKING',54),at('Acct Ending 6098 (Continued)',249)]),
    L([at('Chax',43),at('ana y',83)]),
    FCh,
    L([at('7/06',61),at('MOBILE PMT CAPITAL ONE',113),FCa('300.00-')]),
    L([at('Checka in Hi',45)]),
    L([at('Date Check No',50),at('Amount Date Check No',174),at('Amount',329)]),
    L([at('7/01',61),at('3110',125),R(280)('50.00')]) ]},
  { hasText:true, lines:[
    L([at('COMMUNITY COMMERCIAL CHECKING',62),at('Acct Ending 6098 (Continued)',255)]),
    L([at('Date Check No',62),at('Amount',264)]),
    L([at('7/02 9999931124*',68),R(280)('5.00')]),
    L([at('* Denotes missing check numbers',61)]) ]} ] });
ok('M28 First Community Bank scan', FC, { status:'verified', rows:6, unclaimed:0 });
var FCs=function(k){ return FC.rows.filter(function(r){ return r.section===k; }).length; };
print((FCs('dep')===2 && FCs('wd')===2 && FCs('chk')===2 && FC.rows.some(function(r){ return r.section==='chk' && r.cents===500 && /9999931124/.test(r.desc); }) ? 'PASS ':'FAIL ')
  +'M28 debits under a lost heading, a check register known by its header, date and number in one cell  '+JSON.stringify(FC.rows.map(function(r){ return r.section+' '+r.cents+' '+r.desc; })));
