import sys
HW={c:556 for c in '0123456789$'}; HW.update({',':278,'.':278,'-':333,' ':278})
def width(s,size): return sum(HW.get(c,600) for c in s)*size/1000
def esc(s): return s.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
def pdf(path, pages, font='Helvetica'):
    objs=[]
    def add(o): objs.append(o); return len(objs)
    fid=add('<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>'%font)
    kids=[]; pages_id_placeholder=len(objs)+1+2*len(pages)
    content_ids=[]
    for pg in pages:
        ops=['BT /F1 9 Tf']
        for (x,y,s,align) in pg:
            if align=='r': x=x-width(s,9)
            ops.append('1 0 0 1 %.2f %.2f Tm (%s) Tj'%(x,y,esc(s)))
        ops.append('ET'); data='\n'.join(ops)
        content_ids.append(add('<< /Length %d >>\nstream\n%s\nendstream'%(len(data),data)))
    pages_id=len(objs)+len(pages)+1
    for cid in content_ids:
        kids.append(add('<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'%(pages_id,fid,cid)))
    assert add('<< /Type /Pages /Kids [%s] /Count %d >>'%(' '.join('%d 0 R'%k for k in kids),len(kids)))==pages_id
    cat=add('<< /Type /Catalog /Pages %d 0 R >>'%pages_id)
    out=b'%PDF-1.4\n'; offs=[]
    for i,o in enumerate(objs):
        offs.append(len(out)); out+=('%d 0 obj\n%s\nendobj\n'%(i+1,o)).encode('latin-1')
    x=len(out); out+=('xref\n0 %d\n0000000000 65535 f \n'%(len(objs)+1)).encode()
    for o in offs: out+=('%010d 00000 n \n'%o).encode()
    out+=('trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n'%(len(objs)+1,cat,x)).encode()
    open(path,'wb').write(out)
def page(rows, top=740, step=14):
    out=[]; y=top
    for r in rows:
        for cell in r: out.append((cell[0],y,cell[1],cell[2] if len(cell)>2 else 'l'))
        y-=step
    return out
d=sys.argv[1]
# A: credit union, combined table, no heading, numeric period, continues on page 2 with no heading
W,Dp,B=400,480,560
pdf(d+'/cu-combined.pdf',[ page([
  [(50,'Lakeside Community Credit Union')],[(50,'Statement Period: 01/01/2026 - 01/31/2026')],[(50,'Member Number 0000123456')],[],
  [(50,'Share Draft Checking')],
  [(50,'Date'),(110,'Description'),(W,'Withdrawals','r'),(Dp,'Deposits','r'),(B,'Balance','r')],
  [(50,'01/01/2026'),(110,'Beginning Balance'),(B,'1,000.00','r')],
  [(50,'01/05/2026'),(110,'Deposit Shared Branch'),(Dp,'2500.00','r'),(B,'3,500.00','r')],
  [(50,'01/06/2026'),(110,'POS Purchase Starbucks #1234'),(W,'25.00','r'),(B,'3,475.00','r')],
  [(50,'01/09/2026'),(110,'ACH Debit Acme Funding LLC'),(W,'1,500.00','r'),(B,'1,975.00','r')],
  [(450,'Page 1 of 2')] ]),
  page([
  [(50,'Date'),(110,'Description'),(W,'Withdrawals','r'),(Dp,'Deposits','r'),(B,'Balance','r')],
  [(50,'01/16/2026'),(110,'ACH Credit Stripe Payout'),(Dp,'812.40','r'),(B,'2,787.40','r')],
  [(50,'01/20/2026'),(110,'Check 1001'),(W,'300.00','r'),(B,'2,487.40','r')],
  [(50,'01/31/2026'),(110,'Ending Balance'),(B,'2,487.40','r')],
  [(450,'Page 2 of 2')] ]) ])
# B: Chase-style sectioned statement (regression)
A=500
pdf(d+'/chase-style.pdf',[ page([
  [(300,'January 01, 2026 through January 31, 2026')],[(300,'Account Number: 000000123456789')],
  [(50,'CHECKING SUMMARY')],[(50,'Beginning Balance'),(A,'$1,000.00','r')],[(50,'Deposits and Additions'),(300,'2'),(A,'300.00','r')],
  [(50,'Checks Paid'),(300,'1'),(A,'50.00','r')],[(50,'Ending Balance'),(A,'$1,250.00','r')],
  [(50,'DEPOSITS AND ADDITIONS')],[(50,'DATE'),(100,'DESCRIPTION'),(A,'AMOUNT','r')],
  [(50,'01/05'),(100,'Deposit'),(A,'100.00','r')],[(50,'01/12'),(100,'ACH Credit Stripe Transfer'),(A,'200.00','r')],
  [(50,'Total Deposits and Additions'),(A,'$300.00','r')],
  [(50,'CHECKS PAID')],[(50,'CHECK NO.'),(120,'DESCRIPTION'),(380,'DATE PAID'),(A,'AMOUNT','r')],
  [(50,'1001'),(80,'^'),(380,'01/15'),(A,'50.00','r')],[(50,'Total Checks Paid'),(A,'$50.00','r')],
  [(50,'DAILY ENDING BALANCE')],[(50,'DATE'),(120,'AMOUNT'),(250,'DATE'),(320,'AMOUNT')],
  [(50,'01/05'),(120,'1,100.00'),(250,'01/12'),(320,'1,300.00')],[(50,'01/15'),(120,'1,250.00')] ]) ])
# C: line-printer style: every line one run, columns made with spaces (Courier)
rows=['STATEMENT PERIOD 01/01/26 THRU 01/31/26','',
 'DATE      DESCRIPTION                    WITHDRAWALS     DEPOSITS      BALANCE',
 '01/01/26  BALANCE FORWARD                                              1,000.00',
 '01/05/26  DEPOSIT                                          250.00      1,250.00',
 '01/06/26  POS PURCHASE STARBUCKS             25.00                     1,225.00',
 '01/31/26  ENDING BALANCE                                               1,225.00']
pdf(d+'/line-printer.pdf',[ [(40,740-i*12,r,'l') for i,r in enumerate(rows) if r] ], font='Courier')
print('ok')
