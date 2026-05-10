import warnings
import os
import json
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import lightgbm as lgb
import optuna
import matplotlib
import matplotlib.pyplot as plt
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss
from sqlalchemy import create_engine, text

# Shared evaluation metrics module
from shared_metrics_en import (
    compute_mase,
    compute_relative_bias,
    compute_wape,
    accuracy_tier,
    mase_lag_for_cluster,
)

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)
matplotlib.use("Agg")




DB_CONFIG = {
    "host":     "localhost",
    "port":     "5432",
    "dbname":   "HD_DATA",
    "user":     "postgres",
    "password": "!Init12345",
}

SOURCE_TABLE = 'raw."DELIVERY_DATA_FINAL"'
DATE_START   = "2021-01-01"
DATE_END     = "2025-12-31"

TRAIN_END        = "2023-12-01"
VALIDATION_START = "2024-01-01"
VALIDATION_END   = "2024-12-01"
REFIT_END        = "2024-12-01"
TEST_START       = "2025-01-01"
TEST_END         = "2025-12-01"
LAST_EVAL_PERIOD = "Dec-25"

FORECAST_MONTHS    = 12
ROLLING_SUM_WINDOW = 4
N_OPTUNA_TRIALS    = 40
CHECKPOINT_FILE    = "checkpoint.json"

SB_ADI_THRESHOLD   = 1.32
SB_CV2_THRESHOLD   = 0.49
MIN_DEMAND_PERIODS = 3   # Minimum number of non-zero demand occurrences
                         # required for ADI/CV² to be statistically meaningful.
                         # SKUs below this threshold are forced to intermittent
                         # or lumpy to prevent misclassification.
TOTAL_LT_MONTHS    = 4

ORDER_TYPES = (
    "General Spare for Maintenance - for HIMSEN",
    "General Spare for Maintenance - without HIMSEN",
)



def get_engine():
    c = DB_CONFIG
    return create_engine(
        f"postgresql://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{c['dbname']}"
    )


def build_raw_sql() -> text:
    order_type_list = ", ".join(f"'{ot}'" for ot in ORDER_TYPES)
    return text(f"""
    WITH date_filtered AS (
        SELECT
            "U Code",
            "자재번호"          AS material_no,
            "수주일자"::date    AS order_date,
            "오더수량"::numeric AS order_qty,
            "수통번호"          AS order_no
        FROM {SOURCE_TABLE}
        WHERE "수주일자"::date >= '{DATE_START}'
          AND "수주일자"::date <= '{DATE_END}'
          AND "Info Group" = 'RTM'
          AND "수주유형" IN ({order_type_list})
          AND "수통번호" NOT LIKE '%W%'
          AND "수통번호" NOT LIKE '%X%'
          AND "자재번호" NOT LIKE '%RCF%'
    ),
    filled AS (
        SELECT material_no, order_date, order_qty,
            COALESCE(
                "U Code",
                FIRST_VALUE("U Code") OVER (
                    PARTITION BY material_no
                    ORDER BY CASE WHEN "U Code" IS NOT NULL THEN 0 ELSE 1 END,
                             order_date DESC
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            ) AS u_code
        FROM date_filtered
    ),
    cleaned AS (SELECT * FROM filled WHERE u_code IS NOT NULL),
    month_series AS (
        SELECT u.u_code, m.month
        FROM (SELECT DISTINCT u_code FROM cleaned) u
        CROSS JOIN (
            SELECT generate_series(
                DATE_TRUNC('month', '{DATE_START}'::date)::date,
                DATE_TRUNC('month', '{DATE_END}'::date)::date,
                INTERVAL '1 month'
            )::date AS month
        ) m
    ),
    aggregated AS (
        SELECT u_code,
               DATE_TRUNC('month', order_date)::date AS month,
               SUM(order_qty) AS y
        FROM cleaned
        GROUP BY u_code, DATE_TRUNC('month', order_date)::date
    ),
    adi_calc AS (
        SELECT ms.u_code,
               COUNT(ms.month)::float /
               NULLIF(COUNT(*) FILTER (WHERE a.y > 0), 0) AS adi
        FROM month_series ms
        LEFT JOIN aggregated a
            ON a.u_code = ms.u_code AND a.month = ms.month
        GROUP BY ms.u_code
    )
    SELECT
        ms.u_code,
        TO_CHAR(ms.month, 'YYYY-MM-01')::date AS period,
        COALESCE(a.y,      0)   AS y,
        COALESCE(adi.adi, 999)  AS adi
    FROM month_series ms
    LEFT JOIN aggregated a   ON a.u_code = ms.u_code AND a.month = ms.month
    LEFT JOIN adi_calc adi   ON adi.u_code = ms.u_code
    ORDER BY ms.u_code, ms.month;
    """)


def load_data(engine) -> pd.DataFrame:
    print("=" * 65)
    print("STEP 1. Loading data from PostgreSQL...")
    t0  = time.time()
    df  = pd.read_sql(build_raw_sql(), engine)
    df["period"] = pd.to_datetime(df["period"])
    df  = df.sort_values(["u_code", "period"]).reset_index(drop=True)
    nonzero = df.groupby("u_code")["y"].sum()
    df = df[df["u_code"].isin(nonzero[nonzero > 0].index)].copy()
    print(f"  Done: {time.time()-t0:.1f}s  |  SKU: {df['u_code'].nunique():,}  "
          f"|  Period: {df['period'].min().date()} ~ {df['period'].max().date()}")
    return df




