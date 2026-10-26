# exparsed tests

Run after any change to `exparsed.html`:

```bash
tests/run.sh            # macOS (JavaScriptCore)
node tests/run-node.js  # anywhere with node
```

It cuts the parsing functions out of `exparsed.html` (no build step, no node — it uses macOS's
built-in JavaScriptCore) and runs:

| File | What it covers |
|---|---|
| `fixtures.js` | Chase-style regressions (sectioned statement, printout, OCR) plus 13 messy layouts: combined tables, one-run lines, per-glyph text, signed / unsigned Amount columns, page carry-over, no-comma and CR/DR amounts, Title Case OCR, oldest-first printouts, the "partial" status, unread lines, a TD Bank layout (M14), a printout with PENDING TRANSACTIONS / ACCOUNT HISTORY headings (M15), a First Security Bank layout read through `lgBuild` (M16), a Truist layout with a second account in the same file (M17), an FNB of Hartford layout (M18), balance lines in a summary block whose text pdf.js joins without a space (M19), a Chase statement printed in Spanish (M20) |
| `desktop.js` | layouts from the Desktop "test files for exparsed" set (synthetic lines): Huntington's nested summary, fee waivers and two-across deposits (D1), Navy Federal's separate minus runs, wrapped rows and "Items Paid" repeat (D2), Valley National's two-line column title and "CHECKS IN ORDER" repeat (D3), a savings share ahead of the checking share (D4), left-margin mail-sort marks (D5), clipped figures in an online printout (D6), one summary line covering debits and checks (D7) |
| `edge.js` | whole-page syntax check, sections that must not carry over a page, Title Case footers, real errors still caught, ambiguous directions flagged, JSON transactions, export → re-import |
| `formats.js` | CSV (preamble, debit/credit columns, headerless), account-number formats, OCR page numbering, broken-text detection (including icon-font glyphs that are not broken text), Markdown table layout and re-reading it, statement-period formats, Spanish headings / summary labels / account label / period |
| `macocr.js` | Mac OCR page JSON → lines (amounts split out of joined lines, turned pages), the repairs made to its readings (alternate date by column order, one-letter month, slash-for-digit date, padded boxes that overlap), a ConnectOne Bank scan (M21) and a scanned Chase statement in Spanish (M22) |
| `analytics.js` | computed figures (arithmetic only, no labels): a CSV / printout with no account number joins an account when its opening balance equals a statement's ending balance to the cent (and its oldest day then counts as complete); month gross inflows / outflows as plain sums; the printed average balance checked over the statement period; the printed NSF/returned-fee itemization read and passed through as printed |

Payee grouping (`lgFamily`), credit-source flags, cadence / LIVE tests and fee detection were removed from the page: those are labels, applied by the LLM step downstream. Their old tests are in `families.js.removed`.

## Browser-only checks

OFX needs the browser's XML parser and Excel needs SheetJS, so those run in the page: drop the
files in `samples/` (plus any `.xlsx` bank export). Expected: `chase-export.csv`, the three PDFs
and an Excel export with a balance column show **✓ reconciled**; `quicken.qfx` and
`wells-export.csv` show **rows unverified** (OFX carries no opening balance and that CSV no balance
column, so there is nothing to check the rows against). `samples/make-sample-pdfs.py` rebuilds the PDFs.

## Real statements

`../test-statements/alliance/` — Bank of America business checking ...4860, June–September 2026
(real customer data; delete when no longer needed). Expected in the page, all four:
**✓ reconciled**, and in the Integrity report every check PASS:

| Month | Rows | Deposits | Withdrawals | Checks | Fees | Ending |
|---|---|---|---|---|---|---|
| June | 178 | $154,396.52 (24) | $164,694.99 | $0.00 | $0.00 | $14,163.56 |
| July | 191 | $266,776.55 (30) | $238,371.15 | $12,620.00 (5) | $0.00 | $29,948.96 |
| August | 167 | $271,286.74 (25) | $244,635.45 | $21,283.00 (8) | $229.64 | $35,087.61 |
| September | 116 | $110,096.91 (21) | $139,074.26 | $1,100.00 (1) | $4.04 | $5,006.22 |

Cross-file: periods contiguous, each ending balance = next beginning balance, account last-4 4860
on all four. The version before the ledger fixes read these as online printouts and could verify
none of them ("rows unverified").

