// Mac OCR (Apple Vision via mac_ocr_server.py): page JSON -> lines, the repairs made to its
// readings, and the scanned layouts it first made readable (ConnectOne Bank, Chase in Spanish).
function t(name, cond, info){ print((cond?'PASS ':'FAIL ')+name+(info?'  '+info:'')); }
// A Vision line at PDF point coordinates (2 px per point on a 792 pt page), split into words the way
// the helper reports them: word boxes spread along the line in proportion to their length.
function V(text, x, y, w, alt){
  var px=2, top=(792-y)*px-10, h=20, words=[], ws=text.split(' '), at=x*px, per=w*px/Math.max(1,text.length);
  ws.forEach(function(wd){ words.push({ t:wd, x:at, y:top, w:wd.length*per, h:h }); at+=(wd.length+1)*per; });
  var l={ t:text, x:x*px, y:top, w:w*px, h:h, words:words }; if(alt) l.a=alt; return l;
}
function page(lines){ return visionToPage({ w:1224, h:1584, lines:lines }, 2, 792); }
function texts(p){ return p.lines.map(function(l){ return l.text; }); }
function verify(pages){ var L=lgParseColumnar(pages); if(L.rows && L.rows.length) lgFinalize(L); return L; }
function why(L){ return L.status+' '+(L.rows||[]).length+' rows; '+(L.checks||[]).filter(function(c){ return c.result!=='pass'; }).map(function(c){ return c.check+': '+c.detail; }).join(' | '); }

// ---- the page: rows in reading order, an amount inside a joined line becomes its own cell
var p1=page([V('-$60.00', 520, 700, 30), V('Aug 03 ATM WITHDRAWAL', 56, 700, 120), V('CASH WITHDRAWAL TERMINAL 7E007362', 100, 690, 160), V('Aug 06 CHECK 3267 -$1,980.00', 56, 680, 480)]);
t('Vision lines -> rows top first', texts(p1)[0]==='Aug 03 ATM WITHDRAWAL -$60.00' && texts(p1)[1]==='CASH WITHDRAWAL TERMINAL 7E007362', JSON.stringify(texts(p1)));
var last=p1.lines[2].items; t('amount split out of a joined line', last.length===2 && last[1].s==='-$1,980.00' && last[1].x>last[0].x+20, JSON.stringify(last));
// ---- a page turned upright by the helper comes back with width and height swapped
var turned=visionToPage({ w:1584, h:1224, lines:[{ t:'TOP', x:10, y:0, w:30, h:20 }] }, 2, 792);
t('turned page keeps the top line at the top', Math.abs(turned.lines[0].y-(612-5))<1, turned.lines[0].y);
// ---- two clean readings that disagree: the date that keeps the column in order wins
var p2=page([V('Aug 27 CHECK 3277', 56, 500, 100), V('Aug 21 CHECK 3281', 56, 488, 100, 'Aug 27 CHECK 3281'), V('Aug 27 PREAUTHORIZED WD', 56, 476, 130)]);
t('alternate date picked by column order', texts(p2)[1]==='Aug 27 CHECK 3281', texts(p2)[1]);
var p2b=page([V('Aug 20 CHECK 3277', 56, 500, 100), V('Aug 21 CHECK 3281', 56, 488, 100, 'Aug 27 CHECK 3281'), V('Aug 27 PREAUTHORIZED WD', 56, 476, 130)]);
t('in-order reading kept', texts(p2b)[1]==='Aug 21 CHECK 3281', texts(p2b)[1]);
// ---- a month misread by one letter, and a digit read as a slash
var p3=page([V('May 08 CHECK 3228', 56, 500, 100), V('Vay 08 PREAUTHORIZED WD', 56, 488, 130), V('May 08 OVERDRAFT FEE', 56, 476, 120)]);
t('one-letter month repaired from its column', texts(p3)[1]==='May 08 PREAUTHORIZED WD', texts(p3)[1]);
var p3b=page([V('Vay 08 PREAUTHORIZED WD', 56, 488, 130), V('Jul 08 OVERDRAFT FEE', 56, 476, 120)]);
t('no repair when the column month does not fit', texts(p3b)[0]==='Vay 08 PREAUTHORIZED WD', texts(p3b)[0]);
var p4=page([V('07/31', 36, 500, 22), V('0//31', 36, 488, 22), V('07/31', 36, 476, 22)]);
t('numeric date with a slash for a digit repaired', texts(p4)[1]==='07/31', texts(p4)[1]);
var p4b=page([V('10/02 Deposit', 56, 500, 100), V('1023 10/05', 56, 488, 60), V('$500.00', 480, 488, 40)]);
t('check number leading its row is not taken for a date', /^1023 /.test(texts(p4b)[1]), texts(p4b)[1]);
// four digits whose middle "1" is the slash ("7127" among 7/27 rows -- First Community Bank's scan); a
// check number leading a dated row keeps its digits
var p4c=page([V('7/27 MOBILE PMT CAPITAL ONE 600.00-', 56, 500, 300), V('7127 FINCL ADJ MERCHANT BANKCD 363.95-', 56, 488, 300), V('7/27 PURCHASE Sysco 1,577.94-', 56, 476, 300)]);
t('date with its slash read as 1 repaired', /^7\/27 FINCL/.test(texts(p4c)[1]), texts(p4c)[1]);
var p4d=page([V('1/02 Deposit', 56, 500, 100), V('1123 1/05', 56, 488, 60), V('$500.00', 480, 488, 40)]);
t('check number 1123 before a date stays a check number', /^1123 1\/05/.test(texts(p4d)[1]), texts(p4d)[1]);
var p4c=page([V('05/14 Fee', 56, 500, 80), V('Day 15 thing', 56, 488, 80)]);
t('no month repair from a numeric date', texts(p4c)[1]==='Day 15 thing', texts(p4c)[1]);
var p4d=page([V('Aug 30 WIRE', 56, 500, 60, 'Aug 20 WIRE'), V('Aug 28 ACH', 56, 488, 60), V('Aug 27 ACH', 56, 476, 60)]);
t('newest-first column keeps its first date', texts(p4d)[0]==='Aug 30 WIRE', texts(p4d)[0]);
var p4e=page([V('Aug 06 CHECK 3267 1234.56', 56, 480, 480)]).lines[0].items;
t('amount without a thousands comma split out', p4e.length===2 && p4e[1].s==='1234.56', JSON.stringify(p4e.map(function(i){ return i.s; })));
var p4f=page([V('Transfer from x7084 to x6655', 106, 480, 190), V('900 .00', 412, 480, 41)]).lines[0].items;
t('figure split at its decimal point read whole', p4f.length===2 && p4f[1].s==='900.00', JSON.stringify(p4f.map(function(i){ return i.s; })));
// ---- padded boxes that overlap are not glued into one word
var p5=page([V('06/16', 33, 450, 30), V('06/16 retiro. Withdrawal', 59.6, 450, 111), V('$21,916.23', 488, 450, 48)]);
t('overlapping boxes stay separate cells', /^06\/16 06\/16 retiro/.test(lgCleanLine(p5.lines[0]).text), lgCleanLine(p5.lines[0]).text);