def compute_sku_stats(df: pd.DataFrame,
                       cutoff_date: str = None) -> pd.DataFrame:
    """
    ADI is computed only over the active demand window (from first non-zero
    observation onward). Including leading zeros can cause newly introduced
    materials to be over-classified as Lumpy.

    Minimum demand count guard:
    If n_nonzero < MIN_DEMAND_PERIODS, ADI/CV² thresholds are bypassed and
    the cluster is assigned based on ADI alone to prevent misclassification
    caused by cv2 defaulting to 0.0 for SKUs with very few demand events.
    """
    if cutoff_date is not None:
        df = df[df["period"] <= pd.Timestamp(cutoff_date)].copy()

    records = []
    for u_code, grp in df.groupby("u_code"):
        y         = grp["y"].values
        nonzero_y = y[y > 0]
        n_nonzero = len(nonzero_y)

        # Use only the window from the first demand occurrence onward
        if n_nonzero > 0:
            first_idx   = int(np.argmax(y > 0))
            y_active    = y[first_idx:]
            n_active_nz = (y_active > 0).sum()
            adi = len(y_active) / n_active_nz if n_active_nz > 0 else 999.0
        else:
            adi = 999.0

        cv2 = (np.std(nonzero_y) / np.mean(nonzero_y)) ** 2 \
              if n_nonzero > 1 else 0.0

        # 
        if n_nonzero < MIN_DEMAND_PERIODS:
            cluster = "lumpy" if adi > SB_ADI_THRESHOLD else "erratic"
        elif adi <= SB_ADI_THRESHOLD and cv2 <= SB_CV2_THRESHOLD:
            cluster = "smooth"
        elif adi <= SB_ADI_THRESHOLD and cv2 >  SB_CV2_THRESHOLD:
            cluster = "erratic"
        elif adi >  SB_ADI_THRESHOLD and cv2 <= SB_CV2_THRESHOLD:
            cluster = "intermittent"
        else:
            cluster = "lumpy"

        records.append({
            "u_code": u_code, "adi": round(adi, 4), "cv2": round(cv2, 4),
            "cluster": cluster, "n_nonzero_periods": n_nonzero,
            "total_periods": len(y),
            "demand_rate": round(n_nonzero / len(y), 4),
            "mean_nonzero_qty": round(float(np.mean(nonzero_y)), 2) if n_nonzero > 0 else 0.0,
            "total_qty": round(float(nonzero_y.sum()), 2) if n_nonzero > 0 else 0.0,
        })

    sku_stats = pd.DataFrame(records)
    print("\n  [SKU Cluster Distribution — Syntetos-Boylan]")
    print(f"  {'Cluster':<15} {'N':>6}  {'%':>6}  {'MASE lag':>9}")
    print(f"  {'-'*42}")
    total = len(sku_stats)
    for cls in ["smooth", "erratic", "intermittent", "lumpy"]:
        sub = sku_stats[sku_stats["cluster"] == cls]
        n   = len(sub)
        if n == 0:
            continue
        lag = mase_lag_for_cluster(cls)
        print(f"  {cls:<15} {n:>6,}  {n/total*100:>5.1f}%  m={lag:>2}")
    return sku_stats




def apply_rolling_sum(df: pd.DataFrame, sku_stats: pd.DataFrame) -> pd.DataFrame:
    sparse_skus = set(
        sku_stats[sku_stats["cluster"].isin(["intermittent", "lumpy"])]["u_code"]
    )
    df = df.copy()
    df["y_monthly"] = df["y"].copy()
    for u_code in sparse_skus:
        mask = df["u_code"] == u_code
        rolling_y = df.loc[mask, "y"].rolling(ROLLING_SUM_WINDOW,
                                               min_periods=ROLLING_SUM_WINDOW).sum()
        df.loc[mask, "y"] = rolling_y
    df = df.dropna(subset=["y"]).reset_index(drop=True)
    print(f"\n  Rolling Sum: {len(sparse_skus)} Intermittent/Lumpy SKUs → "
          f"{ROLLING_SUM_WINDOW}-month rolling sum")
    return df




FEATURE_COLS = [
    "y_lag_1", "y_lag_2", "y_lag_3", "y_lag_6", "y_lag_12",
    "roll_mean_3", "roll_mean_6", "roll_mean_12",
    "roll_std_3",  "roll_std_6",
    "roll_max_6",  "roll_max_12",
    "demand_occur_rate_6", "demand_occur_rate_12",
    "months_since_last_demand",
    "month_sin", "month_cos", "quarter",
    "ema_3", "ema_6",
    "adi", "cv2",
    "roll_mean_lt", "roll_std_lt", "roll_sum_lt",
    "demand_occur_lt", "lag_at_lt", "cv_lt",
]


def _build_features_for_group(grp: pd.DataFrame,
                                lt_months: int = TOTAL_LT_MONTHS) -> pd.DataFrame:
    grp  = grp.sort_values("period").copy()
    y    = grp["y"]
    y_s1 = y.shift(1)

    for lag in [1, 2, 3, 6, 12]:
        grp[f"y_lag_{lag}"] = y.shift(lag)

    grp["roll_mean_3"]  = y_s1.rolling(3,  min_periods=1).mean()
    grp["roll_mean_6"]  = y_s1.rolling(6,  min_periods=1).mean()
    grp["roll_mean_12"] = y_s1.rolling(12, min_periods=1).mean()
    grp["roll_std_3"]   = y_s1.rolling(3,  min_periods=1).std().fillna(0)
    grp["roll_std_6"]   = y_s1.rolling(6,  min_periods=1).std().fillna(0)
    grp["roll_max_6"]   = y_s1.rolling(6,  min_periods=1).max()
    grp["roll_max_12"]  = y_s1.rolling(12, min_periods=1).max()

    nz_s1 = (y.shift(1) > 0).astype(float)
    grp["demand_occur_rate_6"]  = nz_s1.rolling(6,  min_periods=1).mean()
    grp["demand_occur_rate_12"] = nz_s1.rolling(12, min_periods=1).mean()

    months_since, count = [], 0
    for v in y.shift(1).values:
        count = count + 1 if (np.isnan(v) or v == 0) else 0
        months_since.append(count)
    grp["months_since_last_demand"] = months_since

    m = grp["period"].dt.month
    grp["month_sin"] = np.sin(2 * np.pi * m / 12)
    grp["month_cos"] = np.cos(2 * np.pi * m / 12)
    grp["quarter"]   = grp["period"].dt.quarter

    grp["ema_3"] = y_s1.ewm(span=3, adjust=False).mean()
    grp["ema_6"] = y_s1.ewm(span=6, adjust=False).mean()

    def _expanding_cv2(series: pd.Series) -> list:
        result = []
        for i in range(len(series)):
            nz  = series.iloc[:i + 1]
            nz  = nz[nz > 0]
            val = (nz.std() / nz.mean()) ** 2 if len(nz) > 1 else 0.0
            result.append(val)
        return result

    y_monthly_col = grp["y_monthly"] if "y_monthly" in grp.columns else y
    grp["cv2"] = _expanding_cv2(y_monthly_col.shift(1))

    nz_cumrate = (y_monthly_col.shift(1) > 0).expanding().mean()
    grp["adi"] = (1.0 / nz_cumrate.replace(0.0, np.nan)).fillna(999.0).clip(upper=999.0)

    grp["roll_mean_lt"]    = y_s1.rolling(lt_months, min_periods=1).mean()
    grp["roll_std_lt"]     = y_s1.rolling(lt_months, min_periods=1).std().fillna(0)
    grp["roll_sum_lt"]     = y_s1.rolling(lt_months, min_periods=1).sum()
    grp["demand_occur_lt"] = nz_s1.rolling(lt_months, min_periods=1).mean()
    grp["lag_at_lt"]       = y.shift(lt_months)
    lt_mean                = grp["roll_mean_lt"].replace(0, np.nan)
    grp["cv_lt"]           = (grp["roll_std_lt"] / lt_mean).fillna(0)
    return grp


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    print(f"\nSTEP 3. Feature Engineering... ({len(FEATURE_COLS)} features)")
    t0  = time.time()
    out = pd.concat(
        [_build_features_for_group(g) for _, g in df.groupby("u_code", sort=False)],
        ignore_index=True,
    )
    print(f"  Done: {time.time()-t0:.1f}s")
    return out


