import numpy as np
import pandas as pd
from typing import Optional


# Cluster-specific MASE denominator lag
MASE_LAG = {
    "smooth":       12,   # Seasonal Naive — seasonality present, low zero-denominator risk
    "erratic":      12,   # Frequent demand, seasonal pattern meaningful
    "intermittent":  1,   # Sparse demand, m=12 denominator almost always zero
    "lumpy":         1,   # Most sparse, m=12 completely inappropriate
}


def compute_mase(
    y_true:  np.ndarray,
    y_pred:  np.ndarray,
    y_train: np.ndarray,
    cluster: str,
) -> float:
    """
    MASE with cluster-specific denominator.

    Parameters
    ----------
    y_true  : Actual values over the test period (12 months)
    y_pred  : Forecast values over the test period (12 months)
    y_train : Actual values over the training period (used to compute MASE denominator)
    cluster : "smooth" | "erratic" | "intermittent" | "lumpy"

    Returns
    -------
    float or np.nan
    """
    # Zero-demand U codes: evaluation not meaningful
    if np.sum(y_true) == 0:
        return np.nan

    m = MASE_LAG.get(cluster, 1)

    if len(y_train) <= m:
        return np.nan

    mae_naive = np.mean(np.abs(y_train[m:] - y_train[:-m]))

    if mae_naive == 0:
        return np.nan

    mae_forecast = np.mean(np.abs(y_true - y_pred))
    return float(mae_forecast / mae_naive)


def compute_relative_bias(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Relative Bias = (sum(pred) - sum(true)) / sum(true)

    Positive: over-forecast (excess inventory risk)
    Negative: under-forecast (stock-out risk — more critical in procurement)
    """
    total_true = np.sum(y_true)
    if total_true == 0:
        return np.nan
    return float((np.sum(y_pred) - total_true) / total_true)


def compute_wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    WAPE = sum(|actual - pred|) / sum(actual) * 100

    For portfolio-level volume accuracy only.
    Not used for per-SKU model selection.
    """
    total_true = np.sum(np.abs(y_true))
    if total_true == 0:
        return np.nan
    return float(np.sum(np.abs(y_true - y_pred)) / total_true * 100)


def accuracy_tier(rb: float) -> str:
    """Accuracy tier based on Relative Bias."""
    if np.isnan(rb):    return "N/A"
    if abs(rb) < 0.30:  return "High Accuracy"
    if abs(rb) <= 0.50: return "Medium Accuracy"
    return "Low Accuracy"


def mase_lag_for_cluster(cluster: str) -> int:
    """Returns the MASE lag for a given cluster (for documentation / debugging)."""
    return MASE_LAG.get(cluster, 1)