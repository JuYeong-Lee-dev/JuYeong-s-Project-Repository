# SQL Analytics

**HD Hyundai Marine Solution Europe · Analytical SQL work built and used in production**

A collection of analytical queries written against a PostgreSQL data warehouse covering order history, customer behaviour, and stock fulfillment patterns. All queries use CTEs throughout for readability and logical decomposition.

---

## Analyses

### [NL Stock Procurement Priority](./nl-stock-procurement-priority/)

A four-step sequential analysis to identify which materials should be added to NL revolving stock — using 2021–2024 delivery history as evidence.

| Step | File | What it does |
|---|---|---|
| 1 | `1_order_classification.sql` | Classifies every order as NL-fulfilled, KR-fulfilled, or Split |
| 2 | `2_split_kr_materials.sql` | Within Split orders, extracts lines that went via KR stock |
| 3 | `3_nl_holdings_crosscheck.sql` | Cross-references those materials against NL stock history |
| 4 | `4_nl_procurement_priority.sql` | Ranks materials with no NL history appearing in 3+ Split orders |

**Business problem:** Orders were frequently split between NL and KR fulfillment, meaning NL stock couldn't fully cover demand. This analysis identifies — with historical evidence — which specific materials NL should stock to reduce reliance on KR and shorten lead times.

**Output:** A ranked priority list for procurement, ordered by how frequently a material appeared in Split orders without ever being held in NL stock.

---

### [Shipping Company Demand Pattern Analysis](./shipping-pattern-analysis.sql)

Identifies high-value shipping companies whose vessels have placed qualifying orders (≥ USD 20,000) across multiple months. Output is joined with RFM customer grades and vessel delivery dates, providing a foundation for targeted sales and stocking strategies.

**Techniques:** Multi-CTE filtering, window-based aggregation, LEFT JOINs across three tables, HAVING clause logic for multi-month activity detection.

---

### [Quote-to-Order Gap Analysis](./quote-order-gap-analysis.sql)

Finds vessel/material combinations that received a quote in 2025 but resulted in no contract — using a set difference (`EXCEPT`) to isolate unconverted opportunities. Aggregates quoted vs. contracted amounts per vessel and material category for prioritised follow-up.

**Techniques:** Set difference with `EXCEPT`, NULL-safe JOIN conditions, aggregation with multiple `COUNT(DISTINCT ...)`, multi-table joins.

---

## Technical Stack

PostgreSQL · CTEs · Set operations · Multi-table JOINs

---

> Table and column names have been translated from the original Korean ERP schema for readability. No actual data is included.