#NAIVE

def compute_naive_baselines(df: pd.DataFrame,
                              sku_stats: pd.DataFrame) -> pd.DataFrame:
    
    cluster_map = sku_stats.set_index("u_code")["cluster"].to_dict()
    test_start  = pd.Timestamp(TEST_START)
    test_end    = pd.Timestamp(TEST_END)
    records     = []

    for u_code, grp in df.groupby("u_code"):
        grp     = grp.sort_values("period").copy()
        cluster = cluster_map.get(u_code, "lumpy")
        train   = grp[grp["period"] < test_start]
        test    = grp[(grp["period"] >= test_start) &
                      (grp["period"] <= test_end)]

        if len(test) == 0 or len(train) < 2:
            continue

        y_tr = train["y"].values
        y_te = test["y"].values

        naive_preds, snaive_preds = [], []
        for row in test.itertuples():
            t      = row.period
            prev_m = grp[grp["period"] == t - pd.DateOffset(months=1)]
            prev_y = grp[grp["period"] == t - pd.DateOffset(months=12)]
            n_val  = float(prev_m["y"].iloc[0]) if len(prev_m) > 0 else 0.0
            sn_val = float(prev_y["y"].iloc[0]) if len(prev_y) > 0 else n_val
            naive_preds.append(n_val)
            snaive_preds.append(sn_val)

        
        mase_n  = compute_mase(y_te, np.array(naive_preds),  y_tr, cluster)
        mase_sn = compute_mase(y_te, np.array(snaive_preds), y_tr, cluster)

        for i, row in enumerate(test.itertuples()):
            records.append({
                "U Code":          u_code,
                "Period":          row.period.strftime("%b-%y"),
                "Naive_Forecast":  int(round(naive_preds[i])),
                "SNaive_Forecast": int(round(snaive_preds[i])),
                "MASE_Naive":      mase_n,
                "MASE_SNaive":     mase_sn,
            })

    baseline_df = pd.DataFrame(records)
    per_sku = baseline_df.groupby("U Code")[["MASE_Naive", "MASE_SNaive"]].first().dropna()
    print(f"\n  [Naive Baseline — {baseline_df['U Code'].nunique():,} SKU]")
    for col, label in [("MASE_Naive",  "Naive(prev-month)"),
                       ("MASE_SNaive", "SNaive(same-month-prev-year)")]:
        vals = per_sku[col].dropna()
        print(f"    {label:<35} Mean MASE: {vals.mean():.3f}  "
              f"MASE<1: {(vals<1).mean()*100:.1f}%")
    return baseline_df


def merge_baseline_to_eval(eval_df: pd.DataFrame,
                            baseline_df: pd.DataFrame) -> pd.DataFrame:
    merged = eval_df.merge(
        baseline_df[["U Code", "Period",
                     "Naive_Forecast", "SNaive_Forecast",
                     "MASE_Naive", "MASE_SNaive"]],
        on=["U Code", "Period"], how="left",
    )
    lgbm_mase  = merged["MASE"].fillna(np.nan)
    naive_mase = merged["MASE_Naive"].fillna(np.nan)
    sn_mase    = merged["MASE_SNaive"].fillna(np.nan)
    merged["Lift_vs_Naive"]  = (
        (naive_mase - lgbm_mase) / naive_mase.replace(0, np.nan) * 100
    ).round(1)
    merged["Lift_vs_SNaive"] = (
        (sn_mase - lgbm_mase) / sn_mase.replace(0, np.nan) * 100
    ).round(1)
    return merged


#TWO STAGE MODEL

class TwoStageDemandModel:
    """
    Stage 1 — LightGBM Binary Classifier  → P(y > 0)
    Stage 2 — LightGBM Tweedie Regressor  → E[y | y > 0]
    Output  — E[y] = P(y > 0) × E[y | y > 0]
    """
    def __init__(self, clf_params: dict, reg_params: dict,
                 cluster_name: str = "unknown"):
        self.cluster_name   = cluster_name
        self.clf_params     = {**clf_params,  "objective": "binary",
                               "metric": "binary_logloss", "n_jobs": -1,
                               "verbosity": -1, "random_state": 42}
        self.reg_params     = {**reg_params,  "objective": "tweedie",
                               "n_jobs": -1,  "verbosity": -1, "random_state": 42}
        self.classifier     : lgb.LGBMClassifier | None = None
        self.regressor      : lgb.LGBMRegressor  | None = None
        self._fallback_mean : float = 0.0

    def fit(self, X: pd.DataFrame, y: pd.Series):
        y_binary            = (y > 0).astype(int)
        self._fallback_mean = float(y.mean())
        self.classifier = lgb.LGBMClassifier(**self.clf_params)
        self.classifier.fit(X, y_binary, callbacks=[lgb.log_evaluation(-1)])
        nonzero_mask = y > 0
        if nonzero_mask.sum() >= 10:
            self.regressor = lgb.LGBMRegressor(**self.reg_params)
            self.regressor.fit(X[nonzero_mask], y[nonzero_mask],
                               callbacks=[lgb.log_evaluation(-1)])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if self.classifier is None:
            return np.zeros(len(X))
        prob = self.classifier.predict_proba(X)[:, 1]
        qty  = (self.regressor.predict(X).clip(0)
                if self.regressor is not None
                else np.full(len(X), self._fallback_mean))
        return prob * qty