`../test-statements/batch3/` — Simmons Bank (Affiliated Hotel ...6655 May–Jul, ...7084 May–Jul + Sep,
"Transaction history" printout) and one other bank (docViewDownload, ...6324). Expected: all nine
text PDFs **✓ reconciled**. scan0558/0560/0565/0569 are image-only and are not bank statements (AIA G702 /
G703 payment applications, most pages scanned sideways, and lien waivers): with Mac OCR they read as text, sideways pages
turned upright, and show **no ledger** (unparsed), as they should. Cross-file:
...6655 and ...7084 chain month to month; 7.pdf (July) → September breaks on ending/beginning
because the August ...7084 statement is not in the set. Simmons quirks covered here: shadow-printed
headings, "17 Deposits/Credits" counts before labels, an Amount header ~38pt off its figures,
"CHECKS IN NUMBER ORDER" grids, a "Service Charge Breakdown" block, and a service charge printed
outside the Checks/Debits total.

`../test-statements/batch2/` — ConnectOne Bank small business checking ...3443 (Palisades Home
Improvements), April–September 2026, all six image-only scans. Run with **Mac OCR** (start
`python3 ~/pdf-vision-ocr/mac_ocr_server.py`, pick Mac OCR in Settings, Auto-OCR on). Expected: all six
**✓ reconciled**, every check PASS, about 5–6 s a statement:

| File | Period | Rows | Ending |
|---|---|---|---|
| April 2026 Statement.pdf | 2026-04-01 .. 04-30 | 127 | -$11,663.32 |
| May 2026 Statement.pdf | 2026-05-01 .. 05-31 | 155 | -$5,139.76 |
| doc00394420260819161056.pdf (June) | 2026-06-01 .. 06-30 | 116 | -$11,054.97 |
| July 2026 Statement.pdf | 2026-07-01 .. 07-31 | 99 | $6,022.85 |
| August 2026 Statement.pdf | 2026-08-01 .. 08-31 | 114 | $98,014.44 |
| Sept2026statement.pdf | 2026-09-01 .. 09-30 | 126 | -$9,219.46 |

