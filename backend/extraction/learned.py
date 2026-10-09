"""GST-LayoutKIE: a learned, layout-aware key-information extractor for GST invoices.

Each word is classified into a BIO label (backend/extraction/labels.py) from hashed features of:
  the word (text, shape, prefix/suffix, regex flags), its position on the page, the words to its
  left on the same line (the "label" that usually precedes a value) and the word above it.
The classifier is a multinomial logistic regression over 2**14 hashed features. Inference is plain
numpy (no scikit-learn or GPU needed), so it runs inside the existing serverless API. Training lives
in research/train_kie.py. Predicted labels are grouped and assembled into InvoiceData by the same
code the LayoutLMv3 path uses (backend/extraction/assemble.py).
"""
from __future__ import annotations

import re
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from backend.extraction.labels import LABELS

D = 2 ** 14
N_NUM = 8
MODEL_PATH = Path(__file__).resolve().parent / "models" / "gst_layoutkie_crf_v2.npz"   # LayoutKIE-CRF (see research/)
RX = {
    "gstin": re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"),
    "date": re.compile(r"^(\d{1,2}[/.\-](\d{1,2}|[A-Za-z]{3})[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2})$"),
    "amount": re.compile(r"^-?(\d{1,3}(,\d{2,3})+|\d+)\.\d{2}$"),
    "int": re.compile(r"^\d+$"),
    "pct": re.compile(r"^\d+(\.\d+)?%$"),
    "hsn": re.compile(r"^\d{4}(\d{2}){0,2}$"),
    "money_prefix": re.compile(r"^(rs\.?|inr|₹)$", re.I),
}


def _h(s: str) -> int:
    return N_NUM + zlib.crc32(s.encode("utf-8", "ignore")) % (D - N_NUM)


def _shape(t: str) -> str:
    s = re.sub(r"[A-Z]", "A", re.sub(r"[a-z]", "a", re.sub(r"\d", "9", t)))
    return re.sub(r"(.)\1+", r"\1\1", s)[:12]


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9%]", "", t.lower())


def lines_of(words: list[tuple[str, tuple]]) -> list[list[int]]:
    """Groups word indices into visual lines (by vertical overlap), each sorted left to right."""
    order = sorted(range(len(words)), key=lambda i: ((words[i][1][1] + words[i][1][3]) / 2, words[i][1][0]))
    out: list[list[int]] = []
    for i in order:
        y0, y1 = words[i][1][1], words[i][1][3]
        cy, h = (y0 + y1) / 2, max(1.0, y1 - y0)
        if out:
            j = out[-1][-1]
            ly = (words[j][1][1] + words[j][1][3]) / 2
            if abs(cy - ly) < 0.55 * h:
                out[-1].append(i)
                continue
        out.append([i])
    return [sorted(l, key=lambda i: words[i][1][0]) for l in out]


