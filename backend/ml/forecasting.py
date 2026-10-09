"""Predictive GST analytics with honest model selection.

Pipeline: query -> monthly aggregation (missing months filled with 0 and listed) -> history check ->
baselines (last value, 3-month moving average) + candidates (simple & Holt exponential smoothing, linear trend)
-> chronological holdout (last h months) -> MAE / RMSE / MASE -> a candidate is chosen ONLY if it beats the
naive baseline -> refit on all data -> forecast with an ~80% interval from holdout errors.
Forecasts of GST on purchases are estimates, never tax liability or eligible ITC."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

import numpy as np

MIN_MONTHS = 8
SERIES = {"purchase_value": "Monthly purchase value (₹)", "gst_on_purchases": "Monthly GST on purchases (₹)",
          "invoice_count": "Invoices per month", "gstr2b_records": "GSTR-2B records per month (reconciliation workload)",
          "issues": "New invoices needing review per month"}


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def monthly(points: list[tuple[date, float]]) -> tuple[list[str], np.ndarray, list[str]]:
    if not points:
        return [], np.array([]), []
    acc = defaultdict(float)
    for d, v in points:
        acc[d.strftime("%Y-%m")] += v
    months = _months(min(d for d, _ in points), max(d for d, _ in points))
    filled = [m for m in months if m not in acc]
    return months, np.array([acc.get(m, 0.0) for m in months]), filled


# ---------------------------------------------------------------------------- models: fit(y) -> predict(h)
def naive(y, h):
    return np.repeat(y[-1], h)


def moving_avg(y, h, k=3):
    return np.repeat(np.mean(y[-k:]), h)


def ses(y, h):
    best = None
    for a in np.linspace(0.05, 0.95, 19):
        lvl, sse = y[0], 0.0
        for t in range(1, len(y)):
            sse += (y[t] - lvl) ** 2
            lvl = a * y[t] + (1 - a) * lvl
        if best is None or sse < best[0]:
            best = (sse, lvl)
    return np.repeat(best[1], h)


def holt(y, h):
    if len(y) < 3:
        return naive(y, h)
    best = None
    for a in np.linspace(0.1, 0.9, 9):
        for b in np.linspace(0.05, 0.5, 10):
            lvl, tr, sse = y[0], y[1] - y[0], 0.0
            for t in range(1, len(y)):
                pred = lvl + tr
                sse += (y[t] - pred) ** 2
                nl = a * y[t] + (1 - a) * (lvl + tr)
                tr = b * (nl - lvl) + (1 - b) * tr
                lvl = nl
            if best is None or sse < best[0]:
                best = (sse, lvl, tr)
    return np.array([max(0.0, best[1] + (i + 1) * best[2]) for i in range(h)])


def linear(y, h):
    x = np.arange(len(y))
    b, a = np.polyfit(x, y, 1)
    return np.array([max(0.0, a + b * (len(y) + i)) for i in range(h)])


def seasonal_naive(y, h):
    """Same month last year (needs 12+ months)."""
    if len(y) < 12:
        return naive(y, h)
    return np.array([y[len(y) - 12 + (i % 12)] for i in range(h)])


MODELS = {"naive (last month)": naive, "seasonal naive (same month last year)": seasonal_naive, "moving average (3 months)": moving_avg, "simple exponential smoothing": ses,
          "Holt exponential smoothing": holt, "linear trend": linear}


def _metrics(actual, pred, train):
    err = actual - pred
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err ** 2)))
    scale = float(np.mean(np.abs(np.diff(train)))) if len(train) > 1 else 0.0
    return {"MAE": round(mae, 2), "RMSE": round(rmse, 2), "MASE": round(mae / scale, 3) if scale else None}


def forecast_series(months: list[str], y: np.ndarray, horizon: int = 3, filled: list[str] | None = None) -> dict:
    base = {"history": [{"month": m, "value": round(float(v), 2)} for m, v in zip(months, y)], "filled_missing_months": filled or [],
            "label": "Estimate — not tax liability or eligible ITC.", "min_months_required": MIN_MONTHS}
    if len(y) < MIN_MONTHS:
        return {**base, "status": "insufficient_history",
                "message": f"Forecasts need at least {MIN_MONTHS} months of history to evaluate fairly; there are {len(y)}. Showing history only."}
    h = max(2, min(3, len(y) // 4))
    train, test = y[:-h], y[-h:]
    # Rolling-origin evaluation: each model is scored on up to 3 past windows (not one), so the choice
    # isn't decided by a single noisy holdout. The seasonal model is only a candidate with 12+ months.
    folds = [k for k in range(3) if len(y) - h - k * h >= max(5, MIN_MONTHS - h)]
    names = [m for m in MODELS if not (m.startswith("seasonal") and len(y) - h - max(folds) * h < 12)]
    cv = {m: [] for m in names}
    for k in folds:
        cut = len(y) - h - k * h
        tr, te = y[:cut], y[cut:cut + h]
        for m in names:
            cv[m].append(float(np.mean(np.abs(te - MODELS[m](tr, h)))))
    evals = {}
    for name in names:
        pred = MODELS[name](train, h)
        evals[name] = {**_metrics(test, pred, train), "rolling_MAE": round(float(np.mean(cv[name])), 2), "folds": len(cv[name]),
                       "holdout_predictions": [round(float(p), 2) for p in pred]}
    naive_cv = evals["naive (last month)"]["rolling_MAE"]
    best = min(evals, key=lambda k: evals[k]["rolling_MAE"])
    justified = best != "naive (last month)" and evals[best]["rolling_MAE"] < 0.95 * naive_cv     # must beat naive by 5%+
    chosen = best if justified else "naive (last month)"
    fc = MODELS[chosen](y, horizon)
    rmse = evals[chosen]["RMSE"]
    last = months[-1]
    yy, mm = int(last[:4]), int(last[5:])
    out = []
    for i in range(horizon):
        mm += 1
        if mm > 12:
            yy, mm = yy + 1, 1
        w = 1.28 * rmse * math.sqrt(i + 1)
        out.append({"month": f"{yy}-{mm:02d}", "forecast": round(float(fc[i]), 2), "low": round(max(0.0, float(fc[i]) - w), 2), "high": round(float(fc[i]) + w, 2)})
    return {**base, "status": "ok", "model": chosen, "model_version": "forecast-v1",
            "selection": (f"Chosen because it had the lowest rolling-origin error over {evals[chosen]['folds']} past windows and beat the naive baseline by 5% or more." if justified else
                          "No candidate beat the naive baseline by at least 5% across the past windows, so the naive forecast is used."),
            "holdout": {"months": months[-h:], "actual": [round(float(v), 2) for v in test]}, "evaluation": evals,
            "forecast": out, "interval": "~80% range from holdout RMSE (widens with horizon)",
            "data_range": {"from": months[0], "to": months[-1], "months": len(y)}}