// ---- M21: a ConnectOne Bank scan (Balance Summary with signs and bracketed counts, a Checks Posted
// register, checks listed inside Debits, a footer code under the last row, negative ending balance,
// a fee dated the day before the period that the bank's daily table opens with)
var c1=page([
  V('Account Number: XXXXXX3443', 360, 760, 160),
  V('Balance Summary', 56, 500, 90),
  V('Beginning Balance as of 08/01/26', 57, 477, 170), V('$1,000.00', 515, 477, 45),
  V('+ Deposits and Credits (2)', 68, 463, 130), V('$700.00', 520, 463, 40),
  V('- Checks Posted (1)', 69, 448, 100), V('$200.00', 520, 448, 40),
  V('- Withdrawals and Debits (2)', 69, 434, 140), V('$1,640.00', 515, 434, 45),
  V('Ending Balance as of 08/31/26', 57, 419, 160), V('-$140.00', 518, 419, 42),
  V('Checks Posted', 58, 361, 80),
  V('Date', 58, 328, 25), V('Check#', 113, 328, 40), V('Amount', 178, 328, 40),
  V('Aug 05', 56, 316, 35), V('3267', 125, 316, 25), V('$200.00', 172, 316, 40),
  V('Debits', 58, 250, 40),
  V('Date', 58, 225, 25), V('Description', 100, 225, 60), V('Withdrawals', 500, 225, 60),
  V('Aug 03', 56, 213, 35), V('PREAUTHORIZED WD', 100, 213, 90), V('-$1,600.00', 510, 213, 50),
  V('VALLEY BANK BILL PAY 260803', 100, 203, 150),
  V('Aug 05', 56, 191, 35), V('CHECK 3267', 100, 191, 55), V('-$200.00', 518, 191, 42),
  V('8962 0320049 0001-0010 M8852REG090126072134 07 L 86351', 100, 10, 300)]);
var c2=page([
  V('Debits (Continued)', 56, 642, 100),
  V('Date', 58, 624, 25), V('Description', 100, 624, 60), V('Withdrawals', 500, 624, 60),
  V('Jul 31', 56, 612, 32), V('OVERDRAFT FEE', 100, 612, 75), V('-$40.00', 525, 612, 35),
  V('Credits', 58, 508, 40),
  V('Date', 58, 482, 25), V('Description', 101, 482, 60), V('Deposits', 518, 482, 42),
  V('Aug 04', 56, 471, 35), V('PREAUTHORIZED CREDIT', 100, 471, 110), V('$500.00', 520, 471, 40),
  V('Aug 10', 56, 425, 35), V('DEPOSIT', 101, 425, 45), V('$200.00', 520, 425, 40),
  V('Balance By Date', 56, 300, 90),
  V('Date', 58, 290, 25), V('Balance', 178, 290, 40), V('Date', 229, 290, 25), V('Balance', 349, 290, 40),
  V('Jul 31', 56, 278, 32), V('$960.00', 170, 278, 40), V('Aug 05', 229, 278, 35), V('-$340.00', 339, 278, 45),
  V('Aug 03', 56, 266, 35), V('-$640.00', 166, 266, 45), V('Aug 10', 229, 266, 35), V('-$140.00', 339, 266, 45),
  V('Aug 04', 56, 254, 35), V('-$140.00', 166, 254, 45)]);
