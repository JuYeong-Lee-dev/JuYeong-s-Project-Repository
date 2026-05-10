import warnings
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sqlalchemy import create_engine, text
import optuna
from dotenv import load_dotenv

# Shared evaluation metrics module (must be in the same directory as shared_metrics.py)
from shared_metrics_en import (
    compute_mase,
    compute_relative_bias,
    compute_wape,
    accuracy_tier,
    mase_lag_for_cluster,
)

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

load_dotenv()

DB_URL = os.environ["DB_URL"]  # Set in .env — see .env.example

SOURCE_TABLE = 'raw."DELIVERY_DATA_FINAL"'
DATE_START   = "2021-01-01"
DATE_END     = "2025-12-31"

TRAIN_END        = "2023-12-31"
VALIDATION_START = "2024-01-01"
VALIDATION_END   = "2024-12-31"
REFIT_END        = "2024-12-31"
TEST_START       = "2025-01-01"
TEST_END         = "2025-12-31"

FORECAST_MONTHS  = 12

SB_ADI_THRESHOLD   = 1.32
SB_CV2_THRESHOLD   = 0.49
MIN_DEMAND_PERIODS = 3   

N_OPTUNA_TRIALS  = 50

ORDER_TYPES = (
    "General Spare for Maintenance - for HIMSEN",
    "General Spare for Maintenance - without HIMSEN",
)



def get_engine():
    return create_engine(DB_URL)


def load_monthly_pivot(engine) -> pd.DataFrame:
    order_type_list = ", ".join(f"'{ot}'" for ot in ORDER_TYPES)
    sql = text(f"""
    WITH date_filtered AS (
        SELECT
            "자재번호"          AS material_no,
            "수주일자"::date    AS order_date,
            "오더수량"::numeric AS order_qty,
            "U Code"
        FROM {SOURCE_TABLE}
        WHERE "수주일자"::date >= '{DATE_START}'
          AND "수주일자"::date <= '{DATE_END}'
          AND "Info Group" = 'RTM'
          AND "수주유형" IN ({order_type_list})
          AND "수통번호" NOT LIKE '%W%'
          AND "수통번호" NOT LIKE '%X%'
          AND "자재번호" NOT LIKE '%RCF%'
          AND "수주단가" != '0.01'
    ),
    filled AS (
        SELECT
            material_no, order_date, order_qty,
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
    )
    SELECT u_code AS "U Code", order_date AS "Date", order_qty AS "Order Quantity"
    FROM filled
    WHERE u_code IS NOT NULL
    """)

    df = pd.read_sql(sql, engine)
    df["Date"]  = pd.to_datetime(df["Date"])
    df["Month"] = df["Date"].dt.to_period("M").dt.to_timestamp()

    monthly_df = (
        df.groupby(["Month", "U Code"])["Order Quantity"]
        .sum().reset_index()
    )
    pivot = (
        monthly_df
        .pivot(index="Month", columns="U Code", values="Order Quantity")
        .fillna(0)
    )
    pivot.index = pd.DatetimeIndex(pivot.index).to_period("M").to_timestamp()
    pivot = pivot.asfreq("MS", fill_value=0)
    pivot = pivot.loc[:, pivot.sum(axis=0) > 0]

    print(f"  SKUs: {pivot.shape[1]:,}  "
          f"Period: {pivot.index[0].date()} ~ {pivot.index[-1].date()}")
    return pivot



