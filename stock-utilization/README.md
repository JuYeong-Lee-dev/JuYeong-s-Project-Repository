# NL Warehouse Stock Utilization Improvement

## Business Context

HD Hyundai Marine Solution Europe (HMS-EU) operates a spare parts warehouse in the Netherlands (NL) serving vessel maintenance, repair, and operations (MRO) orders across Europe.

**Problem:** Company order volume grew steadily over 5 years, but NL warehouse stock utilization remained flat at ~20–23%. This meant the NL warehouse was underperforming as a regional fulfillment hub — orders that could have been fulfilled locally were being sourced from HQ in Korea (KR), increasing lead times and logistics costs.

**Root cause identified:** No systematic process existed to detect high-value open orders where NL stock was already sufficient to fulfill them — these opportunities were being missed daily.

---

## Solution

A daily automated detection pipeline that:

1. Loads the latest order progress report (`공사진행.xlsx`) into a local PostgreSQL instance
2. Identifies **high-value orders (≥ USD 5,000)** where:
   - Delivery condition is EXB (Ex-Basis, NL-fulfillable)
   - Order type excludes Repair orders and Tech team
   - NL stock covers ≥ **50%** of order value for HD spare orders (`RKB%`)
   - NL stock covers ≥ **30%** of order value for main engine spares
3. Flags a special case: any order containing a specific critical U-CODE item (`U17H2100000`) under EXB terms
4. Outputs two reports:
   - **Detail report** — full line-item view for logistics review
   - **Email summary report** — aggregated per order for daily team communication

---

## Impact

| Metric | Before | After |
|---|---|---|
| NL Stock Utilization Rate | 20–23% | 25–28% |
| Stock Turnover | 1.3 | 1.75 |

Findings from this detection are used daily to **transit sales fulfillment from KR to NL**, and to support bonus/promotion decisions tied to NL stock consumption.

---

## Technical Stack

- **Python** — pandas, SQLAlchemy
- **PostgreSQL** — local instance for SQL-based filtering logic
- **SQL** — CTE-based filtering with conditional HAVING clauses
- **Excel I/O** — input from ERP export, output to formatted `.xlsx`

---

## Repository Structure

```
stock-utilization/
├── 1_stock_utilization_email_report.py   # Aggregated summary for daily email
├── 2_stock_utilization_detail_report.py  # Full line-item detail for review
└── README.md
```

---

## How to Use

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your DB credentials
```

1. Set `FILE_DATE` to today's date in `YYMMDD` format (e.g., `"260216"`)
2. Place the ERP export at: `RAW/{FILE_DATE}_공사진행.xlsx`
3. Ensure PostgreSQL is running locally
4. Run either script — output saves to the configured output directory

---

## Business Logic Notes

- **EXB (Ex-Basis):** Delivery from NL warehouse — the condition this pipeline targets
- **RKB orders:** HD spare parts with a stricter 50% NL fulfillment threshold
- **Special case U17H2100000:** A critical engine component flagged regardless of order value thresholds
- **≥ USD 5,000 filter:** Focuses effort on orders where NL fulfillment has meaningful financial impact
