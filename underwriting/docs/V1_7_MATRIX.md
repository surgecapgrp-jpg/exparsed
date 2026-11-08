# Policy V1.7 compliance matrix

Each row maps one V1.7 requirement (MCA Capacity Underwriter V1.7, 2026-11-02) to `engine/uw.py` and `adapter/exparsed_adapter.py` on branch `v17-batch4`.

Status values:

- **Met**: the engine already does what the rule says.
- **B1**: changed in batch 1.
- **B2**: changed in batch 2.
- **B3**: changed in batch 3.
- **B4**: changed in batch 4 (this branch), fixes from the 2026-11-02 spec review.
- **Partial**: part of the rule is implemented; the gap is named.
- **Gap**: not implemented.
- **Page**: handled by Exparsed extraction before the engine runs.

Batch 2 covered debit-first discovery (D1 to D5), WATCH rows, the ±30-day two-way match, evidence levels and position identity. Rows still marked B2 in the Fix column were deferred: off-bank collections, contractual cost, payoff ties and variable adverse scenarios. **B3** covers accounts, commingling, missing-account requests, the V1.7 ten-table format and its checker.

Count: 150 rows. 19 B1, 33 B2, 23 B3, 8 B4, 2 B5, 3 B6, 5 B7, 5 V1.8, 38 Met, 8 Partial, 3 Gap, 3 Page.

## Contract hard rules

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| H1 | No invented values; missing is not zero; estimates labeled SCENARIO | Every number comes from ledger rows. U costs and the 1.4x payoff print as SCENARIO. | B1 | — |
| H2 | Keep source refs, descriptions, IDs and cents | `txn_id`, `source_ref`, raw description and Decimal amounts are kept in the audit | Met | — |
| H3 | Missing debit or 1.4x payback never proves closure | N requires `terminated` evidence. Silence gives Y (assumed open) or U. | B1 | — |
| H4 | Keep unresolved candidates with unknown funder, 1 to 2 payments, varying amounts or no funding | Unanswered payees with a finance word, a D3/D4 link or a fixed daily/weekly/biweekly series are WATCH rows. A varying payee without those signals is not nominated. | B2 | Sign-off B10 |
| H5 | Code does arithmetic and checks; never claim an unrun check | `self_checks` lists only executed checks. The LLM answers questions only. | Met | — |
| H6 | Analyze readable files; record every unreadable source | The adapter lists every file that gave no rows in `sources_unread`; Table 1 shows it as Unreadable or Not a statement | B3 | — |
| H7 | Recompute all dependents after any change | Every run recomputes everything from ledger plus judgments | Met | — |
| H8 | Ten fixed sections; Live? is Y/N/U; material U shown | Y/N/U rows and the V1.7 Table 8 lines render; `checker/validate_report.py` enforces them | B3 | — |
| H9 | Say INSUFFICIENT DATA when evidence is insufficient | Fewer than 2 counted months, a material U position, a material unprovided account, an unreadable statement, or unresolved credits that could reverse a NO | B3 | — |
| H10 | Internal audit record; output is the ten tables only | `audit.json` plus a report holding the tables and fixed lines | Met | — |
| H11 | Execution order steps 1 to 11 | Same order, but there is no account-link step and no separate debit-first sweep | Partial | B2, B3 |

## Parameters

| ID | Parameter | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| P1 | BUSINESS_DAYS_PER_MONTH = 20 | 20 | Met | — |
| P2 | WEEKS_PER_MONTH = 52/12 | `D(52) / D(12)`; was 4.333 | B1 | — |
| P3 | BIWEEKS_PER_MONTH = 26/12 | `D(26) / D(12)`; was 2.167 | B1 | — |
| P4 | FULL_MONTH_DAYS = 18 on material accounts | 18 days per material account (S11) | B3 | — |
| P5 | CURRENT_COLLECTION_WINDOW = 10 bd to the debit account's coverage end | 10 bd counting the coverage-end day; batch 1 counted 11 | B4 | — |
| P6 | PRIMARY_FUNDING_WINDOW = 7 bd on or before the first debit | 7 bd, holidays excluded | Met | — |
| P7 | EXPANDED_DISCOVERY_WINDOW = ±30 calendar days, investigation only | Backward and forward searches list MED/HIGH credits or triggers within ±30 calendar days as INVESTIGATE | B2 | — |
| P8 | UNATTACHED_WINDOW = 14 calendar days | 14 | Met | — |
| P9 | SERIES_MIN = 3; EARLY_SERIES_MIN = 1 | 3. A 1 to 2 debit payee with a finance word is a WATCH row when it is not recent. | B2 | — |
| P10 | NEW_LEVEL = 3; AMOUNT_CHANGE strictly >10% | 3; `abs(b - a) > a * 0.10` | Met | — |
| P11 | STOP_GAP = 2x cadence, alert only | STOPPED event, "no payoff debit seen" | Met | — |
| P12 | PROLONGED_SILENCE = 30 covered bd | 30 covered business days, then U | B1 | — |
| P13 | CURE_WINDOW = 2 bd | 2 | Met | — |
| P14 | THIN_BALANCE = EOD < 3 x (stack / 20) | Same; the stack holds Y positions only | Met | — |
| P15 | FLIGHT = >30% of one inflow leaves within 48 h | >30% within 2 calendar days of any external credit of 3x median deposit or more: transfers, refunds, recredits, owner strips and returned credits are left out (signed off 2026-11-08, V1.8b8) | V1.8 | — |
| P16 | COMMINGLING severity thresholds | LOW, MODERATE and HIGH per account-month on confirmed items | B3 | — |
| P17 | CAPACITY_UNCERTAINTY: material if it changes verdict, binding, or >=5% of BASIS | `MATERIAL_SHARE = 0.05`, tested by `readiness()` | B1 | — |

## Records and evidence

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| R1 | SOURCE record per file | `audit.sources`: one record per supplied file (account, period, Exparsed status, checks passed and failed, rows, pending, zero, flags, rows the page omitted) | B7 | Page counts per source still come from `source_ref` |
| R2 | ACCOUNT record with ownership evidence and links | ID, name, last4, statements, integrity; unprovided linked accounts in `account_requests` | Partial | Ownership evidence per account |
| R3 | TX record with originator ID, trace ID, sequence, evidence level | Each `audit.transactions` record carries `sequence`, `source_ref` (file, page, row), `orig_id` (now read with or without the colon, masked or not) and `trace_id` (`TRACE#`, `TRACE NO`, `TRACE NUMBER`). Evidence level stays on positions and strips. | B7 | — |
| R4 | DEBIT_CANDIDATE and CREDIT_CANDIDATE with a disposition each | `debit_dispositions` gives each nominated payee POSITION, WATCH or NON-MCA; forward searches give each candidate credit a V1.7 disposition | B2 | — |
| R5 | MATCH with business and calendar gaps, rivals, decision | Backward candidates log business-day and calendar-day gaps, rivals and outcome | B2 | — |
| R6 | POSITION with status basis, closure evidence, scenario cost | `live_status`, `status_basis`, `terminated` and `scenario_cost` are in the audit | B1 | — |
| R7 | EXCEPTION records | `audit.exceptions`: type, source_tx_ids, why_unresolved, possible_effect_on_capacity, required_evidence, severity, for U positions, unresolved credits, account requests, unreadable statements and open questions | B7 | — |
| R8 | Never join on company name alone | Same judged funder joins payees only on a shared originator ID, sequential continuity, or open payment slots | B2 | — |
| R9 | Evidence levels OBSERVED, CORROBORATED, INFERRED, UNKNOWN | Positions and STRIP_FUNDING gates carry OBSERVED, CORROBORATED, INFERRED or UNKNOWN | B2 | Sign-off B16 |

