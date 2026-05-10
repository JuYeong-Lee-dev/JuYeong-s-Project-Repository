# Branch-Level Demand Forecasting System

**Sep 2025 – Apr 2026 · Two-person team · Presented to and adopted by management**

---

## Repository Structure

```
demand-forecasting/
├── README.md
├── k-mean-clustering.py                # Stage 1: K-Means material segmentation
├── Croston_ARIMA.py                    # Stage 2: Statistical model (TSB / SARIMA)
├── LightGBM.py                         # Stage 2: ML model (two-stage LightGBM)
└── shared_metrics_en.py                # Shared evaluation metrics (MASE, WAPE, Relative Bias)
```

---

## Background

The branch had been using an ETS model for procurement planning with no formal performance tracking. A predecessor built an XGBoost model as an improvement, but it applied a single global model to all 7,000+ SKUs without any distinction by demand pattern. Over 70% of the branch portfolio is intermittent or lumpy demand — spare parts that go months without a single order. Applying one model uniformly across a portfolio of this composition is not a tuning problem. It is a model selection problem. The result was WAPEs consistently above 0.5.

The HQ forecasting system was not an option either. It was designed around HQ's portfolio structure and did not reflect branch-level demand behavior.

Previous attempts had shown that the problem needed a different approach entirely. This project was the first time that approach was fully designed and built from scratch — from data pipeline to production deployment — with every architectural decision made deliberately and every component validated before use.

---

## My Role

I was responsible for the full data cleaning and validation pipeline, and led development of the LightGBM model. My partner built the statistical models (TSB and SARIMA). We jointly designed the overall system architecture, evaluation framework, and ensemble strategy.

---

## System Design

**Stage 1 — Material Segmentation**
`k-mean-clustering.py`

Before any forecasting work, we clustered all SKUs using K-Means (k=4) on three features derived from 2021–2025 order history: average monthly order frequency, average monthly quantity, and coefficient of variation. IsolationForest removed outliers prior to clustering, and PCA reduced multicollinearity before K-Means was applied. Optimal k was selected via Silhouette analysis and validated with Calinski-Harabasz and Davies-Bouldin scores. Each cluster receives a demand grade (A–D) benchmarked against the HQ grading system.

This gives a principled, data-driven foundation for ordering decisions across the full portfolio.

**Stage 2 — Demand Pattern Classification**
`Croston_ARIMA.py` · `LightGBM.py` · `shared_metrics_en.py`

Each SKU is classified into one of four demand patterns: Smooth, Erratic, Intermittent, or Lumpy. Classification uses the Syntetos-Boylan framework, computing ADI (Average Demand Interval) and CV² from the active demand window only — starting from the first non-zero observation rather than the full series. This prevents newly introduced SKUs from being misclassified due to leading zeros inflating their ADI. The ADI threshold of 1.32 is mathematically derived from Syntetos and Boylan (2005) and was not tuned.

Classification determines which model each SKU is routed to. Two models run in parallel across the full portfolio.

**Statistical Model**

For Intermittent and Lumpy SKUs, we used TSB (Syntetos-Boylan-Teunter). For sparse, irregular demand patterns, statistical methods with explicit demand probability modelling are well established to be more reliable than ML approaches. TSB parameters are optimised via Optuna using internal cross-validation only — the validation set is never seen during tuning, preventing hyperparameter leakage.

For Smooth and Erratic SKUs, SARIMA runs with three candidate structures (AIC-optimal, Simple Trend, Seasonal Naive). The best candidate is selected on held-out validation MAE before the final model is refit on the full training history.

**LightGBM Model**

A two-stage architecture: a binary classifier estimates demand occurrence probability P(y > 0), then a Tweedie regressor estimates expected demand quantity E[y | y > 0]. The final forecast is P × E.

The reason for splitting into two stages is that a single regression model cannot handle zero-inflated spare parts demand cleanly. It either over-predicts zeros or underestimates demand when it occurs. Separating occurrence from magnitude lets each model do one thing well. Intermittent and Lumpy SKUs also receive a 4-month rolling sum transformation before training to stabilise sparse signals. Hyperparameters are tuned at the cluster level via Optuna with TimeSeriesSplit.

**Stage 3 — Ensemble Selection**

Rather than declaring one model the winner across all SKUs, we compare per-SKU MASE on the held-out test period and select the better-performing model at inference time. This reflects the reality that no single approach dominates across all demand pattern types.

---

## Evaluation

MASE is the primary evaluation metric, with cluster-specific denominators: Seasonal Naive (m=12) for Smooth and Erratic SKUs, Random Walk (m=1) for Intermittent and Lumpy SKUs. These denominators reflect the strongest naive baseline that is actually meaningful for each demand pattern. WAPE is tracked at the portfolio level but not used for model selection, as it aggregates across SKUs in a way that masks poor performance on low-volume intermittent items.

Ensemble MASE < 1 across all demand pattern clusters, confirming consistent improvement over naive baselines in every segment.

The prior XGBoost approach relied on WAPE alone and exceeded 0.5 across the portfolio. The move from a single global model to pattern-aware model assignment was the primary structural change that drove improvement.

---

## Current Status

| Component | Status |
|---|---|
| Material segmentation (K-Means) | In production |
| Intermittent / Lumpy forecasting | In production |
| Smooth / Erratic forecasting | Validation ongoing |
| Ensemble selector | Fine-tuning |
| Additional model candidates | Planned |

---

## Reflection

Previous forecasting attempts at the branch showed there was a real problem worth solving. This project was the first time a solution was fully designed and owned end-to-end — data pipeline, model development, evaluation framework, validation, and deployment — by a two-person team over seven months. Seeing it adopted by the team and presented to management was the result that made the whole process worthwhile. Development is ongoing.

---

## Technical Stack

Python, LightGBM, pmdarima, Optuna, scikit-learn, pandas, SQLAlchemy, PostgreSQL

2021–2025 branch order history · ~7,000 SKUs · 12-month forecast horizon