Unlimited-OCR could not read these (amounts misread and shifted between rows, pages looping to the
token cap, 15–40 s a page). Quirks covered: a Balance Summary of "+ Deposits and Credits (18)" /
"- Checks Posted (13)" / "- Withdrawals and Debits (83)" (sign before the label, count in brackets)
whose checks are listed among the Debits as "CHECK 3267"; a "Checks Posted" register (date, number,
amount, three across) that repeats them; "Beginning Balance as of 08/01/26" (the period's first day)
and an overdrawn "Ending Balance as of 04/30/26 -$11,663.32"; a footer code printed in the
description column under each page's last row; fees dated the day before the period that the
"Balance By Date" table opens with ("Jun 30 -$11,134.97", "May 31" for fees dated May 29).

`../test-statements/batch4/` — U.S. Bank, Elitepay Business Solutions (Jun–Sep 2026). Expected: all
four **✓ reconciled**, daily balances PASS. Quirks covered: month-name dates ("Aug  5"), a summary
block with no heading ("Customer Deposits 1 5,300.00", "Card Withdrawals 1 91.88-"), "Beginning
Balance on Aug 3 $ 12,302.64", separate Customer / Other Deposits sections (keys cdep / dep), and
daily balances printed under "Balance Summary".

`../test-statements/batch5/` — TD Bank Business Convenience Plus, The Robinson Group ...4531, plus two
files that are not period statements. Expected: the four statements **✓ reconciled**, every check PASS:

| File | Period | Rows | Ending |
|---|---|---|---|
| May 2026 Statement.pdf | 2026-05-04 .. 06-03 | 65 | $1,605.42 |
| June 2026 Statement.pdf | 2026-06-04 .. 07-03 | 135 | $191,102.79 |
| July 2026 Statement.pdf | 2026-07-04 .. 08-03 | 70 | $24,788.34 |
| Attachment-1 (25).pdf | 2026-09-04 .. 10-03 | 86 | $2,755.25 |

Cross-file: May → June → July chain; July → Attachment-1 (September) shows a GAP and an
ending/beginning break because the August statement is not in the set.
`SSPM- Sept-Month to date-.pdf` is a TD online account-history printout for a different account:
**rows unverified** (it prints no balances to check against), 23 posted rows (2026-08-31 .. 09-30),
and the 3 rows under PENDING TRANSACTIONS are left out of the period. `Signed Application - The
Robinson group.pdf` is a loan application: **no ledger** (unparsed), as it should be.
TD quirks covered: a period with no comma ("May 04 2026-Jun 03 2026"); a summary with no heading
whose "Deposits", "Electronic Deposits" and "Other Credits" lines all map to dep (their figures
add up); "Checks Paid" sharing its line with "No. Checks: 12 *Indicates break in serial
sequence..."; a two-across check grid; fees under a bare "Service Charges" heading, with the
total in the summary's "Service Charges" line; icon-font glyphs on the online printout.

`../test-statements/batch6/` — First Security Bank (Searcy, AR) small business checking ...0147,
July–September 2026. Expected: all three **✓ reconciled**, every check PASS:

| File | Period | Rows | Credits | Debits | Ending |
|---|---|---|---|---|---|
| July26 (1).pdf | 2026-07-01 .. 07-31 | 274 | $141,534.35 (35) | $144,717.16 (239, incl. $16.40 service charge) | $4,994.60 |
| August26 (1).pdf | 2026-08-01 .. 08-31 | 201 | $136,316.32 (34) | $132,747.87 (167) | $8,563.05 |
| Sept26 (1).pdf | 2026-09-01 .. 09-30 | 187 | $105,947.78 (35) | $109,315.70 (152) | $5,195.13 |

Cross-file: July → August → September chain, periods contiguous. Quirks covered: a summary in
"PREVIOUS STATEMENT BALANCE AS OF 06/30/26 / PLUS 35 DEPOSITS AND OTHER CREDITS / LESS 238 CHECKS AND
OTHER DEBITS / LESS CYCLE SERVICE CHARGE / CURRENT STATEMENT BALANCE" form, with the service charge
kept out of the debits total; a "Date | Description | Debits | Credits" table header that the printout
reader also accepts (the version before this batch read July as a printout: **rows unverified**).

`../test-statements/batch7/` — Truist Simple / Dynamic Business Checking ...2936 (Dilack Home Care),
May–September 2026. Each statement was downloaded twice: the pairs differ only in creation date and
document ID. The file names are download dates, not periods ("July,2026_07012026" is June).
Expected: all ten **✓ reconciled**, every check PASS (Truist prints no daily balances, so that check
is untestable), and each file noted "a second account in this file (...4411) was not read":

| File (and its copy) | Period | Rows | Ending |
|---|---|---|---|
| May,2026_05302026 (2) / (3) | 2026-05-01 .. 05-29 | 122 | $10,036.03 |
| July,2026_07012026 (2) / (3) | 2026-05-30 .. 06-30 | 125 | $10,606.18 |
| August,2026_08012026 / (1) | 2026-07-01 .. 07-31 | 171 | $218.06 |
| September,2026_09012026 / (1) | 2026-08-01 .. 08-31 | 185 | -$1,845.98 |
| October,2026_10012026 / (1) | 2026-09-01 .. 09-30 | 216 | $14,957.48 |

Cross-file: the five periods chain May → September; the computed figures note each second copy as
"has the same period as ...; ignored as a duplicate". Quirks covered: a summary of "Your previous
balance as of 04/30/2026 / Checks - / Other withdrawals, debits and service charges - / Deposits,
credits and interest + / Your new balance as of 05/29/2026 =" with no period line (the as-of dates
give it); sentence-case headings with commas; a three-across check grid with "*" serials; a
negative ending balance printed "$-1,845.98"; an account list whose balances used to run into the
account number (read as ...3610 / ...6218); the money market account printed after the checking
account, which is left out of this ledger.