def featurize(words: list[tuple[str, tuple]], width: float, height: float) -> tuple[list[list[int]], np.ndarray, list[list[int]]]:
    """Returns (hashed feature ids per word, numeric features [n, N_NUM], lines)."""
    lines = lines_of(words)
    line_of, pos_in = {}, {}
    for li, l in enumerate(lines):
        for k, i in enumerate(l):
            line_of[i], pos_in[i] = li, k
    alpha_line = [sum(1 for i in l if re.search(r"[A-Za-z]{2}", words[i][0])) >= max(3, 0.6 * len(l)) for l in lines]
    feats, num = [], np.zeros((len(words), N_NUM), np.float32)
    for i, (t, (x0, y0, x1, y1)) in enumerate(words):
        li, k, line = line_of[i], pos_in[i], lines[line_of[i]]
        n = _norm(t)
        f = [f"w={n}", f"sh={_shape(t)}", f"p3={n[:3]}", f"s3={n[-3:]}", f"len={min(len(t), 16)}"]
        f += [f"rx={k2}" for k2, rx in RX.items() if rx.match(t)]
        if any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
            f.append("alnum")
        if "/" in t or "-" in t:
            f.append("has_sep")
        cx, cy = (x0 + x1) / 2 / width, (y0 + y1) / 2 / height
        f += [f"xb={int(cx * 8)}", f"yb={int(cy * 8)}", f"xyb={int(cx * 4)}_{int(cy * 4)}", f"first={k == 0}", f"last={k == len(line) - 1}"]
        left = [_norm(words[j][0]) for j in line[max(0, k - 3):k]]
        for d, lw in enumerate(reversed(left), 1):
            f.append(f"l{d}={lw}")
            f.append(f"lsh{d}={_shape(words[line[k - d]][0])}")
        if left:
            f.append("L2=" + "_".join(left[-2:]))
            f.append("L3=" + "_".join(left))
        else:
            f.append("L=NONE")
        if k + 1 < len(line):
            f.append(f"r1={_norm(words[line[k + 1]][0])}")
        first_alpha = next((_norm(words[j][0]) for j in line if re.search(r"[A-Za-z]", words[j][0])), "")
        f.append(f"line0={first_alpha}")
        # word directly above (overlapping horizontally) and the column header above
        up, hdr = None, None
        for lj in range(li - 1, max(-1, li - 30), -1):
            for j in lines[lj]:
                a0, a1 = words[j][1][0], words[j][1][2]
                if a0 - 3 <= (x0 + x1) / 2 <= a1 + 3 or (x0 - 3 <= a0 <= x1 + 3):
                    if up is None and lj >= li - 2:
                        up = _norm(words[j][0])
                    if hdr is None and alpha_line[lj] and lj < li:
                        hdr = _norm(words[j][0])
                    break
            if hdr is not None:
                break
        f.append(f"up={up}")
        # Column-header features were dropped after ablation: they let the model memorise training layouts
        # (unseen-layout item accuracy 97.7% with them vs 99.8% without; research/results/e5b_ablation_confirm.json).
        nnum = sum(1 for j in line if re.search(r"\d", words[j][0]))
        f.append(f"numline={min(nnum, 8)}")
        feats.append([_h(s) for s in f])
        num[i] = [cx, cy, (x1 - x0) / width, (y1 - y0) / height, k / max(1, len(line) - 1), nnum / max(1, len(line)),
                  float(alpha_line[li]), li / max(1, len(lines) - 1)]
    return feats, num, lines


def predict_proba(W: np.ndarray, b: np.ndarray, feats, num) -> np.ndarray:
    logits = np.empty((len(feats), W.shape[0]), np.float32)
    for i, ids in enumerate(feats):
        logits[i] = W[:, ids].sum(axis=1) + W[:, :N_NUM] @ num[i] + b
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits)
    return p / p.sum(axis=1, keepdims=True)


@lru_cache(maxsize=2)
def load_model(path: str = str(MODEL_PATH)):
    """Returns (W, b, classes) for the linear model, or (W, b, classes, T) for the CRF (T = label transitions)."""
    z = np.load(path)
    base = (z["W"].astype(np.float32), z["b"].astype(np.float32), [str(c) for c in z["classes"]])
    return base + (z["T"].astype(np.float32),) if "T" in z.files else base


def _unary(W, b, feats, num):
    u = np.empty((len(feats), W.shape[0]), np.float32)
    for i, ids in enumerate(feats):
        u[i] = W[:, ids].sum(axis=1) + W[:, :N_NUM] @ num[i] + b
    return u


