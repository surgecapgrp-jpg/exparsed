// Layouts from the "test files for exparsed" set (2026-10-18). Synthetic lines, made-up names and
// figures, shaped like each bank's real pages. Runs after fixtures.js (uses its L / at / R / I / ok).

// ---- D1: Huntington -- one total per direction with its breakdown indented under it, a statistics
// column on the left, "(+)" / "(-)" after the headings, deposits two across, the service charges and
// their waivers in a fee list, "Balance Activity" for the daily balances ----
var HU=lgBuild({ type:'pdf', name:'huntington.pdf', pages:[{ hasText:true, lines:[
  L([at('Huntington Business Checking 100',46),at('Account: -------1234',345)]),
  L([at('Statement Activity From:',46),at('Beginning Balance',226),R(440)('$1,000.00')]),
  L([at('09/01/26 to 09/30/26',46),at('Credits (+)',226),R(440)('600.00')]),
  L([at('Regular Deposits',238),R(440)('100.00')]),
  L([at('Days in Statement Period',46),at('30',199),at('Other Credits',238),R(440)('500.00')]),
  L([at('Average Ledger Balance*',46),R(220)('1,150.00'),at('Debits (-)',226),R(440)('300.00')]),
  L([at('Other Debits',238),R(440)('300.00')]),
  L([at('Total Service Charges (-)',226),R(440)('10.00')]),
  L([at('Ending Balance',226),R(440)('$1,290.00')]),
  L([at('Deposits (+)',46),at('Account:-------1234',474)]),
  L([at('Date',46),at('Amount',116),at('Serial #',178),at('Type',244),at('Date',322),at('Amount',392),at('Serial #',454),at('Type',520)]),
  L([at('09/03',46),R(150)('60.00'),at('111',178),at('Remote',244),at('09/03',322),R(430)('40.00'),at('222',454),at('Remote',520)]),
  L([at('Other Credits (+)',46),at('Account:-------1234',474)]),
  L([at('Date',46),at('Amount',122),at('Description',178)]),
  L([at('09/05',46),R(160)('500.00'),at('INCOMING WIRE',178)]),
  L([at('Other Debits (-)',46),at('Account:-------1234',474)]),
  L([at('Date',46),at('Amount',122),at('Description',178)]),
  L([at('09/10',46),R(160)('300.00'),at('OUTGOING WIRE',178)]),
  L([at('Service Charge Detail',46),at('Account:-------1234',474)]),
  L([at('Date',46),at('Service Charge (-)',87),at('Waives and',186),at('Discounts (+)',243),at('Description',322)]),
  L([at('09/15',46),R(177)('15.00'),at('MONTHLY SERVICE FEE',322)]),
  L([at('09/15',46),R(308)('5.00'),at('SERVICE FEE WAIVER',322)]),
  L([at('Balance Activity',46),at('Account:-------1234',474)]),
  L([at('Date',46),at('Balance',177),at('Date',226),at('Balance',357)]),
  L([at('09/03',46),R(210)('1,100.00'),at('09/10',226),R(390)('1,300.00')]),
  L([at('09/05',46),R(210)('1,600.00'),at('09/15',226),R(390)('1,290.00')]),
  L([at('Statement Period from 09/01/26 to 09/30/26',356),at('Page 1 of 1',518)]) ]}] });
ok('D1 Huntington nested summary, fee waivers, deposits two across', HU, { status:'verified', rows:6, unclaimed:0 });
print((HU.rows.filter(function(r){ return r.section==='fee' && r.kind==='credit' && r.cents===500; }).length===1 ? 'PASS ':'FAIL ')+'D1 the waiver in the fee list is a credit');

