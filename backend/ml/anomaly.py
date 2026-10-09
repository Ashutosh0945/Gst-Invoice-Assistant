"""GST anomaly intelligence: an ensemble of Isolation Forest and robust per-feature z-scores (an invoice is ranked by
whichever method finds it MORE unusual). Chosen by benchmark (research/benchmarks_v06.py, 5 seeds): ensemble AUC
0.911±0.007 vs Isolation Forest 0.907±0.021 vs robust z 0.870±0.026; Isolation Forest catches unusual combinations,
robust z catches single extreme values. Features over per-invoice data built only from information
available at prediction time (each invoice is compared with the SAME vendor's EARLIER invoices).
Training is an explicit action (POST /api/v1/ml/anomaly/train); inference is cheap and runs on upload.
An anomaly is a reason to look, never proof of fraud or non-compliance."""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.db.models import AnomalyScore, Gstr2bRecord, Invoice, MlModel
from backend.ml import iforest

MODEL_NAME = "anomaly-iforest"
FEATURES = ["log_amount", "effective_tax_rate", "vendor_amount_deviation", "vendor_invoices_30d", "log_days_since_prev",
            "line_count", "round_amount", "sunday_invoice", "vendor_past_discrepancy_rate", "nonstandard_rate_share"]
LABELS = {"log_amount": "invoice amount", "effective_tax_rate": "tax as a share of taxable value",
          "vendor_amount_deviation": "amount vs this vendor's earlier invoices", "vendor_invoices_30d": "invoices from this vendor in 30 days",
          "log_days_since_prev": "gap since this vendor's previous invoice", "line_count": "number of line items",
          "round_amount": "exact round amount", "sunday_invoice": "dated on a Sunday",
          "vendor_past_discrepancy_rate": "vendor's past discrepancy rate", "nonstandard_rate_share": "lines with non-standard GST rates"}
STANDARD = {0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40}
MIN_TRAIN, MIN_VENDOR_HISTORY = 20, 5


def _key(i: Invoice) -> str:
    return i.vendor_gstin_raw or f"name:{(i.vendor_name_raw or '?').strip().lower()}"


def _when(i: Invoice) -> date:
    return i.invoice_date or (i.created_at.date() if i.created_at else date.today())


def build_features(invoices: list[Invoice], mismatched_ids: set) -> tuple[np.ndarray, list[dict]]:
    """Returns the feature matrix (NaN = unknown) and per-invoice context (vendor history size etc.)."""
    by_vendor: dict[str, list[Invoice]] = {}
    for i in sorted(invoices, key=lambda x: (_when(x), x.created_at or datetime.min.replace(tzinfo=timezone.utc))):
        by_vendor.setdefault(_key(i), []).append(i)
    rows, ctx = {}, {}
    for vk, invs in by_vendor.items():
        for n, inv in enumerate(invs):
            prior = invs[:n]                               # strictly earlier invoices only (no leakage)
            amt = float(inv.grand_total) if inv.grand_total else math.nan
            tax = sum(float(x or 0) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess))
            sub = float(inv.subtotal) if inv.subtotal else math.nan
            p_amt = [math.log1p(float(p.grand_total)) for p in prior if p.grand_total]
            dev = math.nan
            if len(p_amt) >= MIN_VENDOR_HISTORY and not math.isnan(amt):
                med = statistics.median(p_amt)
                mad = statistics.median(abs(a - med) for a in p_amt) or 0.05
                dev = (math.log1p(amt) - med) / (1.4826 * mad)
            d = _when(inv)
            last = _when(prior[-1]) if prior else None
            disc = [p for p in prior if p.id in mismatched_ids or any(f.severity == "ERROR" and f.category == "validation" for f in p.findings)]
            rates = [float(li.gst_rate) for li in inv.items if li.gst_rate is not None]
            rows[inv.id] = [math.log1p(amt) if not math.isnan(amt) else math.nan,
                            tax / sub if sub and sub > 0 else math.nan, dev,
                            float(sum(1 for p in prior if 0 <= (d - _when(p)).days <= 30)),
                            math.log1p((d - last).days) if last and (d - last).days >= 0 else math.nan,
                            float(len(inv.items)) if inv.items else math.nan,
                            1.0 if not math.isnan(amt) and amt >= 10000 and amt % 1000 == 0 else 0.0,
                            1.0 if inv.invoice_date and inv.invoice_date.weekday() == 6 else 0.0,
                            len(disc) / len(prior) if len(prior) >= MIN_VENDOR_HISTORY else math.nan,
                            sum(1 for r in rates if r not in STANDARD) / len(rates) if rates else math.nan]
            ctx[inv.id] = {"vendor_history": len(prior), "vendor": inv.vendor_name_raw,
                           "vendor_median_amount": round(math.expm1(statistics.median(p_amt)), 2) if p_amt else None}
    order = [i.id for i in invoices]
    return np.array([rows[k] for k in order], dtype=float), [ctx[k] for k in order]