## 1. Source routing, coverage and integrity

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| S1 | Route paths A to D by content | Exparsed extracts PDFs, CSVs and scans; the engine reads Path A only | Page | — |
| S2 | Inventory every file, page and account; unreadable files stay listed | Unread statements and non-statement documents stay in the inventory (Table 1, `audit.sources_unread`) | B3 | — |
| S3 | Pending rows kept as non-cleared observations | Excluded from totals, counted in a Table 1 note, listed in `audit.pending_observations` | B7 | — |
| S4 | Sign and date conventions from labels and balances | Exparsed extraction | Page | — |
| S5 | Last four alone never prove the same account | The adapter still groups files by `accountLast4`; Exparsed drops overlapping printouts of one account first | Partial | Group by full number or balance continuity when the export carries them |
| S6 | Early account-link evidence | `account_links()` collects unprovided accounts from transfer text (masked numbers, names, ORIG CO), with flows and months | B3 | — |
| S7 | Dedupe across copies with a crosswalk; keep identical distinct rows | Exparsed drops overlapping printouts (`lgOwnRows`) and says so in `rowsOmitted`, now in the source record. Identical rows stay distinct; `audit.duplicate_crosswalk` lists them and each transaction names its source row. | B7 | Row-by-row list of the rows the page drops needs a page export change |
| S8 | Reconcile balances, totals and continuity | Exparsed checks; the engine takes the status and cross-checks gross credits per month | Page | — |
| S9 | Integrity labels and suffix order | Exparsed status mapped to Pass, Pass with flag, Unverified, Break; worst account sets the suffix | Met | — |
| S10 | Calculation eligibility separate from integrity | A month is excluded when a material account is short, whatever the integrity label; the reason is in Table 1 | B3 | — |
| S11 | Coverage per relevant account; no union hides a missing account | A month counts only with >=18 days on every material account (>=5% of credits) whose statement span includes it | B3 | Sign-off B17 |
| S12 | Custom cycles keep dates but revenue uses calendar months | All accounts use calendar posting months; statement-cycle grouping is removed | B3 | — |

## 2. Provisional classification

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| T1 | One final tag; alternatives stored separately | One tag per transaction (self-check). No alternatives. | Partial | B2 |
| T2 | Credit tags include STRIP_UNRESOLVED | Added | B1 | — |
| T3 | STRIP_UNRESOLVED is a revenue exclusion, not a funding claim | Unanswered candidates become STRIP_UNRESOLVED. Forward dispositions say "not called financing". | B1 | — |
| T4 | Customer evidence keeps a credit in revenue | An answered `REV_*` tag restores it | B1 | — |
| T5 | Debit tags incl. MCA_UNKNOWN_POSITION, FEE_NSF_OD, AMBIGUOUS_ | MCA_<payee>, FEE_NSF_OD, AMBIGUOUS_<LABEL>; WATCH rows without a usable name show "Unknown MCA-style #N" | B2 | — |
| T6 | Recurrence alone is not MCA; rails do not exclude | Manual transfers and checks are swept with other debits. Recurrence alone gives NON-MCA unless the series is fixed daily/weekly/biweekly. | B2 | — |
| T7 | Non-bank documents corroborate; off-ledger collections disclosed | Documents serve as evidence for strips and closures. No off-bank exposure. | Partial | B2 |

## 3. Debit-first discovery

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| D1 | Name and ID pass: finance language, aliases, originator and trace IDs | `MCA_WORD`, finance words inside a token (HEADWAYCAPITAL), the `ORIG CO NAME` payee and `ORIG ID` for identity | B2 | Sign-off B13 |
| D2 | Cadence pass incl. variable amounts, skips, splits, changes; keep 1 to 2 items | Cadence per payee incl. monthly; fixed daily/weekly/biweekly series without a finance word become WATCH when unanswered | B2 | — |
| D3 | Amount pass across changed descriptors and rails | A payee with 2+ debits at an MCA series' level within 30 days of the series (B9 signed off 2026-11-07: the half-of-payee rule is gone) | B2 | — |
| D4 | Funding-linked pass: rescan debits after a suspected funding credit | A new payee within 30 days after an explicit financing credit, when it repeats at daily/weekly/biweekly gaps or shares a word with the sender | B2 | Sign-off B8 |
| D5 | Exception pass: returns, stop-pays, fees, processor net settlements, missing-account transfers | Returned attempts of finance-word payees are nominated (D5). Hidden collections are not recovered. | Partial | Recover collections behind failed attempts |
| D6 | Reverse consolidations, processor splits, off-bank deductions | None | Gap | B2 |
| D7 | Generic descriptors cannot join payments | Grouping is by normalized description | Partial | B2 |
| D8 | Concurrent schedules under one funder are separate positions | Split when 3+ days hold same-day debits differing by >10%, or when same-amount doubles fall on 3 consecutive debit days. An isolated same-amount double (the day after a holiday) is a catch-up. | B6 | — (B22 signed off 2026-11-07) |
| D9 | Series: 3+ cleared; EARLY FINANCE for 1 to 2 with finance evidence; others WATCH | CONFIRMED, PROBABLE, U for provisional cadence, and UNRESOLVED WATCH rows | B2 | — |
| D10 | Amounts: cleared only, attempt chains, >10% for 3 payments, temporary cuts, frequency changes | Implemented as written | Met | — |
| D11 | Variable remittance: documented level plus adverse scenario | VARIABLE cost = cleared debits in the last 20 bd; `adverse_cost` = highest 20 bd of cleared debits in the series, in Table 4 notes, never in the stack | B6 | — |
| D12 | Negative control against payroll, fees, taxes, rent, transfers | Debit rules tag these first; the LLM can overrule | Met | — |