def classify_sku(y: np.ndarray) -> str:
    """
    ADI and CV² are computed only over the active demand window
    (i.e., from the first non-zero observation onward).

    [FIX] Minimum demand count guard:
    ADI and CV² are only statistically reliable when demand has occurred
    enough times. If n_nz < MIN_DEMAND_PERIODS, the standard thresholds are
    bypassed and the cluster is assigned based on ADI alone:
      - ADI <= threshold  → erratic  (frequent but too few samples to assess CV²)
      - ADI >  threshold  → lumpy    (sparse and too few samples to assess CV²)
    This prevents SKUs with very few lifetime demand events (e.g. 1 occurrence)
    from being misclassified as Smooth due to cv2 defaulting to 0.0.
    """
    first_nz = int(np.argmax(y > 0))
    y_active = y[first_nz:]
    nonzero  = y_active[y_active > 0]
    n_nz     = len(nonzero)

    adi = len(y_active) / n_nz if n_nz > 0 else 999.0

    # Insufficient demand history — bypass CV² and force sparse cluster
    if n_nz < MIN_DEMAND_PERIODS:
        return "lumpy" if adi > SB_ADI_THRESHOLD else "erratic"

    cv2 = (np.std(nonzero) / np.mean(nonzero)) ** 2 if n_nz > 1 else 0.0

    if   adi <= SB_ADI_THRESHOLD and cv2 <= SB_CV2_THRESHOLD: return "smooth"
    elif adi <= SB_ADI_THRESHOLD and cv2 >  SB_CV2_THRESHOLD: return "erratic"
    elif adi >  SB_ADI_THRESHOLD and cv2 <= SB_CV2_THRESHOLD: return "intermittent"
    else:                                                      return "lumpy"


def build_class_df(pivot: pd.DataFrame) -> pd.DataFrame:
    records = [
        {"U Code": u, "Class": classify_sku(pivot[u].values)}
        for u in pivot.columns
    ]
    class_df = pd.DataFrame(records)
    dist = class_df["Class"].value_counts()
    print(f"\n  [SKU Classification — Syntetos-Boylan]")
    print(f"  {'Cluster':<15} {'N':>6}  {'%':>6}  {'MASE lag':>9}")
    print(f"  {'-'*42}")
    for cls in ["smooth", "erratic", "intermittent", "lumpy"]:
        n = dist.get(cls, 0)
        lag = mase_lag_for_cluster(cls)
        print(f"  {cls:<15} {n:>6,}  {n/len(class_df)*100:>5.1f}%  m={lag:>2}")
    return class_df


#ARIMA

def process_item_backtest(item, train_series: pd.Series,
                           val_series: pd.Series, n_periods: int) -> dict:
    from pmdarima import auto_arima
    from pmdarima.arima import ARIMA

    try:
        model_aic = auto_arima(
            train_series, seasonal=True, m=12,
            stepwise=True, suppress_warnings=True, error_action="ignore"
        )
        candidates = [
            {"name": "AIC_Optimal",    "order": model_aic.order,
             "s_order": model_aic.seasonal_order},
            {"name": "Simple_Trend",   "order": (0, 1, 1),
             "s_order": (0, 1, 1, 12)},
            {"name": "Seasonal_Naive", "order": (0, 0, 0),
             "s_order": (0, 1, 0, 12)},
        ]

        best_mae, best_cfg = float("inf"), None
        for cfg in candidates:
            try:
                cand = ARIMA(order=cfg["order"],
                             seasonal_order=cfg["s_order"]).fit(train_series)
                preds = cand.predict(n_periods=len(val_series))
                mae = np.mean(np.abs(val_series.values - preds))
                if mae < best_mae:
                    best_mae, best_cfg = mae, cfg
            except Exception:
                continue

        if best_cfg is None:
            return {"item": item, "error": "All candidates failed"}

        full_history = pd.concat([train_series, val_series])
        final_model  = ARIMA(order=best_cfg["order"],
                             seasonal_order=best_cfg["s_order"]).fit(full_history)
        forecast = np.clip(final_model.predict(n_periods=n_periods), 0, None)

        return {
            "item":        item,
            "forecast":    forecast,
            "val_mae":     best_mae,
            "winner_name": best_cfg["name"],
            "order":       f"{final_model.order}x{final_model.seasonal_order}",
            # y_train passed through for MASE denominator calculation in compute_mase_column
            "y_train":     train_series.values.astype(float),
        }
    except Exception as e:
        return {"item": item, "error": str(e)}