var C=verify([c1, c2]);
t('M21 ConnectOne scan verified', C.status==='verified' && C.rows.length===5, why(C));
t('M21 period from the as-of balance lines', C.period && C.period.start==='2026-08-01' && C.period.end==='2026-08-31', JSON.stringify(C.period));
t('M21 check inside Debits counted as a check', C.rows.filter(function(r){ return r.section==='chk'; }).length===1, C.rows.map(function(r){ return r.section+':'+r.desc; }).join(', '));
t('M21 footer code not taken into a description', !C.rows.some(function(r){ return /M8852/.test(r.desc); }));
t('M21 register line not reported unread', !(C.unclaimed||[]).some(function(u){ return /3267 \$200/.test(u.text); }), JSON.stringify(C.unclaimed));

// ---- M22: Chase printed in Spanish, scanned (no hidden section markers): the summary heading beside
// the product name, the 62-character card heading with "(continuación)", padded boxes that overlap
var s1=page([
  V('Julio 01, 2026 a Julio 31, 2026', 388, 740, 150),
  V('Número De Cuenta: 000000687062565', 362, 725, 170),
  V('RESUMEN DE CUENTA DE CHEQUES', 43, 501, 252), V('Chase Business Complete Checking', 308, 501, 153),
  V('Saldo inicial', 39, 464, 57), V('-$100.00', 333, 464, 40),
  V('Depósitos y Adiciones', 40, 450, 95), V('1', 249, 450, 5), V('500.00', 332, 450, 35),
  V('Retiros de cajeros automáticos y', 40, 424, 140), V('1', 249, 424, 5), V('-50.00', 333, 424, 30),
  V('compras con tarjeta de débito', 39, 414, 130),
  V('Saldo final', 39, 361, 50), V('2', 244, 361, 5), V('$350.00', 333, 361, 40),
  V('DEPÓSITOS Y ADICIONES', 36, 300, 120),
  V('FECHA', 36, 285, 30), V('DESCRIPCIÓN', 86, 285, 60), V('CANTIDAD', 499, 285, 40),
  V('07/07', 36, 274, 25), V('Depósito. Deposit', 86, 274, 80), V('$500.00', 495, 274, 42),
  V('Total de depósitos y adiciones', 36, 262, 130), V('$500.00', 495, 262, 42)]);
var s2=page([
  V('RETIROS DE CAJEROS AUTOMÁTICOS Y COMPRAS CON TARJETA DE DÉBITO', 38, 691, 420), V('(continuación)', 472, 691, 60),
  V('FECHA', 36, 669, 30), V('DESCRIPCIÓN', 71, 669, 60), V('CANTIDAD', 499, 669, 40),
  V('07/16', 33, 657, 30), V('07/16 compra. Card purchase', 59.6, 657, 120), V('50.00', 512, 657, 25),
  V('Total de retiros de cajeros automáticos y compras con tarjeta de débito', 36, 640, 300), V('$50.00', 497, 640, 40)]);
var S=verify([s1, s2]);
t('M22 Chase Spanish scan verified', S.status==='verified' && S.rows.length===2, why(S));
t('M22 card purchase in its own section', S.rows.some(function(r){ return r.section==='atm' && r.cents===5000; }), S.rows.map(function(r){ return r.section+':'+r.cents; }).join(', '));

// ---- more OCR slips, from Mac OCR read over every test statement
var p6=page([V('09/02/26/', 36, 555, 37), V('WIRE TYPE:WIRE IN DATE: 260902', 89, 555, 290), V('1,666.00', 541, 555, 36)]);
t('stray mark after a date dropped', /^09\/02\/26 WIRE/.test(texts(p6)[0]), texts(p6)[0]);
var p7=page([V('Depos i ts and Additions', 28, 238, 121)]);
t('letter-spaced word rejoined', texts(p7)[0]==='Deposits and Additions', texts(p7)[0]);
t('lone "Deposit" label is not a heading', lgSectionOf('Deposit')===null && lgSectionOf('DEPOSIT')!==null && lgSectionOf('Deposits').key==='dep');
var p8=page([V('Jul', 19, 165, 14), V('2 Electronic Withdrawal', 40, 165, 104), V('To ELITEPAYBUSINESS', 206, 165, 103), V('10.00-', 561, 165, 30)]);
t('day joined to the text after it split off', p8.lines[0].items[1].s==='2' && p8.lines[0].items[2].s==='Electronic Withdrawal', JSON.stringify(p8.lines[0].items.map(function(i){ return i.s; })));