def _impute(X: np.ndarray, medians: list[float]) -> np.ndarray:
    """Unknown values become the training median: missing data is NEUTRAL, never evidence of wrongdoing."""
    X = X.copy()
    for j, m in enumerate(medians):
        X[np.isnan(X[:, j]), j] = m
    return X


def _eligible(db: Session) -> list[Invoice]:
    invs = db.execute(select(Invoice).options(selectinload(Invoice.findings), selectinload(Invoice.items))).scalars().all()
    # exclude rejected/failed invoices and suspected duplicates so they don't distort "normal"
    return [i for i in invs if i.status not in ("REJECTED", "FAILED")
            and not any(f.category == "duplicate" and f.severity == "ERROR" for f in i.findings)]


def _mismatched(db: Session) -> set:
    ids = {r.matched_invoice_id for r in db.execute(select(Gstr2bRecord).where(Gstr2bRecord.match_status != "MATCHED")).scalars() if r.matched_invoice_id}
    return ids | {i for (i,) in db.execute(select(Invoice.id).where(Invoice.gstr2b_status == "MISSING_IN_2B")).all()}


def train(db: Session, seed: int = 42) -> dict:
    invs = _eligible(db)
    if len(invs) < MIN_TRAIN:
        return {"status": "insufficient_data", "invoices": len(invs),
                "message": f"Anomaly detection needs at least {MIN_TRAIN} processed invoices to learn what is normal; you have {len(invs)}."}
    X, _ = build_features(invs, _mismatched(db))
    medians = [float(np.nanmedian(X[:, j])) if np.any(~np.isnan(X[:, j])) else 0.0 for j in range(X.shape[1])]
    Xi = _impute(X, medians)
    model = iforest.fit(Xi, n_trees=200, sample_size=256, seed=seed)
    train_scores = iforest.score(model, Xi)
    q1, q3 = np.percentile(Xi, 25, axis=0), np.percentile(Xi, 75, axis=0)
    sd = Xi.std(axis=0)
    rz_scale = np.where(q3 - q1 > 0, (q3 - q1) / 1.349, np.where(sd > 0, sd, 1.0))
    rz_train = np.max(np.abs((Xi - np.array(medians)) / rz_scale), axis=1)
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    art = {"forest": model, "medians": medians, "q1": q1.tolist(), "q3": q3.tolist(),
           "train_scores": sorted(float(s) for s in train_scores), "features": FEATURES,
           "rz_scale": rz_scale.tolist(), "rz_train_scores": sorted(float(s) for s in rz_train),
           "scoring": "ensemble: max(percentile of Isolation Forest score, percentile of robust z) vs training data"}
    db.query(MlModel).filter(MlModel.name == MODEL_NAME).update({"is_active": False})
    m = MlModel(name=MODEL_NAME, version=version, is_active=True, artifact=art, trained_on=len(invs),
                params={"n_trees": 200, "sample_size": model["psi"], "seed": seed, "features": FEATURES,
                        "scoring": "ensemble max-rank (Isolation Forest, robust z)", "model_version_scheme": "UTC timestamp"},
                metrics={"score_p50": float(np.median(train_scores)), "score_p95": float(np.percentile(train_scores, 95))})
    db.add(m)
    db.flush()
    n = score_invoices(db, invs, m)
    db.commit()
    return {"status": "trained", "version": version, "invoices": len(invs), "scored": n}