def process_item_future(item, full_train_series: pd.Series,
                         n_periods: int) -> dict:
    import warnings
    warnings.filterwarnings("ignore")
    from pmdarima import auto_arima
    from pmdarima.arima import ARIMA

    try:
        series = full_train_series.copy()
        tune_series = series.iloc[:-12] if len(series) >= 24 else series
        val_series  = series.iloc[-12:] if len(series) >= 24 else series

        model_aic = auto_arima(
            tune_series, seasonal=True, m=12, stepwise=True,
            suppress_warnings=True, error_action="ignore", random_state=42
        )
        candidates = [
            {"name": "AIC_Optimal",    "order": model_aic.order,
             "s_order": model_aic.seasonal_order},
            {"name": "Simple_Trend",   "order": (0, 1, 1),
             "s_order": (0, 1, 1, 12)},
            {"name": "Seasonal_Naive", "order": (0, 0, 0),
             "s_order": (0, 1, 0, 12)},
        ]

        best_mae, best_cfg = float("inf"), None
        for cfg in candidates:
            try:
                cand  = ARIMA(order=cfg["order"],
                              seasonal_order=cfg["s_order"]).fit(tune_series)
                preds = cand.predict(n_periods=len(val_series))
                mae   = np.mean(np.abs(val_series.values - preds))
                if mae < best_mae:
                    best_mae, best_cfg = mae, cfg
            except Exception:
                continue

        if best_cfg is None:
            best_cfg = {"order": (0, 1, 1), "s_order": (0, 1, 1, 12)}

        final_model = ARIMA(order=best_cfg["order"],
                            seasonal_order=best_cfg["s_order"]).fit(series)
        forecast = np.clip(final_model.predict(n_periods=n_periods), 0, None)

        return {
            "item":     item,
            "forecast": forecast,
            "order":    f"{final_model.order}x{final_model.seasonal_order}",
        }
    except Exception as e:
        return {"item": item, "error": str(e)}


#TSB

def _tsb_fit_predict(y: np.ndarray, alpha_d: float, alpha_p: float,
                     h: int,
                     start_month: int = 1,
                     series_start_month: int = 1) -> np.ndarray:
    n = len(y)
    I = (y > 0).astype(float)

    p = float(np.mean(I)) if np.mean(I) > 0 else 0.1
    z = float(np.mean(y[y > 0])) if np.any(y > 0) else 1.0

    for t in range(n):
        p = p + alpha_p * (I[t] - p)
        z = z + alpha_d * (y[t] - z)

    flat_rate = max(p * z, 0.0)

    # Seasonal index — applied only when each month has at least 2 observations
    monthly_sum = np.zeros(12)
    monthly_cnt = np.zeros(12)
    for i, val in enumerate(y):
        m_idx = (series_start_month - 1 + i) % 12
        monthly_sum[m_idx] += val
        monthly_cnt[m_idx] += 1

    with np.errstate(invalid="ignore", divide="ignore"):
        monthly_avg = np.where(monthly_cnt > 0,
                               monthly_sum / monthly_cnt, 0.0)

    overall_avg = np.mean(monthly_avg)

    # All months must have at least 2 observations for the seasonal index to be reliable.
    # Otherwise, a single large one-off demand in a specific month distorts the index.
    if overall_avg > 0 and len(y) >= 24 and monthly_cnt.min() >= 2:
        seasonal_idx = monthly_avg / overall_avg
        seasonal_idx = seasonal_idx / seasonal_idx.mean()
    else:
        seasonal_idx = np.ones(12)

    forecast = np.array([
        flat_rate * seasonal_idx[(start_month - 1 + step) % 12]
        for step in range(h)
    ])
    return np.clip(forecast, 0.0, None)


def _tsb_cv_mae(y: np.ndarray, alpha_d: float, alpha_p: float,
                h: int = 3, n_windows: int = 4,
                series_start_month: int = 1) -> float:
    n         = len(y)
    min_train = max(12, n - n_windows * h)
    errors    = []

    for w in range(n_windows):
        split = min_train + w * h
        if split + h > n:
            break
        y_tr  = y[:split]
        y_val = y[split: split + h]
        val_start_month = (series_start_month - 1 + split) % 12 + 1
        preds = _tsb_fit_predict(y_tr, alpha_d, alpha_p, h,
                                  start_month=val_start_month,
                                  series_start_month=series_start_month)
        errors.extend(np.abs(y_val - preds).tolist())

    return float(np.mean(errors)) if errors else 999.0


