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

This pipeline runs daily and is used to drive targeted outreach — proposing relevant slow-moving items to customers already engaged in active quote discussions, increasing the likelihood of stock liquidation without additional sales effort.

---

## Technical Stack

Python, pandas, xlsxwriter, PostgreSQL, SQL