`../test-statements/batch8/` — First National Bank of Hartford (AL), Business Low Vol ...4463 (Southern
Grace Enterprises), June–September 2026. (Same file names as batch5's TD statements; different files.)
Expected: all four **✓ reconciled**, every check PASS including the row-level running-balance chain
(no daily balances are printed), each noted "N check-list entries repeat items already in the account
activity; not counted twice":

| File | Period | Rows | Credits | Debits | Ending |
|---|---|---|---|---|---|
| June 2026 Statement.pdf | 2026-05-30 .. 06-30 | 77 | $85,701.33 (11) | $72,245.58 (66) | $13,513.08 |
| July 2026 Statement.pdf | 2026-07-01 .. 07-31 | 104 | $125,040.61 (7) | $138,143.67 (97) | $410.02 |
| August 2026 Statement.pdf | 2026-08-01 .. 08-31 | 99 | $111,361.68 (13) | $82,449.79 (86) | $29,321.91 |
| September 2026 Statement.pdf | 2026-09-01 .. 09-30 | 85 | $25,606.31 (9) | $51,061.77 (76) | $3,866.45 |

Cross-file: June → September chain, periods contiguous. Quirks covered: an Account Summary of
"05/30/2026 Beginning Balance / 11 Credit(s) This Period / 66 Debit(s) This Period / 06/30/2026 Ending
Balance" (the dated balance lines give the period's first and last day); one combined Debits / Credits /
Balance activity table; descriptions printed centred on the date line (one line above it, one below) --
every row should carry its own description, e.g. 06/01 +$371.40 "400876268 ONLINE BANKING TRANSFER FROM
Business Low Vol 424269 ON 5/30/26" and 06/01 -$29.99 "834290 PURCHASE-PIN DISNEY PLUS ..."; a "Checks
Cleared" grid and a check-image index (deposit tickets included) that repeat activity rows.

`../test-statements/batch9/` — Chase Business Complete Checking ...2565 (Fredos Renovation Services),
printed in **Spanish**. Expected: the two text PDFs **✓ reconciled**, every check PASS:

| File | Period | Rows | Ending |
|---|---|---|---|
| 20260831-statements-2565- (1).pdf | 2026-08-01 .. 08-31 | 195 | -$2,285.73 |
| SEPTEMBER (2) (1).pdf | 2026-09-01 .. 09-30 | 110 | $14,495.94 |

Cross-file: August → September chain (ending -$2,285.73 = beginning). Each file has one page whose text
layer fails the legibility test (p. 11 / p. 8, the check-image pages) -- reported, not a problem for the
ledger. `May 26 small (1).pdf`, `Jun 26 small (1).pdf`, `Jul 26 small (1).pdf` are image-only scans of
the earlier months. Run with Mac OCR, expected all three **✓ reconciled**, every check PASS:

| File | Period | Rows | Ending |
|---|---|---|---|
| May 26 small (1).pdf | 2026-05-01 .. 05-29 | 216 | $1,206.50 |
| Jun 26 small (1).pdf | 2026-05-30 .. 06-30 | 132 | -$2,205.41 |
| Jul 26 small (1).pdf | 2026-07-01 .. 07-31 | 194 | -$2,358.41 |

Cross-file with the two text PDFs: May → September chain. The scans have no hidden section markers, so
they exercise the printed headings: "RESUMEN DE CUENTA DE CHEQUES" beside "Chase Business Complete
Checking", the 62-character card heading with "(continuación)", and OCR slips the repairs cover ("0//31",
"14.000.00", amounts dropped from one of fifteen identical card rows). Quirks covered: "Agosto 01, 2026 a Agosto 31, 2026"; "Número De Cuenta:";
summary "Saldo inicial / Depósitos y Adiciones 28 / Cheques pagados / Retiros de cajeros automáticos y
[compras con tarjeta de débito] / Retiros Electrónicos / Cargos / Saldo final" with negative balances;
Chase's hidden "*start*deposits and additions" markers (English) used to open sections; Spanish headings
printed one run per word with a barcode glued on ("...DE DÉBITO10759370402000000064"); "FECHA /
DESCRIPCIÓN / CANTIDAD" column headers; "SALDO FINAL DIARIO".

`../test-statements/batch10/` — three **HSBC Bank USA** online exports ("Statement details"), account
...8714 (AC NA - Operating), July, August and September 2026, plus a Chase statement for a different
account (`August 2026 Statement (2).pdf`, ...6995). Expected: all four **✓ reconciled**:

| File | Period | Rows | Checks |
|---|---|---|---|
| July 2026 Statement.pdf | 2026-07-01 .. 07-31 | 145 | running balance PASS (0 breaks); closing ledger balance $9,830.20 = newest row |
| August 2026 Statement.pdf | 2026-08-03 .. 08-31 | 139 | running balance PASS; closing balance dated 2026-09-02 is after the last row, so not compared (untestable) |
| September 2026 Statement.pdf | 2026-09-01 .. 09-30 | 162 | running balance PASS; closing ledger balance $6,036.82 = newest row |
| August 2026 Statement (2).pdf | 2026-08-01 .. 08-31 | 37 | Chase sections and balance PASS |