def optimise_tsb_backtest(item, train_series: pd.Series,
                           val_series: pd.Series,
                           n_periods: int,
                           n_trials: int = N_OPTUNA_TRIALS) -> dict:
   
    import warnings
    warnings.filterwarnings("ignore")
    import optuna

    try:
        y_train = train_series.values.astype(float)
        y_val   = val_series.values.astype(float)
        y_full  = np.concatenate([y_train, y_val])

        if len(y_train) < 12:
            best_alpha_d, best_alpha_p = 0.2, 0.2
        else:
            ssm = train_series.index[0].month

            def objective(trial):
                alpha_d = trial.suggest_float("alpha_d", 0.05, 0.5)
                alpha_p = trial.suggest_float("alpha_p", 0.05, 0.5)
                # Tuned using internal CV on y_train only — y_val is never seen
                return _tsb_cv_mae(y_train, alpha_d, alpha_p,
                                   h=3, n_windows=4,
                                   series_start_month=ssm)

            study = optuna.create_study(
                direction="minimize",
                sampler=optuna.samplers.TPESampler(seed=42),
            )
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study.optimize(objective, n_trials=n_trials,
                           show_progress_bar=False)
            best_alpha_d = study.best_params["alpha_d"]
            best_alpha_p = study.best_params["alpha_p"]

        full_series_start_month = train_series.index[0].month
        start_month = (val_series.index[-1].month % 12) + 1
        forecast = _tsb_fit_predict(y_full, best_alpha_d, best_alpha_p,
                                    n_periods,
                                    start_month=start_month,
                                    series_start_month=full_series_start_month)

        return {
            "item":     item,
            "forecast": forecast,
            "order":    f"TSB(d={best_alpha_d:.2f}, p={best_alpha_p:.2f})",
            # y_train passed through for MASE denominator calculation in compute_mase_column
            "y_train":  y_train,
        }
    except Exception as e:
        return {"item": item, "error": str(e)}


def optimise_tsb_future(item, full_train_series: pd.Series,
                         n_periods: int,
                         n_trials: int = N_OPTUNA_TRIALS) -> dict:
    import warnings
    warnings.filterwarnings("ignore")
    import optuna

    try:
        y_full = full_train_series.values.astype(float)

        if len(y_full) < 12:
            best_alpha_d, best_alpha_p = 0.2, 0.2
        else:
            ssm = full_train_series.index[0].month

            def objective(trial):
                alpha_d = trial.suggest_float("alpha_d", 0.05, 0.5)
                alpha_p = trial.suggest_float("alpha_p", 0.05, 0.5)
                return _tsb_cv_mae(y_full, alpha_d, alpha_p,
                                   h=3, n_windows=4,
                                   series_start_month=ssm)

            study = optuna.create_study(
                direction="minimize",
                sampler=optuna.samplers.TPESampler(seed=42),
            )
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            study.optimize(objective, n_trials=n_trials,
                           show_progress_bar=False)
            best_alpha_d = study.best_params["alpha_d"]
            best_alpha_p = study.best_params["alpha_p"]

        full_series_start_month = full_train_series.index[0].month
        start_month = (full_train_series.index[-1].month % 12) + 1
        forecast = _tsb_fit_predict(y_full, best_alpha_d, best_alpha_p,
                                    n_periods,
                                    start_month=start_month,
                                    series_start_month=full_series_start_month)

        return {
            "item":     item,
            "forecast": forecast,
            "order":    f"TSB(d={best_alpha_d:.2f}, p={best_alpha_p:.2f})",
        }
    except Exception as e:
        return {"item": item, "error": str(e)}


# MASE