## 4. Credit-first discovery

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| C1 | Explicit finance language or corroborated lender identity | `EXPLICIT_FIN` and funder-name tokens | Met | — |
| C2 | New or ambiguous senders on wires, ACH, transfers, mobile deposits, checks | Every wire, plus any ACH, transfer, deposit or check credit from a sender seen fewer than 3 times over 2 months ("new sender"). Unclear transfers keep their own question. | B5 | — |
| C3 | Large or unusual credits; size alone is weak | 3x median, excluding established payers | Met | — |
| C4 | Any credit in primary or expanded windows of a trigger | The 7 bd window scores every credit; the ±30-day window lists MED/HIGH credits as INVESTIGATE | B2 | — |
| C5 | Documented advance or off-bank receipt | Document evidence path. No off-bank flag. | Partial | B2 |
| C6 | Six dispositions: ATTACHED, FINANCING_UNATTACHED, COMPETING, CUSTOMER_SUPPORTED, OTHER_SUPPORTED, UNRESOLVED | `v17_disposition`: ATTACHED, FINANCING_UNATTACHED, COMPETING, CUSTOMER_SUPPORTED, OTHER_SUPPORTED, UNRESOLVED | B2 | — |

## 5. Matching, events and renewals

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| M1 | Triggers: START, AMOUNT UP, CADENCE CHANGE, RESTART, renewal | START, AMOUNT UP, CADENCE CHANGE, RESTARTED | Met | — |
| M2 | T is the first debit of the new level; confirmation date kept separately | Yes; the confirmation date is in the event detail | Met | — |
| M3 | Primary match within 7 bd before T; log business and calendar gaps | Business-day and calendar-day gaps | B2 | — |
| M4 | Expanded ±30 calendar days, kept as INVESTIGATE | INVESTIGATE list per trigger; never attached | B2 | — |
| M5 | Credit after T disclosed as a contradiction | Expanded candidates after the trigger carry `after_trigger` and the outcome counts them as contradictions | B2 | — |
| M6 | Coverage test A: every trigger has backward and expanded dispositions | Backward and expanded dispositions per trigger (self-check) | B2 | — |
| M7 | Coverage test B: every candidate credit has forward and expanded dispositions | Forward and expanded dispositions per candidate credit (self-check) | B2 | — |
| M8 | Pair score points +3, +2, +2, +1, -3; HIGH, MED, LOW, NONE | +2 needs explicit finance terms or a wire that names the funder or carries finance wording; plain customer wires get 0 | B4 | — |
| M9 | Proof gate: financing text, document, or independent evidence of the sender | `bank_text`, `document`, `named_funder_series`. A model `sender_identified` answer is not proof: the credit is STRIP_UNRESOLVED, unattached, with a Table 1 verify note (signed off 2026-11-08, V1.8b8) | V1.8 | — |
| M10 | Link gate; rivals listed; ties are COMPETING | Rivals logged; ties and cross-position reuse are AMBIGUOUS | Met | — |
| M11 | One credit cannot fund two unrelated positions | Self-check | Met | — |
| M12 | Early match: unknown cadence gets a STRESS scenario only | Provisional cadence becomes U with STRESS = max debit x20 | B1 | — |
| M13 | Events incl. descriptor or ID change | Adds DESCRIPTOR CHANGE when payee groups join, with the join basis | B2 | — |
| M14 | Renewal: same verified funder within 10 bd after stop | A same-funder restart within 10 bd of the stop adds a PROBABLE RENEWAL event next to RESTARTED (which already triggers a funding search). One position. Different-name refi hint within 10 bd. | B6 | — |
| M15 | Unattached: proven funding without trigger in 14 days | FINANCING unattached note in Table 1 | Met | — |
| M16 | Pre-file only when a source establishes it | No longer inferred; note says "unproven" | B1 | — |
| M17 | "Not found" requires both coverage tests | Both windows are searched before Not found | B2 | — |
| M18 | Funding Date and Amount come from a sourced credit only | Attached credit, else Not found | Met | — |

## 6. Position status and cost

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| L1 | One POSITION ID per credible series; one funder may own several | P1, P2 and so on; display adds #n | Met | — |
| L2 | Dispositions ESTABLISHED, PROBABLE, NON-MCA SUPPORTED, UNRESOLVED WATCH | CONFIRMED, PROBABLE, NON-MCA (debit dispositions) and UNRESOLVED WATCH | B2 | — |
| L3 | Unknown funder labeled "Unknown MCA-style #N" | "Unknown MCA-style #N" when the payee has no usable name | B2 | — |
| L4 | Y: cleared within 10 bd of the debit account's coverage end | Yes, 10 bd counting the end day | B4 | — |
| L5 | Y: established position silent up to 30 covered bd, "assumed open; collections absent" | Yes; the last sustained cost is carried | B1 | — |
| L6 | N only with closure evidence; N costs $0 | Bank-text closure must sit on a transaction of the payee or naming its funder; cleared debits after that date keep the position open. Document closures carry no engine-readable date. | B4 | — |
| L7 | U: unproved identity, silence over 30 covered bd, or visibility gaps; cost —, scenario in Notes | Silence over 30 bd, provisional cadence, no cleared debit, or WATCH (identity unproved) | B2 | — |
| L8 | Total Live Stack sums Y only; U stays out | Yes (self-check) | B1 | — |
| L9 | Cost: daily x20, weekly x52/12, biweekly x26/12, monthly x1 | Daily, weekly, biweekly and monthly (18 to 25 bd gaps, x1) | B2 | Sign-off B14 |
| L10 | Temporary reductions use the prior sustained payment | TEMP CUT events | Met | — |
| L11 | CONTRACTUAL cost separate from observed | None | Gap | B2 |
| L12 | 1.4x payoff as SCENARIO only | Labeled "SCENARIO est. remaining ... not closure evidence" | B1 | — |
| L13 | Contract or lender payoff tied to the position | None | Gap | B2 |
| L14 | Non-MCA loans in DEBT_SERVICE; no double count | DEBT_SERVICE rule tag; MCA debits are tagged MCA_ only | Met | — |
| L15 | Do not merge two positions because the funder name matches | See R8 | B2 | — |
| L16 | Material U blocks YES; NO stands only if unknowns cannot reverse it | `readiness()` | B1 | — |

## 7. Revenue, obligations and capacity

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| V1 | Consolidated calendar months after dedupe | Calendar posting months for every account | B3 | — |
| V2 | Stripped includes STRIP_UNRESOLVED, shown as unresolved | Table 2 shows "unresolved $X"; Table 1 totals it | B1 | — |
| V3 | Counted needs >=18 days and eligibility | 18 days on each material account; flagged months excluded | B3 | — |
| V4 | TOR, Last-3, BASIS | As written | Met | — |
| V5 | Table 3 over all months equals Table 2 all-month True Revenue | Self-check | Met | — |
| V6 | Obligations include zero months; OWNER_DRAW and AMBIGUOUS excluded | As written | Met | — |
| V7 | Material excluded outflows disclosed with sensitivity | What Would Flip This gives owner draws and AMBIGUOUS outflows per month and Room C with them counted | B3 | — |
| V8 | Rooms A to D, HEADLINE, CONSERVATIVE from unrounded cents | As written (self-check on HEADLINE) | Met | — |
| V9 | Weekly = monthly/(52/12), daily = monthly/20 | Yes | B1 | — |
| V10 | Binding texts | Zero headline names Room B and/or C; the conservative binding (Room C, or Room D and the worst month) is always stated | B4 | — |
| V11 | Readiness: <2 months, an essential unavailable amount, or material uncertainty gives INSUFFICIENT DATA | Months, material U positions, material unprovided accounts, unreadable statements, and unresolved credits that could reverse a NO | B3 | — |
| V12 | Data-status suffix | Worst integrity across accounts | Met | — |