# Optuna Hyperparameter Tuning


def _clf_objective(trial, X: pd.DataFrame, y: pd.Series) -> float:
    params = {
        "n_estimators":      trial.suggest_int("n_estimators", 100, 600),
        "num_leaves":        trial.suggest_int("num_leaves", 16, 128),
        "learning_rate":     trial.suggest_float("learning_rate", 0.005, 0.15, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 60),
        "reg_alpha":         trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        "reg_lambda":        trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        "subsample":         trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "objective": "binary", "n_jobs": -1, "verbosity": -1, "random_state": 42,
    }
    y_binary = (y > 0).astype(int)
    scores   = []
    for tr_i, vl_i in TimeSeriesSplit(n_splits=4).split(X):
        m = lgb.LGBMClassifier(**params)
        m.fit(X.iloc[tr_i], y_binary.iloc[tr_i],
              eval_set=[(X.iloc[vl_i], y_binary.iloc[vl_i])],
              callbacks=[lgb.early_stopping(30, verbose=False),
                         lgb.log_evaluation(-1)])
        proba = m.predict_proba(X.iloc[vl_i])[:, 1]
        scores.append(log_loss(y_binary.iloc[vl_i], proba))
    return float(np.mean(scores))


def _reg_objective(trial, X: pd.DataFrame, y: pd.Series) -> float:
    params = {
        "tweedie_variance_power": trial.suggest_float("tweedie_variance_power",
                                                       1.0, 1.9),
        "n_estimators":      trial.suggest_int("n_estimators", 100, 600),
        "num_leaves":        trial.suggest_int("num_leaves", 16, 96),
        "learning_rate":     trial.suggest_float("learning_rate", 0.005, 0.1, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 40),
        "reg_alpha":         trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        "reg_lambda":        trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        "subsample":         trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "objective": "tweedie", "n_jobs": -1, "verbosity": -1, "random_state": 42,
    }
    scores = []
    for tr_i, vl_i in TimeSeriesSplit(n_splits=4).split(X):
        if len(tr_i) < 10:
            continue
        m = lgb.LGBMRegressor(**params)
        m.fit(X.iloc[tr_i], y.iloc[tr_i],
              eval_set=[(X.iloc[vl_i], y.iloc[vl_i])],
              callbacks=[lgb.early_stopping(30, verbose=False),
                         lgb.log_evaluation(-1)])
        pred = m.predict(X.iloc[vl_i]).clip(0)
        scores.append(np.mean(np.abs(y.iloc[vl_i].values - pred)))
    return float(np.mean(scores)) if scores else 999.0


def tune_cluster(X_tune: pd.DataFrame, y_tune: pd.Series,
                 cluster_name: str, n_trials: int) -> tuple[dict, dict]:
    print(f"\n  [{cluster_name}] Classifier tuning ({n_trials} trials)...")
    clf_study = optuna.create_study(direction="minimize",
                                    sampler=optuna.samplers.TPESampler(seed=42))
    clf_study.optimize(lambda t: _clf_objective(t, X_tune, y_tune),
                       n_trials=n_trials, show_progress_bar=False)
    best_clf = clf_study.best_params
    print(f"  [{cluster_name}] Classifier Best logloss: {clf_study.best_value:.4f}")

    X_nz, y_nz = X_tune[y_tune > 0], y_tune[y_tune > 0]
    best_reg = {}
    if len(X_nz) >= 30:
        print(f"  [{cluster_name}] Regressor tuning ({n_trials} trials, "
              f"{len(X_nz)} non-zero rows)...")
        reg_study = optuna.create_study(direction="minimize",
                                        sampler=optuna.samplers.TPESampler(seed=42))
        reg_study.optimize(lambda t: _reg_objective(t, X_nz, y_nz),
                           n_trials=n_trials, show_progress_bar=False)
        best_reg = reg_study.best_params
        print(f"  [{cluster_name}] Regressor Best MAE: {reg_study.best_value:.4f}")
    else:
        print(f"  [{cluster_name}] Regressor tuning skipped (non-zero rows < 30)")
        best_reg = {"tweedie_variance_power": 1.5, "n_estimators": 200,
                    "num_leaves": 31, "learning_rate": 0.05}
    return best_clf, best_reg



# Cluster-level Model Training


def train_cluster_models(df_feat: pd.DataFrame,
                          sku_stats: pd.DataFrame,
                          tune_end: str,
                          train_end: str,
                          n_trials: int) -> dict[str, TwoStageDemandModel]:
    cluster_map = sku_stats.set_index("u_code")["cluster"].to_dict()
    df_feat     = df_feat.copy()
    df_feat["cluster"] = df_feat["u_code"].map(cluster_map)

    tune_df  = df_feat[df_feat["period"] <= tune_end ].dropna(subset=FEATURE_COLS)
    train_df = df_feat[df_feat["period"] <= train_end].dropna(subset=FEATURE_COLS)

    cluster_models: dict[str, TwoStageDemandModel] = {}

    for cluster_name in ["smooth", "erratic", "intermittent", "lumpy"]:
        sub_tune  = tune_df [tune_df ["cluster"] == cluster_name]
        sub_train = train_df[train_df["cluster"] == cluster_name]

        if sub_tune.empty or sub_train.empty:
            print(f"  [{cluster_name}] No data → skip")
            continue

        X_tune,  y_tune  = sub_tune [FEATURE_COLS], sub_tune ["y"]
        X_train, y_train = sub_train[FEATURE_COLS], sub_train["y"]

        print(f"\n  [{cluster_name}]  tune: {len(sub_tune):,} rows  "
              f"refit: {len(sub_train):,} rows  "
              f"SKUs: {sub_train['u_code'].nunique():,}")

        clf_params, reg_params = tune_cluster(X_tune, y_tune,
                                               cluster_name, n_trials)
        model = TwoStageDemandModel(clf_params, reg_params, cluster_name)
        model.fit(X_train, y_train)
        cluster_models[cluster_name] = model
        print(f"  [{cluster_name}] Training complete (refit on {train_end})")

    return cluster_models