def crf_decode(u: np.ndarray, T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Viterbi best path + forward-backward marginals for a linear-chain CRF (log space, pure NumPy)."""
    n, c = u.shape
    back = np.zeros((n, c), np.int32)
    score = u[0].copy()
    for t in range(1, n):
        cand = score[:, None] + T + u[t][None, :]
        back[t] = cand.argmax(axis=0)
        score = cand.max(axis=0)
    path = np.zeros(n, np.int32)
    path[-1] = score.argmax()
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    lse = lambda a, ax: (m := a.max(axis=ax, keepdims=True)) + np.log(np.exp(a - m).sum(axis=ax, keepdims=True))  # noqa: E731
    alpha = np.zeros((n, c), np.float32); beta = np.zeros((n, c), np.float32)
    alpha[0] = u[0]
    for t in range(1, n):
        alpha[t] = lse(alpha[t - 1][:, None] + T, 0)[0] + u[t]
    for t in range(n - 2, -1, -1):
        beta[t] = lse(T + (u[t + 1] + beta[t + 1])[None, :], 1)[:, 0]
    logz = lse(alpha[-1][None, :], 1)[0, 0]
    marg = np.exp(alpha + beta - logz)
    return path, marg


def predict_labels(words, width, height, model=None) -> tuple[list[str], list[float], list[list[int]]]:
    model = model or load_model()
    W, b, classes = model[:3]
    feats, num, lines = featurize(words, width, height)
    if len(model) == 4:                       # linear-chain CRF over the reading order
        order = [i for line in lines for i in line]
        path, marg = crf_decode(_unary(W, b, [feats[i] for i in order], num[order]), model[3])
        labels, confs = [None] * len(words), [0.0] * len(words)
        for pos, i in enumerate(order):
            labels[i], confs[i] = classes[path[pos]], float(marg[pos, path[pos]])
        return labels, confs, lines
    p = predict_proba(W, b, feats, num)
    idx = p.argmax(axis=1)
    return [classes[i] for i in idx], [float(p[n, i]) for n, i in enumerate(idx)], lines


# ----------------------------------------------------------------------------- GST-rule value repair
_TO_DIGIT = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "i": "1", "|": "1", "S": "5", "s": "5",
                           "B": "8", "Z": "2", "z": "2", "G": "6", "b": "6", "q": "9", "g": "9"})
NUMERIC = {"SUBTOTAL", "TOTAL_CGST", "TOTAL_SGST", "TOTAL_IGST", "GRAND_TOTAL", "ROUND_OFF", "ITEM_QTY", "ITEM_PRICE",
           "ITEM_TAXABLE", "ITEM_CGST", "ITEM_SGST", "ITEM_IGST", "ITEM_TOTAL", "ITEM_HSN", "ITEM_GSTRATE"}


def _repair_amount(t: str) -> str:
    t = re.sub(r"^(rs\.?|inr|₹)\s*(?=\d)", "", t.strip(), flags=re.I)      # glued currency prefix
    if re.fullmatch(r"(rs\.?|inr|₹|rs)", t.strip(), re.I):
        return ""                               # currency word next to an amount: not part of the number
    if not re.search(r"\d", t):
        return t                                # nothing numeric to repair; leave as read
    t = t.translate(_TO_DIGIT)
    # "1,234.56" vs OCR swapping ',' and '.': the LAST separator followed by exactly 2 digits is the decimal point
    m = re.match(r"^(-?[\d.,]*?)[.,](\d{2})(%?)$", t)
    if m:
        t = m.group(1).replace(".", "").replace(",", "") + "." + m.group(2) + m.group(3)
    return t


def _repair_gstin(t: str) -> str:
    """GSTIN = 2 digits, 5 letters, 4 digits, letter, 1 alnum, 'Z', checksum. Fix confusable characters by
    position, then, if the checksum still fails, try single confusable swaps until it validates."""
    from backend.validation.gst import gstin_checksum

    t = re.sub(r"[^0-9A-Za-z]", "", t)
    if len(t) == 15 and t[12] in "lI|":
        t = t[:12] + "1" + t[13:]               # 13th character is usually a digit (entity number)
    t = t.upper()
    if len(t) != 15:
        return t
    digits, letters = {0, 1, 7, 8, 9, 10}, {2, 3, 4, 5, 6, 11}
    to_l = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}
    c = [ch.translate(_TO_DIGIT) if k in digits else to_l.get(ch, ch) if k in letters else ch for k, ch in enumerate(t)]
    c[13] = "Z" if c[13] in "Z2" else c[13]
    s = "".join(c)
    if gstin_checksum(s[:14]) == s[14]:
        return s
    pairs = {"0": "O", "O": "0", "1": "I", "I": "1", "L": "1", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2"}
    for k in (12, 14):
        if s[k] in pairs:
            alt = s[:k] + pairs[s[k]] + s[k + 1:]
            if gstin_checksum(alt[:14]) == alt[14]:
                return alt
    return s


def repair(entity: str, text: str) -> str:
    if entity in ("VENDOR_GSTIN", "BUYER_GSTIN"):
        return _repair_gstin(text)
    if entity in NUMERIC:
        return _repair_amount(text)
    if entity == "INVOICE_DATE":
        return re.sub(r"(?<=\d)[Oo](?=\d|$)|^[Oo](?=\d)", "0", re.sub(r"(?<=\d)[lI](?=\d|[/.\-])", "1", text))
    return text


# ----------------------------------------------------------------------------- OCR token normaliser
_GLUE_LABEL = re.compile(r"^([A-Za-z][A-Za-z./ ]*?:)(\S+)$")               # "PartyGSTIN:19DZ..."  -> "PartyGSTIN:" "19DZ..."
_GLUE_CUR = re.compile(r"^(Rs\.?|INR|₹)(\d[\d,]*\.?\d*)$", re.I)         # "Rs.2153.00"         -> "Rs." "2153.00"
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")                                  # "TaxInvoiceNo:"      -> "Tax" "Invoice" "No:"
_MONTH_FIX = str.maketrans({"1": "l", "0": "o", "5": "s"})


def _split_box(text_parts, box):
    x0, y0, x1, y1 = box
    total = sum(len(t) for t in text_parts) or 1
    out, x = [], x0
    for t in text_parts:
        w = (x1 - x0) * len(t) / total
        out.append((t, (x, y0, x + w, y1)))
        x += w
    return out


def normalize_ocr_tokens(words):
    """Real OCR often glues a label to its value, a currency to its amount, or CamelCases multi-word labels.
    Split them back into the word structure the extractor expects, sharing the box proportionally."""
    out = []
    for t, box in words:
        parts = [t]
        m = _GLUE_LABEL.match(t)
        if m and not re.fullmatch(r"\d{1,2}:\d{2}", t):
            parts = [m.group(1), m.group(2)]
        m = _GLUE_CUR.match(parts[-1])
        if m:
            parts = parts[:-1] + [m.group(1), m.group(2)]
        if len(parts[0]) > 4 and parts[0][0].isupper() and _CAMEL.search(parts[0]) and not re.search(r"\d", parts[0]):
            parts = _CAMEL.split(parts[0]) + parts[1:]
        parts = [re.sub(r"(?<=[-/. ])([A-Za-z][A-Za-z0-9]{2})(?=[-/. ]\d{2,4}$)",
                        lambda mm: mm.group(1)[0] + mm.group(1)[1:].translate(_MONTH_FIX), p) for p in parts]
        out.extend(_split_box(parts, box) if len(parts) > 1 else [(parts[0], box)])
    return out


def extract(words: list[tuple[str, tuple]], width: float, height: float, model=None, repair_values: bool = True,
            normalize: bool = True):
    """words: [(text, (x0, y0, x1, y1))] in page coordinates -> InvoiceData."""
    from backend.extraction.assemble import assemble_invoice, group_entities

    if not words:
        from backend.schemas import InvoiceData
        return InvoiceData()
    if normalize:
        words = normalize_ocr_tokens(words)
    labels, confs, lines = predict_labels(words, width, height, model)
    return decode(words, labels, confs, lines, repair_values)


def decode(words, labels, confs, lines, repair_values: bool = True):
    """BIO labels (from any tagger: this model, a CRF, LayoutLMv3...) -> InvoiceData, with GST-rule repair."""
    from backend.extraction.assemble import assemble_invoice, group_entities

    preds, prev = [], {}
    for line in lines:                      # reading order: line by line, left to right
        for i in line:
            lab = labels[i]
            if lab.startswith("I-") and prev.get("ent") != lab[2:]:
                lab = "B-" + lab[2:]          # repair an I- that doesn't continue anything
            prev = {"ent": lab[2:] if lab != "O" else None}
            x0, y0, x1, y1 = words[i][1]
            text = repair(lab[2:], words[i][0]) if repair_values and lab != "O" else words[i][0]
            if text == "":
                continue
            preds.append((text, lab, confs[i], 0, y0, y1 - y0))
    return assemble_invoice(group_entities(preds))


def is_available() -> bool:
    return MODEL_PATH.exists()


assert set(LABELS)  # labels shared with the LayoutLMv3 path