## 8. Peak, returns and liquidity

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| K1 | Peak over all cleared MCA collections by Monday-to-Sunday week | Yes, including U and N positions | Met | — |
| K2 | Skip weeks with <5 covered bd on the collection accounts | Counts covered business days, so holiday weeks with 4 are skipped | B4 | — |
| K3 | Peak = max(observed, modeled current); peak holdback | Report Peak floored at stack/(52/12) and labelled modeled current floor; holdback over a counted month only; checker rejects a negative drop | B4 | — |
| K4 | Returns classified once per attempt chain | Chains within 10 bd | Met | — |
| K5 | FEE_NSF_OD is a fee, never a return | Yes | Met | — |
| K6 | Class A, B and UNKNOWN | A return credit with no matching debit is Class A (B21), tier n/a, cure "UNKNOWN (debit not found)" (V1.8 R3/R4, V1.8b1). Class UNKNOWN is no longer produced | V1.8 | — |
| K7 | T1, T2, T3 codes | V1.8 R3: T1 only for a stop/block code on MCA or loan; the same code on payroll, rent, tax or insurance gives n/a; on any other item T3. T2 every other return on MCA, loan, payroll, rent, tax, insurance; T3 the rest | V1.8 | — |
| K8 | Cure only within 2 bd with balance; MCA stop-pay never cured | T1 never cured. Y needs a cleared re-presentment within 2 bd with EOD >= 0; for a daily position only an extra pull counts (V1.8b6). N for a re-presentment into overdraft or no re-presentment in a covered window. UNKNOWN when the balance or the 2 bd window is missing (V1.8 R4) | V1.8 | — |
| K9 | Table 9 metrics; absent balances are "unavailable" | Six fixed rows | Met | — |

## 9. Commingling and missing accounts

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| G1 | Confirmed vs possible personal items per account-month | Confirmed: OWNER_DRAW debits and STRIP_OWNER credits (owner names, transfers to the owner, model answers). Possible: P2P and consumer-merchant debits, reported apart. | B3 | Sign-off B19 |
| G2 | Severity LOW, MODERATE, HIGH | Per account-month count, $ and share of gross credits; worst month sets the status | B3 | — |
| G3 | REQUEST REQUIRED for unprovided accounts tied to material flows | REQUEST REQUIRED for recurring, financing or material transfers to an unprovided account, with counts, $ and months | B3 | — |
| G4 | VERIFY OWNERSHIP for owner or affiliate accounts | VERIFY OWNERSHIP when transfers run both ways with the unprovided account | B3 | — |
| G5 | Missing accounts that may hide MCA payments force INSUFFICIENT DATA | An unprovided account moving >=5% of BASIS per month, or an unreadable statement, blocks YES; a NO stands (B18 signed off 2026-11-06, V1.7b5) | B3 | — |

## 10. MCA completeness audit

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| A1 | Debit coverage: every cleared debit scanned by D1 to D5 with a disposition | Every debit not tagged by a payroll, tax, rent, utility, insurance or fee rule is swept; each nominated payee has a disposition (self-check) | B2 | — |
| A2 | Credit coverage: every cleared credit scanned by C1 to C5 | `credit_dispositions`: one V1.7 disposition per cleared credit. Candidates take their forward-search result; processor, payer, recurring or answered credits are CUSTOMER_SUPPORTED; strips are OTHER_SUPPORTED or UNRESOLVED (self-check) | B5 | — |
| A3 | Bidirectional link coverage | Primary and ±30-day windows in both directions | B2 | — |
| A4 | Series and ID coverage | Each nominated payee maps to one position, WATCH row or NON-MCA tag; no debit in two positions (self-check) | B2 | — |
| A5 | Live and closure coverage: every N has proof; every material U visible | Self-check "N only with closure evidence; U carries a scenario"; closure tied to the position (L6) | B4 | — |
| A6 | Cross-account coverage | Transfers to and from unprovided accounts are listed and gate the verdict when material | B3 | — |
| A7 | Reconciliation: stack = Table 4 = 4b = Table 6 to the cent | Self-check plus the report validator | Met | — |
| A8 | Completeness metrics; audit FAIL if any eligible row lacks a disposition | `completeness` counts credits and debits scanned, candidates, positions, WATCH rows, material U, unattached and unresolved credits, closures | B2 | requested_missing_accounts still null; see `account_requests` |

## 11. Output and validation

| ID | V1.7 rule | Engine now | Status | Fix |
| :--- | :--- | :--- | :--- | :--- |
| O1 | Ten sections with fixed titles, columns and widths | V1.7 ten sections; widths match; fixed lines checked | B3 | — |
| O2 | Table 4 row types POSITION, WATCH, EVENT, SUMMARY; order Y, U, N | Y, U, N order (validator); EVENT rows; WATCH rows are U with "UNRESOLVED WATCH" in Notes | B2 | — |
| O3 | U Monthly Cost is —; N is $0 | Validator rejects a costed U row | B1 | — |
| O4 | Formats: $12,345, 12.3%, MM/DD/YY, Mon-YY; pipes to slashes | As written | Met | — |
| O5 | Table 8 Commingling and Additional Accounts lines | Commingling and Additional Accounts lines render and are checked once, in order | B3 | — |
| O6 | Table 8 fixed line "Capacity test ... Not a fund recommendation." | Present | Met | — |
| O7 | Validator assertions 1 to 7 | `checker/validate_report.py` (V1.7 report checker, from the V2.2 validator) | B3 | — |
| O8 | No fund or decline recommendation | None is produced | Met | — |

## Batch 1 interpretations for sign-off