// ---- D2: Navy Federal -- each debit's "-" a run of its own, a row whose figures wrap onto the next
// line, a description holding "Debit" and "Checkout" (not a column header), "Items Paid" repeating the
// debits, and the member's savings account after the checking account ----
var NFm=function(s){ return I(s, 472-s.length*4.5, s.length*4.5); }, NFd=I('-',472,3);
var NF=lgBuild({ type:'pdf', name:'navyfed.pdf', pages:[{ hasText:true, lines:[
  L([at('Statement Period',411)]), L([at('02/01/26 - 02/28/26',407)]),
  L([at('Business Checking - 7199126330',14)]),
  L([at('Date',14),at('Transaction Detail',43),at('Amount($)',432),at('Balance($)',557)]),
  L([at('02-01',14),at('Beginning Balance',43),R(600)('1,000.00')]),
  L([at('02-02',14),at('POS Debit- Business Debit Card 7584 01-30-26 Shop Checkout.Fast',43)]),
  L([at('SC',43),NFm('15.00'),NFd,R(600)('985.00')]),
  L([at('02-03',14),at('Deposit',43),NFm('100.00'),R(600)('1,085.00')]),
  L([at('02-04',14),at('Wire Fee',43),NFm('20.00'),NFd,R(600)('1,065.00')]),
  L([at('02-28',14),at('Ending Balance',43),R(600)('1,065.00')]),
  L([at('Items Paid',14)]),
  L([at('Date',18),at('Item',140),at('Amount($)',226),at('Date',317),at('Item',439),at('Amount($)',525)]),
  L([at('02-02',18),at('POS',155),R(270)('15.00'),at('02-04',317),at('POS',454),R(570)('20.00')]),
  L([at('Mbr Business Savings - 3229534023',14)]),
  L([at('Date',14),at('Transaction Detail',43),at('Amount($)',432),at('Balance($)',557)]),
  L([at('02-01',14),at('Beginning Balance',43),R(600)('5.00')]),
  L([at('02-15',14),at('Dividend',43),NFm('0.01'),R(600)('5.01')]) ]}] });
ok('D2 Navy Federal separate minus, wrapped row, Items Paid, second account', NF, { status:'verified', rows:3, unclaimed:0 });

// ---- D3: Valley National -- a two-line column title ("Withdrawals &" / "Other Debits") and "CHECKS
// IN ORDER" repeating the checks the transactions list, its heading behind a mail-sort code ----
var VA=lgBuild({ type:'pdf', name:'valley.pdf', pages:[{ hasText:true, lines:[
  L([at('SUMMARY FOR THE PERIOD: 01/01/26 - 01/31/26',54)]),
  L([at('Beginning Balance',78),at('Deposits & Other Credits',202),at('Withdrawals & Other Debits',339),at('Ending Balance',503)]),
  L([R(130)('$1,000.00'),R(290)('$500.00'),R(420)('$300.00'),R(560)('$1,200.00')]),
  L([at('TRANSACTIONS',54)]),
  L([at('Withdrawals &',334),at('Deposits &',440)]),
  L([at('Date',54),at('Description',97),at('Other Debits',340),at('Other Credits',431),at('Balance',554)]),
  L([at('Beginning Balance',97),R(589)('$1,000.00')]),
  L([at('01/02',54),at('CHECK 1445',97),R(400)('-$300.00'),R(589)('$700.00')]),
  L([at('01/06',54),at('DEPOSIT',97),R(496)('$500.00'),R(589)('$1,200.00')]),
  L([I('47821 0213344 0009-0014 47821',11,120),at('CHECKS IN ORDER',54)]),
  L([at('Date',54),at('Number',180),at('Amount',277),at('Date',320),at('Number',446),at('Amount',544)]),
  L([at('01/02',54),at('1445',189),R(310)('$300.00')]) ]}] });
ok('D3 Valley two-line column title, checks list repeating the transactions', VA, { status:'verified', rows:2, unclaimed:0 });