def integerize_cumulative(forecasts: list[float]) -> list[int]:
    result, carry = [], 0.0
    for f in forecasts:
        carry += max(f, 0.0)
        if carry >= 1.0:
            integer_part = int(carry)
            carry        = carry - integer_part
            result.append(integer_part)
        else:
            result.append(0)
    return result




def recursive_forecast_sku(history: pd.DataFrame,
                            model: TwoStageDemandModel,
                            adi: float, cv2: float,
                            n_months: int = FORECAST_MONTHS) -> list[dict]:
   
    # Include y_monthly if present; for smooth/erratic it falls back to y
    cols = ["period", "y", "adi"]
    if "y_monthly" in history.columns:
        cols.append("y_monthly")

    buf = history[cols].copy()
    nz  = buf["y"][buf["y"] > 0]
    cv2 = float((nz.std() / nz.mean()) ** 2) if len(nz) > 1 else 0.0
    buf["cv2"] = cv2

    start     = history["period"].max() + pd.DateOffset(months=1)
    raw_preds = []

    for step in range(n_months):
        next_period = start + pd.DateOffset(months=step)
        placeholder = {"period": [next_period], "y": [0.0],
                       "adi": [adi], "cv2": [cv2]}
        if "y_monthly" in buf.columns:
            placeholder["y_monthly"] = [0.0]
        buf = pd.concat([buf, pd.DataFrame(placeholder)], ignore_index=True)

        feat_buf = _build_features_for_group(buf)
        row      = feat_buf[feat_buf["period"] == next_period][FEATURE_COLS].fillna(0)
        raw_pred = float(model.predict(row)[0])
        raw_preds.append(raw_pred)
        buf.loc[buf["period"] == next_period, "y"] = raw_pred
        if "y_monthly" in buf.columns:
            buf.loc[buf["period"] == next_period, "y_monthly"] = raw_pred

    int_preds = integerize_cumulative(raw_preds)
    return [
        {"period":       start + pd.DateOffset(months=step),
         "forecast":     int_preds[step],
         "forecast_raw": round(raw_preds[step], 4)}
        for step in range(n_months)
    ]


# Evaluation + Forecast Loop  