| # | V1.7 text | Engine reading |
| ---: | :--- | :--- |
| B1 | STRIP_UNRESOLVED for a "material receipt lacking sufficient evidence" | An unanswered or "unsure" candidate credit of $2,500 or more becomes STRIP_UNRESOLVED. **Signed off 2026-11-07, changed:** a smaller one keeps its rule tag and stays in revenue (`UNRESOLVED_FLOOR`, V1.7b9). Rule-verifiable funding evidence still strips it. |
| B2 | "material U/excluded-revenue ... uncertainty affecting capacity => INSUFFICIENT DATA" | **Decided 2026-11-02, changed:** unresolved credits never block YES. They are already out of BASIS, so adding them back can only raise capacity. They block NO only when adding them back would reverse it. Their BASIS and HEADLINE sensitivity stays in `capacity.uncertainty`. Material U positions still block YES. |
| B3 | "An incomplete or unverified cadence has a STRESS-only rate" | A position without a standard cadence (fewer than 3 cleared debits, or irregular gaps) is U with STRESS = max cleared debit x20. **Decided 2026-11-02: kept.** A material U row blocks YES, so leaving its STRESS cost out of the stack cannot produce an unsafe YES. |
| B4 | U scenario cost | The last sustained monthly cost. For VARIABLE, cleared debits in the 20 bd ending at the last debit. **Signed off 2026-11-07, kept.** |
| B5 | "30 covered business days without collections" | Business days after the last cleared debit, through coverage end, inside the debit account's statement periods. **Signed off 2026-11-07, kept.** |
| B6 | Current window "through the end of the relevant account's available coverage" | The debit account's last statement end date. **Signed off 2026-11-07, kept.** |
| B7 | Combined U exposure | Each U position is tested alone. **Signed off 2026-11-07, changed:** the sum of immaterial U scenarios is no longer tested (V1.7b10). |

## Batch 1 effect on saved runs

| Run | Before (V2.2) | After (batch 1) | Cause |
| :--- | :--- | :--- | :--- |
| Sample, no answers | YES, HEADLINE $17,578 | INSUFFICIENT DATA, $11,577 | JKL wire $30,000 becomes STRIP_UNRESOLVED; SunCap silent 66 bd becomes U ($6,000/mo scenario, 11.5% of BASIS) |
| Sample, saved answers | YES, $5,218 | INSUFFICIENT DATA, $5,217 | SunCap U. A payoff document plus a `terminated` answer gives YES (test). |
| Real ledger, no answers | YES, $91,570 | INSUFFICIENT DATA, $74,570 | $243,928 of candidate credits become STRIP_UNRESOLVED; 4 stopped funders become U |
| Real ledger, saved answers | YES, $44,883 | INSUFFICIENT DATA, $44,882 | 5 stopped funders become U, 4 of them material: Accord $14,054, DIB $8,753, Eminent $7,500, MS Equities $7,045 per month |

The $1 HEADLINE moves come from 52/12 replacing 4.333. With V1.7, a real ledger reaches YES only when each stopped funder has closure evidence (payoff letter or bank text) or resumes collections.

## Batch 2 interpretations for sign-off

| # | V1.7 text | Engine reading |
| ---: | :--- | :--- |
| B8 | D4 "rescan all subsequent and nearby debits" after a suspected financing credit | A payee whose first debit falls within 30 days after an explicit financing credit is nominated only if it repeats at daily, weekly or biweekly gaps, or shares a word with the sender. Without that filter the real ledger nominated a bar, a convenience store and Zelle payments. **Decided 2026-11-02: kept.** |
| B9 | D3 "repeated same or similar collection amounts under changing descriptors" | 2+ debits at a default MCA series' most common amount, within 30 days of the series. **Signed off 2026-11-07, changed:** the payee's other debits no longer matter (was: the hits had to be half of them). One $390 check among 194 checks still does not count: it is 1 debit. |
| B10 | D2 cadence without a funder name | An unanswered fixed daily, weekly or biweekly series becomes a WATCH row. Fixed monthly series without a finance word (rent-like bills) stay NON-MCA. On the real ledger, this catches KAPITUS and ACCORD BUSINESS when no answers exist. **Decided 2026-11-02: kept.** It catches KAPITUS and ACCORD BUSINESS; a model answer removes a false WATCH row. |
| B11 | Expanded window "plausible out-of-window relationships" | Credits scoring 3+ points (MED or HIGH) within ±30 calendar days. They are listed as INVESTIGATE and never attached. **Signed off 2026-11-07, kept.** |
| B12 | "A descriptor change with a corroborated originator ID and continuity is usually the same position" | Two payees given the same funder join when they share an `ORIG ID`, when one starts within 10 business days after the other stops, or when one's debits fall inside the other's span on days without its debits. The real ledger joins KAPITUS SERVICIN into KAPITUS on the third rule. ZLUR FUNDING LLC shares a day with ZLUR FUNDING, so it stays separate (U, $1,980 STRESS). **Signed off 2026-11-07, kept.** |
| B13 | D1 finance language | Word matches, plus CAPITAL, FUNDING, FINANC, LENDING, ADVANCE or MERCHANT inside a token. This finds HEADWAYCAPITAL and FORWARD FINANCIN. It also nominates EMPIRE MERCHANTS (a liquor distributor) until the model answers. **Signed off 2026-11-07, kept.** |
| B14 | Monthly cadence x1 | Gaps of 18 to 25 business days. A fixed monthly series with a finance word is MCA by default (HEADWAYCAPITAL, $7,442/mo, silent since 03/31/26, so U). **Signed off 2026-11-07, kept.** |
| B15 | WATCH rows in Table 4b | Peak load counts positions only. WATCH debits stay out because their identity is unproved. **Signed off 2026-11-07, kept.** |
| B16 | Evidence levels | CORROBORATED: an attached funding with a bank-text, document or named-funder gate, or closure evidence. OBSERVED: a finance word in the payee. INFERRED: the model or a cadence rule says MCA with no finance word. UNKNOWN: WATCH. Strip gates map `bank_text` to OBSERVED, `document` and `named_funder_series` to CORROBORATED, and `sender_identified` to INFERRED. **Signed off 2026-11-07, kept.** Since M9 (V1.8b8) `sender_identified` never gates, so no strip carries INFERRED. |

Not in batch 2: same-day same-amount doubles stay one position (D8, HANDOFF interpretation 14); off-bank collections (D6, T7); contractual cost and payoff ties (L11, L13); variable adverse scenarios (D11); alternative tags (T1); new-sender ACH and mobile credits (C2).

## Batch 2 effect on saved runs

| Run | Batch 1 | Batch 2 |
| :--- | :--- | :--- |
| Sample, no answers | INSUFFICIENT DATA, $11,577; 4 positions | Same; 5 payees nominated, 0 WATCH |
| Sample, saved answers | INSUFFICIENT DATA, $5,217 | Same |
| Real ledger, no answers | INSUFFICIENT DATA, $74,570; 5 positions | Same HEADLINE. 6 positions and 6 WATCH rows (KAPITUS, ACCORD BUSINESS, CAPITAL ONE, DOORDASH CAPITAL, EMPIRE MERCHANTS, ZLUR FUNDING LLC); HEADWAYCAPITAL found as an MCA position. 85 questions (was 81). |
| Real ledger, saved answers | INSUFFICIENT DATA, $44,882 | Same HEADLINE. KAPITUS SERVICIN joins KAPITUS; ZLUR FUNDING LLC becomes ZLUR FUNDING #2 (U). 6 new questions are unanswered by the saved file. |