Cross-file: the account check flags (2) as ...6995 against ...8714 -- correct, it is another account. The
three HSBC files are reported "modified after creation" (all edited 2026-10-05 10:13). Quirks covered: a
header of "Bank reference | Customer reference | TRN type | TRN status | Value date | Credit amount | Debit
amount | Balance | Time | Post date" with each label at the start of its cell and figures ending just short
of the next label (placed by cell, not by the midpoint rule); "31 Jul 2026" dates; a "Narrative" line under
each row; the header repeated on each page, which can open with the tail of a narrative; "Closing ledger
balance brought forward ... From <date>" (pdf.js joins that line without spaces) next to a later "Current
ledger balance"; a row whose cells carry a second, clipped text run ("004945657821WAXB").

`../test-statements/batch11/BankReport (1).pdf` — a **DecisionLogic** bank-data report (the account
verification a lender pulls through the borrower's bank login), 206 pages, Bank of America, 430 days
(8/5/2025 – 10/8/2026). It covers 7 accounts; the first, checking ...6246, is the ledger and the other six
(...4417 checking, five business credit cards) are named in the note. Expected **✓ reconciled**, printout,
4757 rows (4755 posted + 2 pending), 2025-08-05 .. 2026-10-07:

| Check | Result |
|---|---|
| running balance | PASS, 4754 printed balances, 0 breaks |
| Current Balance ($2,163.54) | PASS = newest posted row (pending excluded) |
| Deposits/Credits $1,434,744.32, Withdrawals/Debits ($1,448,188.50) | PASS: 383 credits; debits $1,447,532.67 + pending $655.83 |
| Calendar View, 15 months | PASS, each month's deposits and withdrawals |

Quirks covered: "Date | Codes | Description | Category | Amount | Balance" newest first with labels starting
their cells (a long description runs past the midpoint into Category: "... INDN:A | Loan"); the font's
ligatures come through pdf.js as NUL ("Descrip\u0000on", "Automo\u0000ve Expense", "Microso\u0000" --
restored as ti / ft / tt; one word, "Charlotte", comes out "Charlotie"); "(PENDING)" leading a pending
row's description, its balance repeating the current one; a wrapped category ("Home Improvement/" |
"Maintenance"); the "Calendar View" month table ending the transactions (its Begin/End Bal columns do
not chain month to month and are not checked); the next account's Summary and table in the same file.

`../test-statements/batch12/` — **Pinnacle Bank** (pnfp.com) "Statement of Account", Little Paper Boat LLC
...8960: `document.pdf` (7/01–8/02/26), `Statement-4.pdf` (8/03–8/31), `8960_Little Paper Boat_2026-09-29.pdf`
(9/01–9/30), plus `download-2.csv`, the account's online download for 10/01–10/08. `ledger.json` is
exparsed's export of these four **before** they were supported (all three PDFs "breaks", periods missing).
Expected: all four **✓ reconciled**, and together the cross-file checks pass (periods contiguous, each ending
balance = the next beginning, account ...8960 in all three PDFs):

| File | Rows | Checks |
|---|---|---|
| document.pdf | 330 | Credits $176,176.71; Debits $185,024.77 = Other Debits + 2 checks; $7,618.53 → -$1,229.53; 23 day-ends |
| Statement-4.pdf | 313 | Credits $207,529.49; Debits $207,950.40 = Other Debits + 1 check; -$1,229.53 → -$1,650.44; 21 day-ends |
| 8960_Little Paper Boat_2026-09-29.pdf | 259 | Credits $52,536.50; Debits $52,753.09 (incl. a ".75"); -$1,650.44 → -$1,867.03; 21 day-ends |
| download-2.csv | 68 | running balance PASS over 65 posted rows; the 3 "Pending: 10/08/2026 ..." rows are pending |