def compute_mase_column(output_long: pd.DataFrame,
                         y_train_map: dict) -> pd.DataFrame:
    """
    [FIX 1 + FIX 3]  Compute MASE using cluster-specific denominators.

    Parameters
    ----------
    output_long : DataFrame containing U Code, Period, y_true, y_pred, Cluster
    y_train_map : {u_code: np.ndarray} — training data for each SKU

    Design rationale:
    Calls shared_metrics.compute_mase() per SKU so that the denominator lag
    (m=12 or m=1) is automatically selected based on the cluster.
    Pre-computing insample_naive_mae and merging via dict has been removed
    because cluster information is now available directly at computation time.
    """
    df = output_long.copy()
    df["abs_error"] = np.abs(df["y_true"] - df["y_pred"])

    mase_per_sku = {}
    rb_per_sku   = {}
    wape_per_sku = {}

    for u_code, grp in df.groupby("U Code"):
        y_true   = grp["y_true"].values
        y_pred   = grp["y_pred"].values
        cluster  = grp["Cluster"].iloc[0]
        y_train  = y_train_map.get(u_code, np.array([]))

        mase_per_sku[u_code] = compute_mase(y_true, y_pred, y_train, cluster)
        rb_per_sku[u_code]   = compute_relative_bias(y_true, y_pred)
        wape_per_sku[u_code] = compute_wape(y_true, y_pred)

    df["MASE"]          = df["U Code"].map(mase_per_sku)
    df["Relative_Bias"] = df["U Code"].map(rb_per_sku)
    df["WAPE"]          = df["U Code"].map(wape_per_sku)
    df["Accuracy"]      = df["Relative_Bias"].map(
        lambda x: accuracy_tier(x) if pd.notna(x) else "N/A"
    )

    # Diagnostics
    n_sku   = df["U Code"].nunique()
    n_valid = df.groupby("U Code")["MASE"].first().notna().sum()
    print(f"\n  [MASE Diagnostics — cluster-aware denominator]")
    print(f"    Total SKUs              : {n_sku:,}")
    print(f"    Valid MASE              : {n_valid:,}")
    print(f"    NaN (zero-demand/short) : {n_sku - n_valid:,}")

    valid_mase = df.groupby("U Code")["MASE"].first().dropna()
    if len(valid_mase):
        print(f"    Mean MASE   : {valid_mase.mean():.4f}")
        print(f"    Median MASE : {valid_mase.median():.4f}")
        print(f"    MASE < 1    : {(valid_mase < 1).sum():,} / {len(valid_mase):,} "
              f"({(valid_mase < 1).mean()*100:.1f}%)")

    # Per-cluster breakdown
    cluster_mase = (
        df.groupby(["U Code", "Cluster"])["MASE"]
        .first().reset_index()
        .groupby("Cluster")["MASE"]
        .agg(mean="mean", median="median", count="count")
    )
    print(f"\n  [MASE by Cluster]")
    print(cluster_mase.to_string())

    return df


# CSV 

def export_standard_csv(backtest_df: pd.DataFrame,
                         forecast_df: pd.DataFrame,
                         output_prefix: str = "croston_arima") -> None:
    """
    Outputs CSV in the same format as LightGBM V8.
    Allows the ensemble integration module to read both files identically.

    backtest: u_code, period, y_true, y_pred, model_name, pred_type
    forecast: u_code, period, y_pred, model_name, pred_type
    """
    bt = backtest_df[["U Code", "period_dt", "y_true", "y_pred", "Cluster"]].copy()
    bt = bt.rename(columns={"U Code": "u_code", "period_dt": "period",
                             "Cluster": "cluster"})
    bt["model_name"] = "croston_arima_tsb"
    bt["pred_type"]  = "monthly"
    bt = bt[["u_code", "period", "y_true", "y_pred", "model_name", "pred_type"]]
    bt_path = f"backtest_{output_prefix}_2025.csv"
    bt.to_csv(bt_path, index=False)
    print(f"  Standard-format backtest : {bt_path}")

    fc = forecast_df[["U Code", "period_dt", "y_pred", "Cluster"]].copy()
    fc = fc.rename(columns={"U Code": "u_code", "period_dt": "period",
                             "Cluster": "cluster"})
    fc["model_name"] = "croston_arima_tsb"
    fc["pred_type"]  = "monthly"
    fc = fc[["u_code", "period", "y_pred", "model_name", "pred_type"]]
    fc_path = f"forecast_{output_prefix}_2026.csv"
    fc.to_csv(fc_path, index=False)
    print(f"  Standard-format forecast : {fc_path}")


# MAIN