## Batch 3 interpretations for sign-off

| # | V1.7 text | Engine reading |
| ---: | :--- | :--- |
| B17 | "Months require >=18 covered days on the material revenue/collection accounts" | A material account holds 5% or more of all credits. Its short months inside its own statement span exclude the month. Months before its first statement or after its last are not held against it, because the engine cannot tell an account that did not exist from one that was not supplied. **Signed off 2026-11-07, kept.** |
| B18 | REQUEST REQUIRED, VERIFY OWNERSHIP, and "material missing accounts ... INSUFFICIENT DATA" | Any account named in transfer text and not supplied is listed when its transfers recur (2+), it is a financing account (LOC, credit line, loan), or it moves 5% of BASIS per month. Two-way transfers give VERIFY OWNERSHIP. A listed account moving 5% of BASIS or more per month blocks YES. **Signed off 2026-11-06, changed:** a NO stands, because hidden MCA payments can only lower HEADLINE (V1.7b5). |
| B19 | CONFIRMED vs POSSIBLE personal items | CONFIRMED = OWNER_DRAW debits and STRIP_OWNER credits. These come from the supplied owner names, transfers to the owner, or a model answer. POSSIBLE = Zelle, Venmo and Cash App debits, plus consumer merchants (grocery, streaming, gym, salon, mortgage, HOA). Possible items never set the status. **Signed off 2026-11-07, kept.** |
| B20 | Transfers paying a credit line | A transfer whose text names a LOC, credit line, line of credit or loan is DEBT_SERVICE, so it counts in obligations. On the real ledger, $75,672 to NST Credit Line 6298 adds about $5,800/mo to obligations, and HEADLINE drops from $44,882 to $39,061. **Signed off 2026-11-07, kept.** |
| B21 | Class UNKNOWN | A return credit (return wording or an R-code) with no matching debit. **Signed off 2026-11-07, changed:** it is Class A. The debit is unknown and may be essential, so the tier is T1 for a T1 code and T2 otherwise; cure is "N (debit not found)". |

Not in batch 3: account identity beyond the last four digits (S5), per-file source records (R1), ownership evidence (R2), alternative tags (T1), pending rows as observations (S3).

## Batch 3 effect on saved runs

| Run | Batch 2 | Batch 3 |
| :--- | :--- | :--- |
| Sample, no answers | INSUFFICIENT DATA, $11,577 | Same. Commingling Present — Low (4 owner draws, $8,000); accounts COMPLETE OBSERVED |
| Sample, saved answers | INSUFFICIENT DATA, $5,217 | Same |
| Real ledger, no answers | INSUFFICIENT DATA, $74,570 | INSUFFICIENT DATA; adds REQUEST REQUIRED for TD Convenience Checking ...1272 ($101,390 out, material) and NST Credit Line ...6298, and VERIFY OWNERSHIP for CHK ...1563 |
| Real ledger, saved answers | INSUFFICIENT DATA, $44,882 | INSUFFICIENT DATA, $39,061 (credit-line transfers now count as debt service); same account requests |

## Batch 4 fixes

A spec review on 2026-11-02 found 10 rows marked Met, B1 or B3 that the code did not meet. Each fix has a test in `V17Batch4` that fails on batch 3.

| Row | Batch 3 behaviour | Batch 4 |
| :--- | :--- | :--- |
| K3 | Peak Handled showed the observed week even below current load; drop could be negative | Report Peak = max(observed, modeled current); holdback over a counted month |
| L6, A5 | Closure quote matched anywhere in the ledger text | Quote must sit on the payee's or funder-named transaction; later cleared debits override it |
| K7 | MCA and loan returns were T2 only with R01 or R09 | All non-T1 returns on finance and essentials are T2 |
| M8 | Every wire scored +2 | Only funder-named or finance-worded wires |
| V10 | Zero headline did not name the room; conservative binding shown only at zero | Both stated |
| P5, L4 | Live window held 11 business days | 10, counting the end day |
| K2 | Holiday weeks with 4 business days were eligible | Skipped |
| K8 | Loan stop-pays could show cured | Never cured |

