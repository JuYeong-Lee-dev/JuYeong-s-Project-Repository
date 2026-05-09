# NL Warehouse Stock Utilization Improvement

## Business Context

HD Hyundai Marine Solution Europe (HMS-EU) operates a spare parts warehouse in the Netherlands (NL) serving vessel maintenance, repair, and operations (MRO) orders across Europe.

**Problem:** Company order volume grew steadily over 5 years, but NL warehouse stock utilization remained flat at ~20–23%. This meant the NL warehouse was underperforming as a regional fulfillment hub — orders that could have been fulfilled locally were being sourced from HQ in Korea (KR), increasing lead times and logistics costs.

**Root cause identified:** No systematic process existed to detect high-value open orders where NL stock was already sufficient to fulfill them — these opportunities were being missed daily.

---

## Solution

A daily automated detection pipeline that identifies **high-value open orders (≥ USD 5,000)** where NL stock is already sufficient for local fulfillment, but the opportunity is being missed.

**Filtering logic:**
- Delivery condition is EXB (Ex-Basis, NL-fulfillable)
- Excludes Repair orders and Tech team orders
- NL stock covers ≥ **50%** of order value for HD spare orders (`RKB%`)
- NL stock covers ≥ **30%** of order value for main engine spares
- Special case: any order containing critical component `U17H2100000` under EXB terms is always flagged

**Outputs two daily reports:**
- **Detail report** — full line-item view for logistics review
- **Email summary** — aggregated per order for daily team communication

---

## Impact

| Metric | Before | After |
|---|---|---|
| NL Stock Utilization Rate | 20–23% | 25–28% |
| Stock Turnover | 1.3 | 1.75 |

Findings are used daily to **transit sales fulfillment from KR to NL**, and to support bonus/promotion decisions tied to NL stock consumption.

---

## Technical Stack

- **Python** — pandas, SQLAlchemy
- **PostgreSQL** — local instance for SQL-based filtering logic
- **SQL** — CTE-based filtering with conditional HAVING clauses
- **Excel I/O** — input from ERP export, output to formatted `.xlsx`