Quirks covered: the summary box prints each balance under its "Balance 9/01/26" label (the closing one
shares its line with "Interest +$0.00"), so the period comes from those two labels; page 2 of every
statement is the blank back of page 1 (only "Page 2 of N"), with the credits running on after it at other
column positions; the summary's single "Debits" figure covers both "Other Debits" and "Checks"; a figure
under a dollar printed without its zero (".75"); a check-image page at the end. Provenance flags are
expected: iText-generated, and July and August "modified after creation" (9 and 25 minutes later). The CSV
has no account number, so its figures are not combined with ...8960 (its oldest balance does continue from
September's ending balance, -$1,867.03).

`../test-statements/batch13/` — **Citadel Credit Union** (citadelbanking.com), K and S Kleaners Inc, member
account 0000994346: July, August and September 2026 Statement.pdf. `ledger.json` is exparsed's export of the
three **before** they were supported (all "breaks": the savings share's $1.00 taken as the ending balance,
page 1's rows swallowed by the summary block, no account number). Expected: all three **✓ reconciled**, and
together the cross-file checks pass (periods contiguous, each ending balance = the next beginning, ...4346):

| File | Rows | Checks |
|---|---|---|
| July 2026 Statement.pdf | 137 | 34 deposits = $137,365.88, 103 withdrawals = $123,109.12; $2,433.60 → $16,690.36; running balance 0 breaks |
| August 2026 Statement.pdf | 135 | 38 = $67,173.20, 97 = $53,527.34; $16,690.36 → $30,336.22; 0 breaks |
| September 2026 Statement.pdf | 204 | 44 = $217,730.33, 160 = $237,368.95; $30,336.22 → $10,697.60; 0 breaks |

Quirks covered: "ACCOUNT #" with the number printed under it; the statement holds two shares, "BUSINESS STAR
SAVINGS - 0000" (beginning and ending $1.00, no activity) before "ELITE BUSINESS CHECKING - 0070", whose own
table is the ledger and whose heading repeats "(Continued)" on each page; "07/01/2026 BEGINNING BALANCE" /
"ENDING BALANCE" lines; control totals "34 DEPOSITS = $137,365.88  103 WITHDRAWALS = $-123,109.12"; a
"Cleared Check Summary" register (checks already in the table) in August and September. The printed
"Average Daily Balance" is $0.16–$0.28 below the computed one: the bank averages before the month-end
dividend posts.

`../test-statements/batch14/` — **United Bank** (BankWithUnited.com), Artisan Frontier LLC, Free Business
Checking 3107077: 5.pdf (May), 6.pdf (June), 7.pdf (July), 8.pdf (August) and Sept26.pdf (September 2026).
It is the ConnectOne layout of batch2 with a text layer. The version before (`exparsed.before-batch14.html`)
read all five as "breaks". Expected: all five **✓ reconciled**, every check PASS and no unread lines. Loaded
together, the 9 cross-file checks pass (periods contiguous, each ending balance = the next beginning, ...7077
on all five), and the computed average balance for each month equals the printed "Average Balance":

| File | Rows | Deposits | Checks Posted | Withdrawals | Beginning → Ending | Avg balance |
|---|---|---|---|---|---|---|
| 5.pdf | 116 | 26 = $230,420.15 | 27 = $80,166.54 | 63 = $111,404.31 | -$13,486.71 → $25,362.59 | $2,154.90 |
| 6.pdf | 192 | 36 = $498,674.67 | 72 = $450,175.76 | 84 = $85,264.51 | $25,362.59 → -$11,403.01 | $5,209.55 |
| 7.pdf | 156 | 22 = $365,834.65 | 60 = $287,315.62 | 74 = $74,134.48 | -$11,403.01 → -$7,018.46 | $9,678.63 |
| 8.pdf | 160 | 20 = $528,903.95 | 65 = $317,506.94 | 75 = $130,824.72 | -$7,018.46 → $73,553.83 | $21,461.71 |
| Sept26.pdf | 135 | 19 = $228,293.23 | 36 = $192,957.81 | 80 = $138,461.02 | $73,553.83 → -$29,571.77 | -$278.67 |

Quirks covered:
- **Margin marks:** a 2D barcode's rows (letters A–P, "AKFPDIBKHLGPBMEOEPANEMDK") and the sheet's sequence
  number ("7151 0036637 0002-0010 0000000000000000") run down the left margin. pdf.js joins them to the
  headings ("Credits", "Checks Posted (Continued)", "Balance By Date") and to the rows that share their height.
- **Blank page:** page 2 carries only the mail footer.
- **Checks Posted register:** dates, numbers and amounts, three across. "*" marks a break in the sequence and
  "R" a returned check. It runs on pages of its own ahead of Debits, which list every check again ("CHECK
  6570").
- **Returned items:** checks and ACH debits are returned, re-presented and returned again, each with a $36
  NSF or overdraft fee.
- **Fees from the previous month:** overdraft fees dated the last day of the previous month are listed in the
  next statement. That statement's "Balance By Date" opens with that day's balance after those fees. It must
  not replace the previous statement's own figure in the monthly average.
- **Check images:** "Check Images for Account 3107077" pages carry captions ("05/04/2026 # 6570
  $13,124.50") that repeat rows.

`../test-statements/batch15/` — **First Community Bank** (Bluefield, VA), The Big Pig of Sparta Inc,
Community Commercial Checking ...6098:
- `7.pdf` (July, 7/01–8/02/26): a 29-page **Canon scan** whose embedded text layer is the scanner's own poor
  OCR. It needs Mac OCR.
- `8.pdf` (August) and the `CHKxxxx6098-STATEMENT-09-30-2026-….pdf` (September): text PDFs.

`ledger.json` is exparsed's export of the three **before** this batch's fixes. July went through Mac OCR,
was read as an online printout, and was "untestable"; August and September already verified. Expected now,
all three **✓ reconciled** (July with Mac OCR on), with the cross-file checks passing:

| File | Rows | Deposits/Credits | Checks/Debits | Previous → Current |
|---|---|---|---|---|
| 7.pdf | 300 | 49 = $152,730.36 | 251 = $148,653.04 | $26,540.28 → $30,617.60 |
| 8.pdf | 274 | 48 = $171,197.64 | 226 = $139,002.24 | $30,617.60 → $62,813.00 |
| CHKxxxx6098-…pdf | 252 | 42 = $98,717.73 | 210 = $147,860.38 | $62,813.00 → $13,670.35 |

Quirks covered, all in July's scan:
- **Scanner's own text layer:** the scanner's OCR passes the per-page legibility test on 26 of 29 pages, so
  "OCR full doc" used to re-read only pages 4, 6 and 8 and kept the scanner's garbled text for the rest. A
  PDF whose creator is a scanner or scan app now has every page read again. lgBuild still prefers the text
  layer when that reconciles.
- **Shaded heading lost:** "Checks and Withdrawals" sits on a shaded band that scanned black. Only the column
  header repeats after the deposits, and the debits print a trailing minus ("7.12-"). On the next page the
  heading reads "Chax ana y".
- **Register heading garbled:** "Checks in Number Order" reads "Checka in Hi", so only the register's own
  header ("Date Check No | Amount Date Check No | Amount") names it.
- **Cells joined:** a date and a check number come through as one cell ("7/02 9999931124*").
- **Slash read as 1:** "7127" for 7/27.
- **Upside-down and garbled figures:** Vision returned eight register figures upside down or with garbage
  after the cents ("325.00" as "0O•SZE", "332.67" as "29 ZEE", "341.01" as "TOIDE", "338.65" as "338.6s").
  The helper (`mac_ocr.swift`) now treats such readings as unreadable and reads the cell again from the whole
  box, accepting only a whole figure. Turning a reading back over is not safe: an upside-down 7 came back
  as "2".

## Mac OCR over every statement (stress test, 2026-10-08)

All 59 PDFs were also read page by page through Mac OCR **ignoring their text layer** (the tool never does
this for a text PDF -- it uses the exact text layer -- but it shows how scans of these banks would fare):
43 of the 53 statements reconcile from OCR alone (45 since 2026-10-09: the helper re-reads figures Vision
returned upside down -- Simmons' "$30,000.00" came back "00•000 0E" -- see batch15); the rest miss one to a few
figures that Vision misreads as another valid number or skips (Simmons' shadow-printed type drops leading digits, "$30,000.00" ->
"1,000.00"; one HSBC debit cell; one TD wire; FNB card rows). Repairs that came out of this run and are
covered by `macocr.js`: a stray mark after a date ("09/02/26/"), letter-spaced words ("Depos i ts"), a lone
"Deposit" label on a deposit slip, a day joined to the text after its month ("Jul" | "2 Electronic ..."),
one-decimal amounts ("3,500.0"), table rules read as "łął" after a figure, bare numbers where an amount
should be ("68929" for "$6,764.89").
