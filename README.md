# JuYeong Lee — Data Portfolio

Data analyst with hands-on experience building production ML systems and operational data pipelines in a European MRO supply chain environment. Projects here were designed, built, and deployed in a real business context — not academic exercises.

---

## Projects

### [Branch-Level Demand Forecasting System](./Demand%20Forecasting/)
`Sep 2025 – Apr 2026 · Two-person team · Adopted by management`

End-to-end forecasting system for ~7,000 SKUs across a 12-month horizon. Built from scratch after identifying that the incumbent approach — a single global XGBoost model with no demand pattern distinction — was structurally unsuited to a portfolio where 70%+ of SKUs are intermittent or lumpy.

The system segments SKUs by demand pattern (Smooth / Erratic / Intermittent / Lumpy) using the Syntetos-Boylan framework, routes each SKU to the appropriate model (TSB, SARIMA, or two-stage LightGBM), and selects the best performer per SKU at inference time via a test-set ensemble. Ensemble MASE < 1 across all demand pattern clusters.

`Python · LightGBM · pmdarima · Optuna · scikit-learn · PostgreSQL`

---

### [NL Warehouse Stock Utilization](./stock-utilization/)
`HD Hyundai Marine Solution Europe`

Automated daily pipeline that identifies high-value open orders (≥ USD 5,000) where NL warehouse stock is sufficient for local fulfillment — opportunities the team was missing due to no systematic detection process. Outputs a line-item detail report and an aggregated email summary for daily team use.

| Metric | Before | After |
|---|---|---|
| NL Stock Utilization Rate | 20–23% | 25–28% |
| Stock Turnover | 1.3 | 1.75 |

`Python · pandas · SQLAlchemy · PostgreSQL · Excel I/O`

---

### [Slow-Moving Stock Detection Pipeline](./slow-moving-stock-detection/)
`HD Hyundai Marine Solution Europe · Daily operational use`

A three-step daily pipeline that cross-references incoming quote files against the warehouse's slow-moving and excess stock inventory. For each vessel with a total quoted value ≥ USD 10,000, the pipeline detects whether applicable slow-moving items are already in the quote (matched) or could be proposed (applicable). Output became the basis for targeted promotion strategies developed with the sales team, reducing designated slow-moving stock from 100+ items to under 80 — a reduction of over 20%.

`Python · pandas · xlsxwriter · PostgreSQL · SQL`

---

## Core Skills

| Area | Tools & Methods |
|---|---|
| Machine Learning | LightGBM, scikit-learn, Optuna, time series forecasting |
| Statistical Modelling | TSB, SARIMA, demand pattern classification |
| Data Engineering | Python, pandas, SQLAlchemy, PostgreSQL, SQL |
| Automation | Daily pipelines, Excel report generation, operational tooling |
| Evaluation | MASE, WAPE, cross-validation, ensemble selection |

---

*More projects in progress.*

---

## Note on Privacy & Credentials

All code and queries in this repository have been sanitised for public sharing. Database credentials, internal system names, and personal file paths have been replaced with environment variables or generic placeholders. No actual company data is included — only logic, structure, and methodology.