Not in batch 4: report publication after rejected answer files (V3 handoff, done in PR #14), the stage manifest (V3 handoff), and B18 (signed off 2026-11-06: missing accounts block YES only; PR #16, V1.7b5).

## Batch 4 effect on saved runs

| Run | Batch 3 | Batch 4 |
| :--- | :--- | :--- |
| Sample, no answers | INSUFFICIENT DATA, $11,577 | Same; binding adds "CONSERVATIVE: Room D (worst month Jun-26)" |
| Sample, saved answers | INSUFFICIENT DATA, $5,217 | Same; CFG funding match falls from HIGH 5 to MED 3 (the JKL customer wire loses +2) |
| Real ledger, no answers | INSUFFICIENT DATA, $74,570 | Same; binding adds "CONSERVATIVE: Room D (worst month Feb-26)" |
| Real ledger, saved answers | INSUFFICIENT DATA, $39,061 | Same; binding adds the conservative room |

## B5: credit coverage (open item 7, first batch; policy V1.7b6)

| Row | Change |
| :--- | :--- |
| C2 | New senders on ACH, transfers, deposits and checks become funding candidates. Unanswered, they default to STRIP_UNRESOLVED like any candidate. |
| A2 | Every cleared credit carries one disposition in `audit.credit_dispositions`, checked by a self-check. |

| Run | Before | After |
| :--- | :--- | :--- |
| Sample, both runs | — | Same report |
| Real ledger, both runs | HEADLINE $74,570 / $39,061 | Same HEADLINE. ADP TAX 03/09/26 $168.50 becomes a candidate: one more question, Mar-26 True Revenue $79,721 to $79,553 (outside the BASIS months) |
| Real ledger, saved answers | — | Dispositions: 1,030 CUSTOMER_SUPPORTED, 30 OTHER_SUPPORTED, 15 FINANCING_UNATTACHED, 6 ATTACHED, 2 COMPETING, 1 UNRESOLVED |

## B6: debit side (open item 7, second batch; policy V1.7b7)

| Row | Change |
| :--- | :--- |
| D8 | Same-amount doubles on 3 consecutive debit days split a series into two positions. Isolated doubles stay catch-up payments. |
| M14 | A same-funder restart within 10 bd of the stop is a PROBABLE RENEWAL event. |
| D11 | VARIABLE positions carry `adverse_cost` and a Table 4 note when it exceeds the observed cost. |

| # | V1.7 text | Engine reading |
| ---: | :--- | :--- |
| B22 | "Track different concurrent schedules under one funder as separate POSITION IDs" | Same-amount doubles count as a second schedule only on 3 consecutive debit days. On the real ledger, MS Equities, Eminent and ZLUR show doubles only on the business day after Memorial Day and Juneteenth (and 2 other single days); these stay one position each. **Signed off 2026-11-07, kept.** |

| Run | Effect |
| :--- | :--- |
| Sample, both runs | Same report |
| Real, no answers | Same positions and HEADLINE. Adverse notes: CAPITAL ONE $9,947, EMPIRE MERCHANTS $8,976, DOORDASH CAPITAL $1,323 (all U, not in stack) |
| Real, saved answers | Same positions and HEADLINE $39,061. Adverse notes: REWARDS NETWORK $6,434 against $3,374 observed; DOORDASH CAPITAL $1,323 against $934 |

## B7: records (open item 7, third batch; policy V1.7b8)

| Row | Change |
| :--- | :--- |
| R1 | `audit.sources`, one record per supplied file |
| R3 | `sequence`, `source_ref` with row number, `orig_id`, `trace_id` on each transaction record. `ORIG_ID` now matches `ORIG ID **318418` (no colon, masked), which the real ledger prints. |
| R7 | `audit.exceptions` |
| S3 | `audit.pending_observations` |
| S7 | `audit.duplicate_crosswalk` and the page's `rowsOmitted` note in the source record |

| Run | Effect |
| :--- | :--- |
| Sample, both runs | Same report |
| Real, no answers | Same report and HEADLINE. 2,147 trace IDs and 2,057 originator IDs read (0 originator IDs before); 105 exception records (86 open questions, 11 U positions, 6 account requests, 1 VERIFY OWNERSHIP, 1 unresolved credits) |
| Real, saved answers | Same HEADLINE $39,061. The KAPITUS to KAPITUS SERVICIN descriptor change now joins on "shared originator ID" (was "debits fill open slots"); 21 exception records |

## Sign-offs B1, B4, B5, B6 (2026-11-07; policy V1.7b9)

B1 changed: `UNRESOLVED_FLOOR = D("2500")`. An unanswered or "unsure" candidate credit under $2,500 keeps its rule tag and stays in revenue. Its disposition stays UNRESOLVED. B4, B5 and B6 are kept as written.

| Run | Effect |
| :--- | :--- |
| Sample, both runs | Same report |
| Real, no answers | STRIP_UNRESOLVED $244,097 in 14 months to $230,179 in 12. BASIS $137,284 to $137,951. HEADLINE $74,570 to $74,970. Still INSUFFICIENT DATA |
| Real, saved answers | Same HEADLINE $39,061. ADP TAX 03/09/26 $168.50 (the 1 open question) stays in revenue: Mar-26 True Revenue $79,553 to $79,721 |

## Sign-offs B7, B9, B11, B12 (2026-11-07; policy V1.7b10)

B7 changed: U positions are tested one by one. The "U positions combined" test is removed. It also crashed the run: `exceptions()` read an `amount` key that the combined row did not have. B9 changed: D3 links a payee with 2+ debits at an MCA series' amount within 30 days, however many other debits the payee has. B11 and B12 are kept as written.

| Run | Effect |
| :--- | :--- |
| Sample and real, both runs | Same reports. No saved run had a combined U test or a D3 link that the half-of-payee rule blocked |

## Sign-offs B13 to B17, B19 to B21 (2026-11-07; policy V1.7b11)

B21 changed: a return credit with no matching debit is a Class A return, T1 for a T1 code and T2 otherwise, never cured. Table 9 still prints an UNKNOWN count; it is now always 0. B13, B14, B15, B16, B17, B19 and B20 are kept as written. All 22 interpretations B1 to B22 are now signed off.

| Run | Effect |
| :--- | :--- |
| Sample and real, both runs | Same reports. No saved run has a return credit without its debit |

## V1.8 batch 1: return conflicts (2026-11-07; policy V1.8b1)

V1.8 (MCA Capacity V1.8 Character Returns Enhanced) replaces V1.7. Its capacity rules match V1.7. Its return rules conflicted with the engine in 3 places, fixed here:

| Row | V1.7 engine | V1.8 engine |
| :--- | :--- | :--- |
| K7 | Any stop/block code was T1, vendor items included | T1 only on MCA or loan. Payroll, rent, tax or insurance gives n/a. Other items give T3 |
| K6 | Unmatched return credit was T1 by code, else T2, cure N | Tier n/a, cure UNKNOWN. Still Class A per B21 |
| K8 | Missing balance or missing follow-up gave cure N | Cure UNKNOWN. A re-presentment into overdraft is N |

The checker now requires a Class A cure of Y, N or UNKNOWN and rejects a cured T1 row. Table 9 and the WILL-PAY line now count tier n/a and cured, uncured and unknown cures.

| Run | Effect |
| :--- | :--- |
| Sample and real, both runs | Same numbers. Table 9 detail and the WILL-PAY line gain the n/a and cure counts |

Not in this batch: the V1.8 return-word scan log (R1), the character pass (B1 to B5) and the extra Table 4 and Table 9 detail.

## V1.8 batch 2: return-word scan (2026-11-07; policy V1.8b2)

V1.8 R1 asks for a record of every row with return wording, each linked to a return event or dismissed with a reason.

- `RETURN_SCAN` matches STOP PAY, STOP PAYMENT, UNAUTHORIZED, NOT AUTH, AUTH REVOKED, ACH BLOCK, POSITIVE PAY, NSF, INSUFFICIENT FUNDS, UNCOLLECTED, RETURN, RETURNED, RETURN ITEM, REVERSAL, REVERSED, RECREDIT, CHARGEBACK and codes R01, R05, R07, R08, R09, R10, R29. Any other R-code counts only when the row also says ACH or RETURN. Every STRIP_RECREDIT row gets a record whatever its wording.
- `audit.return_scan` holds one record per hit: transaction, account, date, description, amount, matched word, disposition and reason.
- Dispositions: EVENT (linked to a Table 7 row), FEE (an NSF/OD fee, counted in Table 9 fees), DISMISSED (reason names the tag and that no returned attempt is linked).
- 2 new self-checks: every hit has a disposition and reason; every Table 7 Class A return row is a hit.
- Stage 9 counts hold the hit total by disposition.

| Run | Effect |
| :--- | :--- |
| Sample, both runs | Same reports. 2 hits: 1 EVENT, 1 FEE |
| Real, both runs | Same reports. 5 hits, all DISMISSED: a bank claim reversal (credit $2,965 and debit $515) and 3 fee reversals of $34 |

The scan reads only supplied rows. Missing pages or accounts limit it, and a scan with no hits is not proof of no returns.

## V1.8 batch 3: character evidence, part 1 (2026-11-07; policy V1.8b3)

V1.8 B1 to B3 evidence, computed by code and kept in `audit.character_evidence`. Nothing in the report changes. Labels (B4, B5) come in part 2 through the judge prompt.

- `collections` (B1): for each established or probable position with a daily, weekly, biweekly or monthly cadence, expected pulls from the first to the last observed attempt, cleared days, returned days and missing pulls. Cause is always UNKNOWN. Not computed for VARIABLE or PROVISIONAL cadence, for a payment or schedule change inside the interval, or for a statement gap (weekly and longer). Daily counts covered business days only.
- `thin_days` (B2): per account, the 5 lowest EOD dates (`THIN_DAY_COUNT`) plus every Class A return date. Each lists cleared finance and essential debits, returns, owner injections (STRIP_OWNER) and owner or transfer outflows, with a flag when a finance return and an outflow share a day. EOD only: same-day order is unknown.
- `sweeps` (B3): external deposit, then an owner draw or transfer out within 2 days (`FLIGHT_DAYS`), then a Class A return on MCA or loan within 5 business days of the outflow (`SWEEP_RETURN_BD`). Destination is "supplied account" when the outflow names another supplied account's last four, else "outside or unknown". Timing only.
- 2 self-checks: every cited transaction is in the ledger; every sweep ends in a Table 7 Class A finance return.

`SWEEP_RETURN_BD` = 5 is an interpretation; V1.8 gives no window. It needs sign-off.

| Run | Effect |
| :--- | :--- |
| All 4 saved runs | Same reports |
| Real | 7 of 10 positions computed. Kapitus 56 of 56 weekly, Forward Financing 167 of 167 daily, Accord 49 of 50, MS Equities 57 of 58. 5 thin days, EOD -$171.66 to -$4,192.82; no returns, so 0 sweeps |
| Sample | BlueOak 6 of 7 weekly, SunCap 19 of 19 daily, CFG 4 of 4 |

## V1.8 batch 4: character labels, part 2 (2026-11-07; policy V1.8b4)

V1.8 B4 and B5: the judge picks the character and failure-mode labels from the batch 3 evidence. Code limits which labels the evidence can support.

- The engine adds a `character` question only when a judgments file is supplied, so its evidence reflects the MCA answers. The page asks it in one extra model call and merges the answer into the same judgments file. A rejected or failed character answer keeps the earlier report, with a note.
- The question id hashes the evidence. An answer given against older evidence is rejected as stale.
- Allowed labels: LOW is barred when a coverage limit exists (material missing account or unreadable statement) or a finance T1 return is uncured. HIGH needs a finance T1 return or 2 or more sweep sequences. POSSIBLE VOLITIONAL and MIXED need at least one Class A finance return.
- The answer carries `tag` (character), `failure_mode` and `text` (at most 400 characters). The WILL-PAY line becomes "Character X; failure-mode evidence Y (model reading of engine evidence; capacity verdict independent). text Counts: ...". Unanswered, it reads "Character INDETERMINATE; failure-mode evidence INDETERMINATE (not assessed)."
- The character question is not counted as an open question (Table 1, status line, exception records) and is not in the review queue yet.
- `judge.md` V3.1 adds the `character` section. `judgments.schema.json` adds `failure_mode`, the `character` id prefix and a 400-character `text`.

| Run | Effect |
| :--- | :--- |
| All 4 saved runs | Only the WILL-PAY line changes: "Character INDETERMINATE ... (not assessed). Counts: ..." The saved judgments hold no character answer |

## V1.8 batch 5: report detail (2026-11-07; policy V1.8b5)

`SWEEP_RETURN_BD` = 5 signed off 2026-11-07, kept as written.

- Table 4 Notes, per position: "Returns: N Class A (tiers); cured, uncured, unknown" when the position has a verified return. "Collections X of Y expected <cadence> pulls <first> to <last>" when batch 3 computed an expected count, with "N missing, cause unknown (not a return)" when pulls are missing.
- Table 9 FLIGHT detail: "sweep-to-return N:" with deposit, outflow and returned-attempt dates for up to 3 sequences, then "timing only, intent not shown". With none: "sweep-to-return: none".

| Run | Effect |
| :--- | :--- |
| Real, saved answers | 7 positions gain a Collections note; Accord 49 of 50 and MS Equities 57 of 58 show 1 missing each. FLIGHT detail ends "sweep-to-return: none" |
| Sample | BlueOak 6 of 7 (1 missing), CFG 4 of 4, SunCap 19 of 19 |

Found, not changed: the cure rule (K8) accepts any later debit to the same payee of equal or higher amount within 2 bd. For a daily MCA, the next scheduled pull counts as the cure of a returned pull. V1.8 R4 asks for a re-presentment of the same obligation.

## V1.8 batch 6: cure needs an extra pull (2026-11-08; policy V1.8b6)

Signed off 2026-11-08, "extra pull". A daily position's next scheduled pull no longer cures a returned pull. Inside the 2 bd window, only a pull beyond the schedule counts: a second same-payee pull on one day, or one pull of at least the regular level plus the returned amount. Weekly and slower payees keep the old rule, because their next regular pull falls outside 2 bd.

| Run | Effect |
| :--- | :--- |
| All 4 saved runs | Same reports. No saved run has a return on a daily position |

## V1.8 batch 7: character labels in the review queue (2026-11-08; policy V1.8b7)

- The review queue lists a "Character read" row whenever the character question exists, answered or not. It shows the current WILL-PAY labels, a character menu and a failure-mode menu limited to the engine's allowed labels, and a text box.
- A pick replaces the model's character answer in the judgments file; a blank character menu keeps it. The engine still checks the labels against the evidence.
- WILL-PAY names who set the labels: "(model reading ...)" or "(underwriter reading ...)" when the answer's reason is "underwriter".
- The open-question count leaves the character row out.

| Run | Effect |
| :--- | :--- |
| All 4 saved runs | Same reports |

## Sign-offs P15 and M9 (2026-11-08; policy V1.8b8)

- P15, changed: FLIGHT tests every external credit of at least 3x the median deposit. External leaves out STRIP_TRANSFER, STRIP_REFUND, STRIP_RECREDIT, STRIP_OWNER and returned credits; it is the same test the V1.8 sweep evidence uses (`is_external_credit`). Before, only funding candidates and STRIP_FUNDING credits were tested, so a large deposit from an established customer was skipped.
- M9, changed: a `sender_identified` STRIP_FUNDING answer is not proof of financing. The credit becomes STRIP_UNRESOLVED at any amount, stays out of revenue, and attaches to no position. Table 1 notes "out of revenue as STRIP_UNRESOLVED, not proof of financing; verify with bank text or a document". A rule gate (financing text or a named funder series) on the same credit still makes it STRIP_FUNDING. The B2 add-back test now covers these credits.

| Run | Effect |
| :--- | :--- |
| Sample, defaults and saved answers | Same reports. FLIGHT events stay at 2; no saved answer uses `sender_identified` |
| Real ledger, defaults and saved answers | Not rerun: the ledger is not in this session. FLIGHT count may rise; HEADLINE cannot move from P15. M9 moves funding links only if a saved answer uses `sender_identified` |