def active_model(db: Session) -> MlModel | None:
    return db.execute(select(MlModel).where(MlModel.name == MODEL_NAME, MlModel.is_active.is_(True))
                      .order_by(MlModel.created_at.desc())).scalars().first()


def _signals(x: np.ndarray, raw: np.ndarray, art: dict, ctx: dict) -> list[dict]:
    out = []
    for j, f in enumerate(FEATURES):
        if math.isnan(raw[j]):
            continue
        iqr = (art["q3"][j] - art["q1"][j]) or 1e-6
        z = (x[j] - art["medians"][j]) / iqr
        if abs(z) >= 1.5 or (f in ("round_amount", "sunday_invoice") and raw[j] == 1.0 and art["medians"][j] == 0):
            out.append({"feature": f, "label": LABELS[f], "value": round(float(raw[j]), 3),
                        "typical": round(float(art["medians"][j]), 3), "direction": "higher" if z > 0 else "lower", "strength": round(abs(float(z)), 2)})
    out.sort(key=lambda s: -s["strength"])
    if ctx.get("vendor_median_amount") is not None:
        out.append({"feature": "history", "label": "vendor's typical invoice amount", "value": ctx["vendor_median_amount"]})
    return out[:5]


def score_invoices(db: Session, invs: list[Invoice], model: MlModel | None = None) -> int:
    model = model or active_model(db)
    if model is None or not invs:
        return 0
    art = model.artifact
    pool = _eligible(db)
    ids = {i.id for i in invs}
    pool_all = pool + [i for i in invs if i.id not in {p.id for p in pool}]
    X, ctx = build_features(pool_all, _mismatched(db))
    Xi = _impute(X, art["medians"])
    scores = iforest.score(art["forest"], Xi)
    ref = np.array(art["train_scores"])
    rz = np.max(np.abs((Xi - np.array(art["medians"])) / np.array(art.get("rz_scale", [1.0] * Xi.shape[1]))), axis=1)
    rz_ref = np.array(art.get("rz_train_scores", [0.0]))
    previous = {a.invoice_id: a for a in db.execute(select(AnomalyScore).where(AnomalyScore.invoice_id.in_(ids))).scalars()}
    n = 0
    for k, inv in enumerate(pool_all):
        if inv.id not in ids:
            continue
        pct_if = float(100.0 * np.searchsorted(ref, scores[k], side="right") / len(ref))
        pct_rz = float(100.0 * np.searchsorted(rz_ref, rz[k], side="right") / len(rz_ref))
        pct = max(pct_if, pct_rz)
        prio = "high" if pct >= 98 else "medium" if pct >= 93 else "low"
        suff = "sufficient" if ctx[k]["vendor_history"] >= MIN_VENDOR_HISTORY and model.trained_on >= 50 else \
            "limited" if model.trained_on >= MIN_TRAIN else "insufficient"
        old = previous.get(inv.id)
        if old:
            db.delete(old)
        db.add(AnomalyScore(invoice_id=inv.id, model_version=model.version, score=round(float(scores[k]), 5), rank_pct=round(pct, 3),
                            priority=prio, signals=_signals(Xi[k], X[k], art, ctx[k]), data_sufficiency=suff,
                            review_status=old.review_status if old else "open", review_note=old.review_note if old else None,
                            reviewed_by=old.reviewed_by if old else None, reviewed_at=old.reviewed_at if old else None))
        n += 1
    db.flush()
    return n


def score_one_safely(db: Session, inv: Invoice) -> None:
    """Called after upload. Never raises: an ML failure must not break invoice processing."""
    import logging
    try:
        if active_model(db):
            score_invoices(db, [inv])
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logging.getLogger(__name__).exception("Anomaly scoring failed for invoice %s", inv.id)