def main():
    import time
    t_start = time.time()

    print("=" * 65)
    print("  Croston / ARIMA  V5  (cluster-aware MASE + leakage-free tuning)")
    print(f"  Train (tuning) : {DATE_START} ~ {TRAIN_END}")
    print(f"  Validation     : {VALIDATION_START} ~ {VALIDATION_END}")
    print(f"  Refit          : {DATE_START} ~ {REFIT_END}")
    print(f"  Test (backtest): {TEST_START} ~ {TEST_END}")
    print(f"  MASE denominator: m=12 (smooth/erratic) | m=1 (intermittent/lumpy)")
    print("=" * 65)

    engine = get_engine()

    # STEP 1: Load data
    print("\nSTEP 1. Loading data...")
    pivot = load_monthly_pivot(engine)

    # STEP 2: SKU clustering (based on REFIT_END — no test leakage)
    print(f"\nSTEP 2. SKU Classification (cutoff: {REFIT_END})...")
    pivot_refit = pivot.loc[:REFIT_END]
    class_df    = build_class_df(pivot_refit)

    for_arima   = class_df[class_df["Class"].isin(["smooth", "erratic"])]["U Code"].tolist()
    for_croston = class_df[class_df["Class"].isin(["intermittent", "lumpy"])]["U Code"].tolist()

    # STEP 3: Train/validation/test split
    train_arima   = pivot[for_arima].loc[:TRAIN_END]
    val_arima     = pivot[for_arima].loc[VALIDATION_START:VALIDATION_END]
    test_arima    = pivot[for_arima].loc[TEST_START:TEST_END]

    train_croston = pivot[for_croston].loc[:TRAIN_END]
    val_croston   = pivot[for_croston].loc[VALIDATION_START:VALIDATION_END]
    test_croston  = pivot[for_croston].loc[TEST_START:TEST_END]

    n_test = len(pivot.loc[TEST_START:TEST_END])
    print(f"\n  ARIMA  SKUs : {len(for_arima):,}")
    print(f"  TSB    SKUs : {len(for_croston):,}")
    print(f"  Test rows   : {n_test}  ({TEST_START} ~ {TEST_END})")

    # STEP 4a: ARIMA backtest
    print(f"\nSTEP 4a. ARIMA backtest ({len(for_arima)} SKUs)...")
    arima_results = Parallel(n_jobs=-1, verbose=5)(
        delayed(process_item_backtest)(
            item, train_arima[item], val_arima[item], n_test
        )
        for item in for_arima
    )

    # STEP 4b: TSB backtest
    print(f"\nSTEP 4b. TSB backtest ({len(for_croston)} SKUs)...")
    tsb_results = Parallel(n_jobs=-1, verbose=5)(
        delayed(optimise_tsb_backtest)(
            item, train_croston[item], val_croston[item], n_test
        )
        for item in for_croston
    )

    # STEP 5: Consolidate results
    test_dates = pivot.loc[TEST_START:TEST_END].index
    fmt_index  = test_dates.strftime("%b-%Y")

    final_forecast_bt = {}
    final_orders_bt   = {}
    y_train_map       = {}   # [FIX 3] for MASE denominator calculation

    for res in (arima_results + tsb_results):
        item = res["item"]
        if "error" in res:
            print(f"  [SKIP] {item}: {res['error']}")
            continue
        final_forecast_bt[item] = res["forecast"]
        final_orders_bt[item]   = res["order"]
        if "y_train" in res:
            y_train_map[item] = res["y_train"]

    forecast_bt_df = pd.DataFrame(final_forecast_bt, index=fmt_index).round(4)

    # STEP 6: Convert to long format
    test_all  = pd.concat([test_arima, test_croston], axis=1)
    test_long = (
        test_all.reset_index()
        .melt(id_vars="Month", var_name="U Code", value_name="y_true")
        .assign(Period   = lambda x: x["Month"].dt.strftime("%b-%Y"),
                period_dt= lambda x: x["Month"])
    )
    forecast_long = (
        forecast_bt_df
        .rename_axis("Period")
        .reset_index()
        .melt(id_vars="Period", var_name="U Code", value_name="y_pred")
    )
    output_long = forecast_long.merge(
        test_long[["U Code", "Period", "period_dt", "y_true"]],
        on=["U Code", "Period"], how="left"
    )
    output_long = (
        output_long
        .merge(class_df.rename(columns={"Class": "Cluster"}),
               on="U Code", how="left")
    )

    # STEP 7: Compute MASE [FIX 1 + FIX 3]
    print("\nSTEP 7. MASE computation (cluster-aware denominator)...")
    output_long = compute_mase_column(output_long, y_train_map)

    # Add cumulative forecast
    output_long["cumulative_pred"] = (
        output_long.groupby("U Code")["y_pred"].cumsum()
    )

    order_map = (
        pd.DataFrame.from_dict(final_orders_bt, orient="index",
                               columns=["Model Order"])
        .rename_axis("U Code").reset_index()
    )
    backtest_out = output_long.merge(order_map, on="U Code", how="left")
    backtest_out = backtest_out[[
        "U Code", "Period", "period_dt", "Cluster",
        "y_true", "y_pred", "cumulative_pred",
        "MASE", "Relative_Bias", "Accuracy", "WAPE",
        "Model Order"
    ]]

    # STEP 8a: ARIMA future forecast
    print(f"\nSTEP 8a. ARIMA future forecast ({len(for_arima)} SKUs)...")
    arima_future = Parallel(n_jobs=-1, verbose=5)(
        delayed(process_item_future)(item, pivot[for_arima][item],
                                     FORECAST_MONTHS)
        for item in for_arima
    )

    # STEP 8b: TSB future forecast
    print(f"\nSTEP 8b. TSB future forecast ({len(for_croston)} SKUs)...")
    tsb_future = Parallel(n_jobs=-1, verbose=5)(
        delayed(optimise_tsb_future)(item, pivot[for_croston][item],
                                     FORECAST_MONTHS)
        for item in for_croston
    )

    final_forecast_fc = {}
    final_orders_fc   = {}
    for res in (arima_future + tsb_future):
        item = res["item"]
        if "error" in res:
            print(f"  [SKIP] {item}: {res['error']}")
            continue
        final_forecast_fc[item] = res["forecast"]
        final_orders_fc[item]   = res["order"]

    forecast_dates = pd.date_range(
        start=pivot.index[-1] + pd.DateOffset(months=1),
        periods=FORECAST_MONTHS, freq="MS"
    )
    fmt_future     = forecast_dates.strftime("%b-%Y")
    forecast_fc_df = pd.DataFrame(final_forecast_fc, index=fmt_future).round(4)

    future_long = (
        forecast_fc_df
        .rename_axis("Period")
        .reset_index()
        .melt(id_vars="Period", var_name="U Code", value_name="y_pred")
    )
    future_long["period_dt"]       = pd.to_datetime(future_long["Period"],
                                                     format="%b-%Y")
    future_long["cumulative_pred"] = (
        future_long.groupby("U Code")["y_pred"].cumsum()
    )

    order_map_fc = (
        pd.DataFrame.from_dict(final_orders_fc, orient="index",
                               columns=["Model Order"])
        .rename_axis("U Code").reset_index()
    )
    forecast_out = (
        future_long
        .merge(order_map_fc, on="U Code", how="left")
        .merge(class_df.rename(columns={"Class": "Cluster"}),
               on="U Code", how="left")
    )
    forecast_out = forecast_out[[
        "U Code", "Period", "period_dt", "Cluster",
        "y_pred", "cumulative_pred", "Model Order"
    ]]

    # STEP 9: Save results as CSV
    print("\nSTEP 9. Saving results as CSV...")
    out_bt = backtest_out.drop(columns=["period_dt"])
    out_fc = forecast_out.drop(columns=["period_dt"])
    out_cl = class_df.rename(columns={"Class": "Cluster"})

    out_bt.to_csv("croston_arima_V5_backtest_2025.csv",  index=False)
    out_fc.to_csv("croston_arima_V5_forecast_2026.csv",  index=False)
    out_cl.to_csv("croston_arima_V5_sku_clusters.csv",   index=False)

    print("  -> croston_arima_V5_backtest_2025.csv")
    print("  -> croston_arima_V5_forecast_2026.csv")
    print("  -> croston_arima_V5_sku_clusters.csv")

    # STEP 10: Export standard CSV
    print("\nSTEP 10. Exporting standard-format CSV...")
    export_standard_csv(backtest_out, forecast_out)

    elapsed = time.time() - t_start
    print(f"\n{'='*65}")
    print(f"  Done!  Elapsed: {elapsed/60:.1f} min")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
