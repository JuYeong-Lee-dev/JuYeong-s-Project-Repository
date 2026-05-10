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

## Core Skills

| Area | Tools & Methods |
|---|---|
| Machine Learning | LightGBM, scikit-learn, Optuna, time series forecasting |
| Statistical Modelling | TSB, SARIMA, demand pattern classification |
| Data Engineering | Python, pandas, SQLAlchemy, PostgreSQL, SQL |
| Evaluation | MASE, WAPE, cross-validation, ensemble selection |

---

*More projects in progress.*
