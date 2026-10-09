"""Train GST-LayoutKIE (multinomial logistic regression on hashed layout features) and export numpy weights."""
from __future__ import annotations

import time

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.linear_model import SGDClassifier

from backend.extraction import learned as K
from research.gst_synth import generate
from research.noise import add_noise


def build(docs_spec, noise_rate=0.0, noise_mix=False):
    rows, cols, vals, y = [], [], [], []
    r = 0
    for lid, seed in docs_spec:
        d = generate(lid, seed)
        rate = noise_rate if not noise_mix else [0.0, 0.05, 0.1, noise_rate][seed % 4]
        words, labels = add_noise(d.words, d.labels, rate, seed, d.width, d.height)
        feats, num, _ = K.featurize(words, d.width, d.height)
        for i, ids in enumerate(feats):
            for c in set(ids):
                rows.append(r); cols.append(c); vals.append(1.0)
            for c in range(K.N_NUM):
                rows.append(r); cols.append(c); vals.append(float(num[i, c]))
            y.append(labels[i]); r += 1
    return csr_matrix((vals, (rows, cols)), shape=(r, K.D), dtype=np.float32), np.array(y)


def train(docs_spec, noise_rate=0.1, noise_mix=True, seed=0, epochs=15):
    t = time.time()
    X, y = build(docs_spec, noise_rate, noise_mix)
    clf = SGDClassifier(loss="log_loss", alpha=2e-6, max_iter=epochs, tol=None, random_state=seed)
    clf.fit(X, y)
    W = clf.coef_.astype(np.float32)
    b = clf.intercept_.astype(np.float32)
    return (W, b, list(clf.classes_)), {"tokens": X.shape[0], "seconds": round(time.time() - t, 1)}


def save(model, path=K.MODEL_PATH):
    W, b, classes = model
    np.savez_compressed(path, W=W.astype(np.float16), b=b, classes=np.array(classes))