// ---- D4: Suncoast -- a savings share with rows of its own printed before the checking share ----
var SCh=L([at('Post Date',59),at('Eff Date',117),at('Transaction Description',162),at('Amount',486),at('New Balance',536)]);
var SC=lgBuild({ type:'pdf', name:'suncoast.pdf', pages:[{ hasText:true, lines:[
  L([at('Member Number: XXXXXX2954',54),at('09/01/2026 - 09/30/2026',190)]),
  L([at('BUSINESS REGULAR SAVINGS Suffix 0000',54)]),
  SCh,
  L([at('09/01/2026',57),at('Balance Forward',162),R(590)('6.09')]),
  L([at('09/22/2026',57),at('09/22/2026 Deposit ACH',111),R(520)('1,500.00'),R(590)('1,506.09')]),
  L([at('09/22/2026',57),at('09/22/2026 Withdrawal Transfer To Share 0050',111),R(520)('-1,501.09'),R(590)('5.00')]),
  L([at('BUSINESS SMART CHECKING Suffix 0050',54)]),
  SCh,
  L([at('09/01/2026',57),at('Balance Forward',162),R(590)('1,000.00')]),
  L([at('09/22/2026',57),at('09/22/2026 Deposit Transfer From Share 0000',111),R(520)('1,501.09'),R(590)('2,501.09')]),
  L([at('09/25/2026',57),at('09/25/2026 Withdrawal ACH',111),R(520)('-200.00'),R(590)('2,301.09')]) ]}] });
ok('D4 Suncoast savings share ahead of the checking share', SC, { status:'verified', rows:2 });
print((/savings share \(0000\)/.test(SC.note||'') && SC.rows.every(function(r){ return r.cents!==150000; }) ? 'PASS ':'FAIL ')+'D4 the savings share\'s rows are left out and named in the note  '+SC.note);

// ---- D5: Community 1st CU -- mail-sort text printed down the left margin ahead of row dates ----
var C1=lgBuild({ type:'pdf', name:'c1st.pdf', pages:[{ hasText:true, lines:[
  L([at('Statement For: 08/01/2026 - 08/31/2026',360)]),
  L([at('Beginning Balance',427),R(560)('$1,000.00')]),
  L([at('Ending Balance',439),R(560)('$925.00')]),
  L([at('Date',36),at('Transaction Description',65),at('Amount',473),at('Balance',541)]),
  L([I('3/37',12,13),at('08/03',35),at('Withdrawal ACH',65),R(505)('-100.00'),R(573)('900.00')]),
  L([I('UNQ',12,15),at('08/04',35),at('Deposit ACH',65),R(505)('50.00'),R(573)('950.00')]),
  L([I('353023279',12,40),at('08/05',35),at('Withdrawal Fee',65),R(505)('-25.00'),R(573)('925.00')]) ]}] });
ok('D5 margin marks before row dates', C1, { status:'verified', rows:3, unclaimed:0 });

// ---- D6: M&T online activity -- figures clipped at the cell edge, the last digit on the line below ----
var MT=lgBuild({ type:'pdf', name:'mt-activity.pdf', pages:[{ hasText:true, lines:[
  L([at('Business Checking ...7539  Account Activity  Available Balance $841.17',56)]),
  L([at('9/25/2026',56),at('PAYEE A',113),I('–$636.59',301,38),I('$841.17',437,33)]),
  L([at('9/24/2026',56),at('PAYEE B',113),I('–$88.7',299,40),I('$1,477.76',429,40)]),
  L([at('9/24/2026',56),at('PAYEE C',113),I('–$2,609.5',299,40),I('1',334,5),I('$1,566.47',429,40)]),
  L([at('9/24/2026',56),at('PAYEE D',113),I('–$115.05',301,38),I('9',334,5),I('$4,176.06',424,45)]),
  L([at('9/23/2026',56),at('DEPOSIT',113),I('$4,422.75',364,40),I('$4,291.11',424,45)]) ]}] });
ok('D6 clipped figures get their last digit back', MT, { status:'verified', rows:5 });
print((MT.rows.some(function(r){ return r.cents===8871; }) && MT.rows.some(function(r){ return r.cents===260959; }) ? 'PASS ':'FAIL ')+'D6 $88.71 and $2,609.59 read whole');

