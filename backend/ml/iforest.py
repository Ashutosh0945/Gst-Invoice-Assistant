"""Isolation Forest (Liu, Ting & Zhou 2008) in NumPy, serialisable to JSON.
Same algorithm and scoring as scikit-learn's IsolationForest; tests/test_ml.py checks the rankings agree."""
from __future__ import annotations

import math

import numpy as np

EULER = 0.5772156649


def c(n: float) -> float:
    """Average path length of an unsuccessful BST search over n points."""
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    return 2.0 * (math.log(n - 1) + EULER) - 2.0 * (n - 1) / n


def _build(X: np.ndarray, rng: np.random.Generator, max_depth: int) -> dict:
    feat, thr, left, right, size = [], [], [], [], []

    def grow(idx: np.ndarray, depth: int) -> int:
        node = len(feat)
        feat.append(-1); thr.append(0.0); left.append(-1); right.append(-1); size.append(len(idx))
        if depth >= max_depth or len(idx) <= 1:
            return node
        sub = X[idx]
        span = sub.max(axis=0) - sub.min(axis=0)
        usable = np.flatnonzero(span > 0)
        if usable.size == 0:
            return node
        f = int(rng.choice(usable))
        lo, hi = sub[:, f].min(), sub[:, f].max()
        t = float(rng.uniform(lo, hi))
        mask = sub[:, f] < t
        feat[node], thr[node] = f, t
        left[node] = grow(idx[mask], depth + 1)
        right[node] = grow(idx[~mask], depth + 1)
        return node

    grow(np.arange(len(X)), 0)
    return {"feature": feat, "threshold": thr, "left": left, "right": right, "size": size}


def fit(X: np.ndarray, n_trees: int = 200, sample_size: int = 256, seed: int = 42) -> dict:
    X = np.asarray(X, dtype=float)
    rng = np.random.default_rng(seed)
    psi = min(sample_size, len(X))
    max_depth = int(math.ceil(math.log2(max(psi, 2))))
    trees = []
    for _ in range(n_trees):
        idx = rng.choice(len(X), size=psi, replace=False)
        trees.append(_build(X[idx], rng, max_depth))
    return {"trees": trees, "psi": psi, "n_trees": n_trees, "seed": seed}


def _path(tree: dict, x: np.ndarray) -> float:
    n, depth = 0, 0
    while tree["left"][n] != -1:
        n = tree["left"][n] if x[tree["feature"][n]] < tree["threshold"][n] else tree["right"][n]
        depth += 1
    return depth + c(tree["size"][n])


def score(model: dict, X: np.ndarray) -> np.ndarray:
    """Anomaly score in (0, 1]: ~0.5 normal, close to 1 very unusual. NOT a probability of fraud."""
    X = np.asarray(X, dtype=float)
    norm = c(model["psi"])
    out = np.empty(len(X))
    for i, x in enumerate(X):
        h = np.mean([_path(t, x) for t in model["trees"]])
        out[i] = 2.0 ** (-h / norm) if norm else 0.5
    return out