def run_evaluation_and_forecast(
        df: pd.DataFrame,
        df_feat: pd.DataFrame,
        sku_stats: pd.DataFrame,
        eval_models: dict[str, TwoStageDemandModel],
        future_models: dict[str, TwoStageDemandModel],
        output_folder: str,
        checkpoint_path: str,
        baseline_df: pd.DataFrame = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    cluster_map = sku_stats.set_index("u_code")["cluster"].to_dict()
    cv2_map     = sku_stats.set_index("u_code")["cv2"].to_dict()
    df_feat     = df_feat.copy()
    df_feat["cluster"] = df_feat["u_code"].map(cluster_map)

    eval_train_df = df_feat[df_feat["period"] <= REFIT_END]
    eval_test_df  = df_feat[(df_feat["period"] >= TEST_START) &
                             (df_feat["period"] <= TEST_END)]

    unique_codes = eval_test_df["u_code"].unique()
    n_total      = len(unique_codes)

    done_set           = _load_checkpoint(checkpoint_path)
    partial_eval_csv   = os.path.join(output_folder, "_partial_eval.csv")
    partial_future_csv = os.path.join(output_folder, "_partial_future.csv")

    if done_set and os.path.exists(partial_eval_csv):
        eval_rows   = pd.read_csv(partial_eval_csv).to_dict("records")
        future_rows = pd.read_csv(partial_future_csv).to_dict("records")
    else:
        eval_rows, future_rows = [], []

    print(f"\nSTEP 6. Per-SKU Evaluation + Future Forecast "
          f"({n_total:,} SKUs, done: {len(done_set):,})")
    times, skus_done = [], 0

    for u_code in unique_codes:
        if u_code in done_set:
            continue

        t0      = time.time()
        cluster = cluster_map.get(u_code, "lumpy")
        adi_val = sku_stats.loc[sku_stats["u_code"] == u_code, "adi"].iloc[0]
        cv2_val = cv2_map.get(u_code, 0.0)

        eval_model   = eval_models.get(cluster)
        future_model = future_models.get(cluster)
        if eval_model is None or future_model is None:
            done_set.add(u_code)
            continue

        tr = eval_train_df[eval_train_df["u_code"] == u_code]
        te = eval_test_df [eval_test_df ["u_code"] == u_code]
        if tr.empty or te.empty:
            done_set.add(u_code)
            continue

        X_te  = te[FEATURE_COLS].fillna(0)
        sparse = cluster in {"intermittent", "lumpy"}
        y_te   = te["y"].values    if sparse else te["y_monthly"].values
        y_tr   = tr["y"].values    if sparse else tr["y_monthly"].values

        raw_preds = eval_model.predict(X_te)

     
        mase_s = compute_mase(y_te, raw_preds, y_tr, cluster)
        rb_s   = compute_relative_bias(y_te, raw_preds)
        wape_s = compute_wape(y_te, raw_preds)

        e_pred_int = np.array(integerize_cumulative(raw_preds.tolist()))

        for i in range(len(te)):
            eval_rows.append({
                "U Code":          u_code,
                "Cluster":         cluster,
                "Period":          te.iloc[i]["period"].strftime("%b-%y"),
                "Forecast (LGBM)": int(e_pred_int[i]),
                "Forecast_Raw":    round(float(raw_preds[i]), 4),
                "Actual":          int(y_te[i]),
                "MASE":            mase_s,
                "Relative_Bias":   rb_s,
                "WAPE":            wape_s,
            })

      
        sku_history  = df[df["u_code"] == u_code].copy()
        future_preds = recursive_forecast_sku(
            sku_history, future_model, adi_val, cv2_val
        )

        for fp in future_preds:
            future_rows.append({
                "U Code":          u_code,
                "Cluster":         cluster,
                "Period":          fp["period"].strftime("%b-%y"),
                "Forecast (LGBM)": int(fp["forecast"]),
                "Forecast_Raw":    fp["forecast_raw"],
            })

        # Plot
        fig, ax = plt.subplots(figsize=(14, 6))
        tr_plot = tr.tail(24)
        ax.plot(tr_plot["period"], tr_plot["y"],
                label="Training (last 24m)", color="royalblue",
                marker="o", markersize=3, linewidth=1.2, alpha=0.7)
        ax.plot(te["period"], y_te,
                label="Actual (2025)", color="green",
                marker="o", markersize=5, linewidth=2.0)
        ax.plot(te["period"], raw_preds,
                label="Backtest Forecast (raw)", color="orange",
                marker="x", markersize=5, linewidth=1.8, linestyle="--")
        fut_dates = [fp["period"] for fp in future_preds]
        fut_vals  = [fp["forecast"] for fp in future_preds]
        ax.plot(fut_dates, fut_vals,
                label="Future Forecast (2026)", color="red",
                marker="*", markersize=7, linewidth=2.0, linestyle="--")
        ax.axvline(pd.Timestamp(TEST_END), color="gray", linestyle=":", alpha=0.7)
        mase_str = f"{mase_s:.3f}" if not np.isnan(mase_s) else "N/A"
        rb_str   = f"{rb_s:+.2f}" if not np.isnan(rb_s) else "N/A"
        ax.set_title(f"[{cluster}] {u_code}  MASE: {mase_str}  RB: {rb_str}",
                     fontsize=12, fontweight="bold")
        ax.set_xlabel("Date"); ax.set_ylabel("Order Quantity")
        ax.legend(fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="x", rotation=45)
        plt.tight_layout()
        safe = "".join(c if c.isalnum() else "_" for c in str(u_code))
        fig.savefig(os.path.join(output_folder, f"{safe}_forecast.png"),
                    dpi=100, bbox_inches="tight")
        plt.close(fig)

        done_set.add(u_code)
        skus_done += 1
        times.append(time.time() - t0)

        if skus_done % 50 == 0:
            _save_checkpoint(checkpoint_path, done_set)
            pd.DataFrame(eval_rows).to_csv(partial_eval_csv,   index=False)
            pd.DataFrame(future_rows).to_csv(partial_future_csv, index=False)

        if skus_done % 100 == 0 or skus_done == 1:
            avg_t     = np.mean(times[-100:])
            remaining = n_total - len(done_set)
            eta       = str(timedelta(seconds=int(avg_t * remaining)))
            now       = datetime.now().strftime("%H:%M:%S")
            print(f"  [{now}] {len(done_set):>5}/{n_total} "
                  f"({len(done_set)/n_total*100:.1f}%)  "
                  f"avg {avg_t:.1f}s/SKU  ETA: {eta}")

    _save_checkpoint(checkpoint_path, done_set)
    pd.DataFrame(eval_rows).to_csv(partial_eval_csv,   index=False)
    pd.DataFrame(future_rows).to_csv(partial_future_csv, index=False)
    print(f"\n  All SKUs processed: {n_total:,}")

    eval_df   = pd.DataFrame(eval_rows)
    future_df = pd.DataFrame(future_rows)

    if baseline_df is not None and len(baseline_df) > 0:
        eval_df = merge_baseline_to_eval(eval_df, baseline_df)
        lift    = eval_df.groupby("U Code")["Lift_vs_Naive"].first().dropna()
        sn_lift = eval_df.groupby("U Code")["Lift_vs_SNaive"].first().dropna()
        print(f"\n  [LGBM vs Naive Lift]")
        print(f"    vs Naive   : mean {lift.mean():>+6.1f}%  "
              f"LGBM wins {(lift>0).mean()*100:.1f}%")
        print(f"    vs SNaive  : mean {sn_lift.mean():>+6.1f}%  "
              f"LGBM wins {(sn_lift>0).mean()*100:.1f}%")

    return eval_df, future_df



# Checkpoint


def _load_checkpoint(path: str) -> set:
    if os.path.exists(path):
        with open(path) as f:
            done = set(json.load(f))
        print(f"  Checkpoint found: {len(done)} SKUs done. Resuming...")
        return done
    return set()


def _save_checkpoint(path: str, done: set):
    with open(path, "w") as f:
        json.dump(list(done), f)



# Feature Importance


def plot_feature_importance_cluster(models: dict[str, TwoStageDemandModel],
                                     output_folder: str, label: str = "eval"):
    lt_features = {"roll_mean_lt", "roll_std_lt", "roll_sum_lt",
                   "demand_occur_lt", "lag_at_lt", "cv_lt"}
    for cluster_name, model in models.items():
        for stage_name, lgbm_model in [("classifier", model.classifier),
                                        ("regressor",  model.regressor)]:
            if lgbm_model is None:
                continue
            imp = pd.DataFrame({
                "Feature":    FEATURE_COLS,
                "Importance": lgbm_model.feature_importances_,
            }).sort_values("Importance", ascending=True)
            colors = ["tomato" if f in lt_features else "steelblue"
                      for f in imp["Feature"]]
            fig, ax = plt.subplots(figsize=(10, 8))
            bars = ax.barh(imp["Feature"], imp["Importance"],
                           color=colors, edgecolor="white")
            ax.bar_label(bars, fmt="%d", padding=3, fontsize=8)
            ax.set_xlabel("Importance (split count)", fontsize=11)
            ax.set_title(f"[{cluster_name}] {stage_name} Feature Importance ({label})",
                         fontsize=12, fontweight="bold")
            ax.grid(axis="x", alpha=0.3)
            from matplotlib.patches import Patch
            ax.legend(handles=[
                Patch(facecolor="tomato",    label="LT-based Feature"),
                Patch(facecolor="steelblue", label="Standard Feature"),
            ], loc="lower right", fontsize=9)
            plt.tight_layout()
            fig.savefig(
                os.path.join(output_folder,
                             f"feat_imp_{cluster_name}_{stage_name}_{label}.png"),
                dpi=130, bbox_inches="tight"
            )
            plt.close(fig)



# Standard CSV 


def export_standard_csv(eval_df: pd.DataFrame, future_df: pd.DataFrame,
                         sku_stats: pd.DataFrame, output_folder: str):
    sparse_clusters = {"intermittent", "lumpy"}
    cluster_map = sku_stats.set_index("u_code")["cluster"].to_dict()

    bt_rows = []
    for _, row in eval_df.iterrows():
        period_dt = pd.to_datetime(row["Period"], format="%b-%y").replace(day=1)
        cluster   = cluster_map.get(row["U Code"], "lumpy")
        bt_rows.append({
            "u_code":     row["U Code"],
            "period":     period_dt,
            "y_true":     int(row["Actual"]),
            "y_pred":     float(row.get("Forecast_Raw", row["Forecast (LGBM)"])),
            "model_name": "lightgbm_twostage",
            "pred_type":  "rolling_sum_4m" if cluster in sparse_clusters else "monthly",
        })
    bt_df   = pd.DataFrame(bt_rows)
    bt_path = os.path.join(output_folder, "backtest_lightgbm_twostage_2025.csv")
    bt_df.to_csv(bt_path, index=False)
    print(f"  Standard-format backtest: {bt_path}")

    fc_rows = []
    for _, row in future_df.iterrows():
        period_dt = pd.to_datetime(row["Period"], format="%b-%y").replace(day=1)
        cluster   = cluster_map.get(row["U Code"], "lumpy")
        fc_rows.append({
            "u_code":     row["U Code"],
            "period":     period_dt,
            "y_pred":     float(row.get("Forecast_Raw", row["Forecast (LGBM)"])),
            "model_name": "lightgbm_twostage",
            "pred_type":  "rolling_sum_4m" if cluster in sparse_clusters else "monthly",
        })
    fc_df   = pd.DataFrame(fc_rows)
    fc_path = os.path.join(output_folder, "forecast_lightgbm_twostage_2026.csv")
    fc_df.to_csv(fc_path, index=False)
    print(f"  Standard-format forecast: {fc_path}")


# Excel Output


def save_csv(eval_df: pd.DataFrame, future_df: pd.DataFrame,
             sku_stats: pd.DataFrame,
             output_folder: str, timestamp: str) -> str:
    print("\nSTEP 7. Saving results as CSV (4 files)...")

    # --- Accuracy Evaluation ---
    eval_out = eval_df.copy()
    eval_out["Cum. Actual"]   = eval_out.groupby("U Code")["Actual"].cumsum()
    eval_out["Cum. Forecast"] = eval_out.groupby("U Code")["Forecast (LGBM)"].cumsum()
    base_cols  = ["U Code", "Cluster", "Period",
                  "Forecast (LGBM)", "Forecast_Raw", "Actual",
                  "Cum. Actual", "Cum. Forecast",
                  "MASE", "Relative_Bias", "WAPE"]
    extra_cols = [c for c in ["Naive_Forecast", "SNaive_Forecast",
                               "MASE_Naive", "MASE_SNaive",
                               "Lift_vs_Naive", "Lift_vs_SNaive"]
                  if c in eval_out.columns]
    eval_out = eval_out[base_cols + extra_cols]

    # --- Future Forecast ---
    future_out = future_df.copy()
    future_out["Cum. Forecast"] = (
        future_out.groupby("U Code")["Forecast (LGBM)"].cumsum()
    )
    future_out = future_out[["U Code", "Cluster", "Period",
                              "Forecast (LGBM)", "Forecast_Raw", "Cum. Forecast"]]

    # --- SKU Cluster Summary ---
    cluster_sheet = sku_stats[[
        "u_code", "cluster", "adi", "cv2",
        "n_nonzero_periods", "total_periods",
        "demand_rate", "mean_nonzero_qty", "total_qty",
    ]].rename(columns={"u_code": "U Code", "cluster": "Cluster"}
              ).sort_values(["Cluster", "adi"])

    # --- Baseline Comparison ---
    if "Lift_vs_Naive" in eval_df.columns:
        baseline_summary = (
            eval_df.groupby("U Code").agg(
                Cluster        =("Cluster",       "first"),
                MASE_LGBM      =("MASE",          "first"),
                MASE_Naive     =("MASE_Naive",     "first"),
                MASE_SNaive    =("MASE_SNaive",    "first"),
                Lift_vs_Naive  =("Lift_vs_Naive",  "first"),
                Lift_vs_SNaive =("Lift_vs_SNaive", "first"),
            ).reset_index()
        )
        baseline_summary["Winner"] = np.where(
            baseline_summary["MASE_LGBM"] < baseline_summary["MASE_Naive"],
            "LGBM", "Naive"
        )
    else:
        baseline_summary = pd.DataFrame({"Note": ["No naive baseline data"]})

    # --- Save all four files ---
    p1 = os.path.join(output_folder, f"lgbm_V8_accuracy_evaluation_{timestamp}.csv")
    p2 = os.path.join(output_folder, f"lgbm_V8_future_forecast_{timestamp}.csv")
    p3 = os.path.join(output_folder, f"lgbm_V8_sku_cluster_summary_{timestamp}.csv")
    p4 = os.path.join(output_folder, f"lgbm_V8_baseline_comparison_{timestamp}.csv")

    eval_out.to_csv(p1,          index=False)
    future_out.to_csv(p2,        index=False)
    cluster_sheet.to_csv(p3,     index=False)
    baseline_summary.to_csv(p4,  index=False)

    print(f"  -> {os.path.basename(p1)}")
    print(f"  -> {os.path.basename(p2)}")
    print(f"  -> {os.path.basename(p3)}")
    print(f"  -> {os.path.basename(p4)}")
    return p1



# Summary


def print_summary(eval_df: pd.DataFrame, future_df: pd.DataFrame,
                  sku_stats: pd.DataFrame, total_secs: float):
    per_sku = eval_df.groupby("U Code")["MASE"].first().dropna()
    print("\n" + "=" * 65)
    print("  LightGBM Two-Stage V8 — Final Summary")
    print("=" * 65)
    print(f"  Total elapsed     : {str(timedelta(seconds=int(total_secs)))}")
    print(f"  SKUs processed    : {len(per_sku):,}")
    print(f"\n  [Backtest MASE — cluster-aware denominator]")
    desc = per_sku.describe()
    for s in ["mean", "std", "min", "25%", "50%", "75%", "max"]:
        print(f"    {s:<8}: {desc[s]:.4f}")
    print(f"    MASE < 1 : {(per_sku < 1).sum():,} / {len(per_sku):,} "
          f"({(per_sku < 1).mean()*100:.1f}%)")

    print(f"\n  [MASE by Cluster]")
    cluster_mase = (
        eval_df.groupby(["U Code", "Cluster"])["MASE"]
        .first().reset_index()
        .groupby("Cluster")["MASE"]
        .agg(mean="mean", median="median", count="count")
    )
    print(cluster_mase.to_string())

    if "Lift_vs_Naive" in eval_df.columns:
        lift    = eval_df.groupby("U Code")["Lift_vs_Naive"].first().dropna()
        sn_lift = eval_df.groupby("U Code")["Lift_vs_SNaive"].first().dropna()
        print(f"\n  [LGBM vs Naive]")
        print(f"    vs Naive   : mean {lift.mean():>+6.1f}%  "
              f"LGBM wins {(lift>0).mean()*100:.1f}%")
        print(f"    vs SNaive  : mean {sn_lift.mean():>+6.1f}%  "
              f"LGBM wins {(sn_lift>0).mean()*100:.1f}%")

    annual = future_df.groupby("U Code")["Forecast (LGBM)"].sum()
    print(f"\n  [Future Forecast 2026]")
    print(f"    Total forecast volume    : {annual.sum():,.0f}")
    print(f"    Mean annual forecast/SKU : {annual.mean():,.1f}")
    print("=" * 65)



#  MAIN


def main():
    t_start   = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_folder = os.path.join(os.path.abspath("."), f"lgbm_V8_{timestamp}")
    existing = sorted(
        [d for d in os.listdir(".") if d.startswith("lgbm_V8_")], reverse=True
    )
    if existing:
        candidate = os.path.join(os.path.abspath("."), existing[0])
        if os.path.exists(os.path.join(candidate, CHECKPOINT_FILE)):
            output_folder = candidate
            print(f"Resuming from checkpoint: {output_folder}/")
    os.makedirs(output_folder, exist_ok=True)
    checkpoint_path = os.path.join(output_folder, CHECKPOINT_FILE)

    print("=" * 65)
    print("  LightGBM Two-Stage V8  (cluster-aware MASE + y_monthly fix)")
    print(f"  Tune   : {DATE_START} ~ {TRAIN_END}")
    print(f"  Val    : {VALIDATION_START} ~ {VALIDATION_END}")
    print(f"  Refit  : {DATE_START} ~ {REFIT_END}")
    print(f"  Test   : {TEST_START} ~ {TEST_END}")
    print(f"  MASE denominator: m=12 (smooth/erratic) | m=1 (intermittent/lumpy)")
    print("=" * 65)

    engine = get_engine()

    df = load_data(engine)

    print(f"\nSTEP 2. SKU Clustering (cutoff: {REFIT_END})...")
    df_refit_only = df[df["period"] <= pd.Timestamp(REFIT_END)].copy()
    sku_stats     = compute_sku_stats(df_refit_only, cutoff_date=REFIT_END)

    df      = apply_rolling_sum(df, sku_stats)
    df_feat = add_features(df)

    print(f"\n[Eval model: tune={TRAIN_END}, refit={REFIT_END}]")
    eval_models = train_cluster_models(
        df_feat, sku_stats,
        tune_end=TRAIN_END, train_end=REFIT_END,
        n_trials=N_OPTUNA_TRIALS,
    )
    plot_feature_importance_cluster(eval_models, output_folder, label="eval")

    print(f"\n[Future model: tune={REFIT_END}, refit={DATE_END}]")
    future_models = train_cluster_models(
        df_feat, sku_stats,
        tune_end=REFIT_END, train_end=DATE_END,
        n_trials=N_OPTUNA_TRIALS,
    )
    plot_feature_importance_cluster(future_models, output_folder, label="future")

    print("\nSTEP 5-B. Computing naive baseline...")
    baseline_df = compute_naive_baselines(df, sku_stats)   # [FIX 2] sku_stats passed in
    baseline_df.to_csv(os.path.join(output_folder, "naive_baseline.csv"), index=False)

    eval_df, future_df = run_evaluation_and_forecast(
        df, df_feat, sku_stats,
        eval_models, future_models,
        output_folder, checkpoint_path,
        baseline_df=baseline_df,
    )

    excel_path = save_csv(eval_df, future_df, sku_stats, output_folder, timestamp)

    print("\nSTEP 7-B. Exporting standard-format CSV...")
    export_standard_csv(eval_df, future_df, sku_stats, output_folder)

    total_s = time.time() - t_start
    print_summary(eval_df, future_df, sku_stats, total_s)

    print(f"\n{'='*65}")
    print("  All done!")
    print(f"  Elapsed : {str(timedelta(seconds=int(total_s)))}")
    print(f"  Folder  : {output_folder}/")
    print(f"  Excel   : {excel_path}")
    print(f"{'='*65}")

    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    return eval_df, future_df, sku_stats, eval_models, future_models


if __name__ == "__main__":
    eval_df, future_df, sku_stats, eval_models, future_models = main()