// ---- D7: First Merchants -- one summary line for the debits covers two sections (debits and checks) ----
var FM=lgBuild({ type:'pdf', name:'firstmerchants.pdf', pages:[{ hasText:true, lines:[
  L([at('For Statement Period',335),at('09/01/2026 to 09/30/2026',451)]),
  L([at('BALANCE SUMMARY',54)]),
  L([at('Beginning Balance as of 09/01/2026',54),R(290)('$1,000.00')]),
  L([at('+ Deposits and Credits (1)',68),R(290)('$500.00')]),
  L([at('- Withdrawals and Debits (2)',68),R(290)('$300.00')]),
  L([at('Ending Balance as of 09/30/2026',54),R(290)('$1,200.00')]),
  L([at('MISCELLANEOUS CREDITS',54)]),
  L([at('Date',54),at('Description',89),at('Deposits',523)]),
  L([at('Sep 01',54),at('REMOTE DEPOSIT',89),R(570)('500.00')]),
  L([at('MISCELLANEOUS DEBITS',54)]),
  L([at('Date',54),at('Description',89),at('Withdrawals',500)]),
  L([at('Sep 10',54),at('ACH PAYMENT',89),R(570)('200.00')]),
  L([at('CHECKS PAID',54)]),
  L([at('Check No',54),at('Date',120),at('Amount',300)]),
  L([at('1001',54),at('Sep 12',120),R(330)('100.00')]) ]}] });
ok('D7 a direction\'s one summary line covers its debits and checks', FM, { status:'verified', rows:3, unclaimed:0 });
print(((FM.checks||[]).some(function(c){ return c.result==='pass' && /covers sections wd \+ chk/.test(c.detail||''); }) ? 'PASS ':'FAIL ')+'D7 checked as the direction total');

// ---- D8: Global Federal CU -- each heading prints its count and total in brackets after a colon,
// one unsigned Amount column, and the withdrawals heading and column header sit at the foot of page 1
// with every one of its rows on page 2 ----
var GF=lgBuild({ type:'pdf', name:'globalfcu.pdf', pages:[{ hasText:true, lines:[
  L([at('STATEMENT PERIOD FROM 09-01-26 THROUGH 09-30-26',300)]),
  L([at('DEPOSITS/OTHER CREDITS: (1 TOTALING 500.00)',40)]),
  L([at('Effective',40),at('Posted',95),at('DESCRIPTION',150),at('AMOUNT',520)]),
  L([at('09-02',40),at('09-02',95),at('DEPOSIT TRANSFER FROM SHARE 10',150),R(560)('500.00')]),
  L([at('OTHER WITHDRAWALS/DEBITS: (2 TOTALING 300.00)',40)]),
  L([at('Effective',40),at('Posted',95),at('DESCRIPTION',150),at('AMOUNT',520)]) ]},
 { hasText:true, lines:[
  L([at('BUSINESS CHEK - 70 (CONTINUED)',40)]),
  L([at('Effective',40),at('Posted',95),at('DESCRIPTION',150),at('AMOUNT',520)]),
  L([at('09-10',40),at('09-10',95),at('WITHDRAWAL DEBIT CARD PURCHASE',150),R(560)('200.00')]),
  L([at('09-12',40),at('09-12',95),at('WITHDRAWAL MAINTENANCE FEE',150),R(560)('100.00')]),
  L([at('CHECKING SUMMARY:',40)]),
  L([at('PREVIOUS BALANCE',40),R(400)('1,000.00')]),
  L([at('NEW BALANCE',40),R(400)('1,200.00')]) ]}] });
ok('D8 bracketed count/total headings, withdrawals heading at the foot of a page', GF, { status:'verified', rows:3 });
print((GF.rows.filter(function(r){ return r.section==='wd' && r.signed<0; }).length===2 ? 'PASS ':'FAIL ')+'D8 the page-2 rows are withdrawals');
