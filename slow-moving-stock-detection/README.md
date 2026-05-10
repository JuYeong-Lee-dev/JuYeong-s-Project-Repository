# Slow-Moving Stock Detection Pipeline

**HD Hyundai Marine Solution Europe · Operational automation in daily use**

---

## Problem

The warehouse carried a portfolio of slow-moving and excess stock — parts classified as `Excess` or `Malignity` — that were tying up capital with no clear path to liquidation. At the same time, the team was receiving daily quote requests from European shipping companies. The opportunity existed to match incoming quotes against applicable slow-moving stock, but there was no systematic way to detect this daily.

Identifying these opportunities manually across hundreds of daily quote lines was not feasible.

---

## Solution

A three-step daily pipeline that cross-references incoming quotes against the slow-moving stock inventory and produces an actionable output for the sales team.

```
daily_quote.xlsx  ──►  1_detect_vessels.py   ──►  [detection output]
                   ──►  2_pull_quote_details.py ──►  [full line-item detail]
                   ──►  3_generate_report.py   ──►  [formatted Excel report]
```

**Step 1 — Vessel Detection** (`1_detect_vessels.py`)

Filters for vessels with a total quoted value ≥ USD 10,000 and checks whether any quoted U-CODEs match the slow-moving stock list for that vessel. Flags each vessel as `MATCHED` (item already in the quote) or `APPLICABLE — NOT QUOTED` (item could be proposed).

**Step 2 — Quote Detail Pull** (`2_pull_quote_details.py`)

Takes the flagged vessel list from Step 1 and extracts the full quote line-item data for those vessels, ready for targeted sales follow-up.

**Step 3 — Slow-Moving Report** (`3_generate_report.py`)

Independently generates a formatted daily Excel report of all slow-moving stock items (≥ USD 500) present in the day's quote file. Excludes items tied to active construction orders. Output is formatted for direct team distribution.

**Supporting SQL** (`european_vessels_filter.sql`)

Filters the detection scope to European shipping companies only, joining against vessel info by Group Owner Country.

---

## Impact

| Metric | Before | After |
|---|---|---|
| Detection process | Manual search through daily quote Excel | Automated daily pipeline |
| Designated slow-moving item count | 100+ items | Under 80 items (>20% reduction) |

Before this pipeline, identifying applicable slow-moving stock required manually scanning through daily quote files — an effort that was inconsistent and easy to miss. After automating detection, the output was shared with the sales team and became the basis for targeted promotion strategies. The result was a reduction in designated slow-moving stock from over 100 items to under 80, a reduction of more than 20%.

---

## Technical Stack

Python, pandas, xlsxwriter, PostgreSQL, SQL
