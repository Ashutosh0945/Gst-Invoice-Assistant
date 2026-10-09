# Learning to Read Unseen Indian GST Invoice Layouts on a CPU: Synthetic Layout Diversity, Structured Prediction and OCR-Aware Normalisation

*Conference-paper draft (6–8 pages). Every number is produced by code in `research/` from `research/results/*.json`.
Regenerate: `python -m research.rigor run 1|2|3` → `python -m research.rigor aggregate` → `python -m research.real_ocr ocr 0 24` →
`python -m research.real_ocr eval` → `python -m research.make_report` and `python -m research.make_report rigorous`.*

## Abstract
Indian businesses must extract GSTINs, invoice numbers, tax amounts and line items from supplier invoices in countless layouts to
reconcile input tax credit (ITC) against GSTR-2B. Template rules break on unseen layouts; large document transformers need GPUs and
annotated data that does not exist publicly for Indian GST invoices. We contribute (1) **GSTInvoice-Synth**, a generator of 48
structurally different GST invoice layouts with exact word-level labels and an unseen-layout evaluation protocol; (2) **LayoutKIE-CRF**,
a linear-chain CRF over hashed lexical, positional and left-context features whose 50 KB weights run in ~12 ms per invoice on a CPU
with a pure-NumPy decoder (bit-exact with CRFsuite); (3) **GST-aware value repair and OCR token normalisation**. Across three independent
runs on layouts never seen in training, LayoutKIE-CRF reaches **99.6 ± 0.6% field accuracy and 95.4% fully-correct invoices**, versus
44.9 ± 3.2% and 0% for the best rule-based extractor (McNemar p < 0.001); sequence modelling significantly improves fully-correct
invoices over an identical linear model (95.4% vs 78.3%, p < 0.0001). On **real OCR** (RapidOCR), accuracy drops to 75.8%; our
normaliser recovers it to **85.2%** (header fields 63.2% → 96.7%), and a camera-capture pipeline lifts phone-style photos from
**31.4% to 84.5%**, close to clean scans. We also document failure modes: value-format shift between invoice generators and raw photos.

## 1. Introduction
- GST compliance and ITC reconciliation depend on correct field extraction from heterogeneous supplier invoices.
- No public annotated Indian GST invoice dataset exists [HF forum request; AgamiAI "GST documents coming soon"]; GPU models are costly for MSMEs.
- Research questions: **RQ1** Can a CPU model trained only on synthetic layouts generalise to unseen layouts? **RQ2** Does structured
  (sequence) prediction matter? **RQ3** How large is the gap on real OCR, and what closes it? **RQ4** What drives generalisation:
  layout variety, data volume, which features?
- Contributions: dataset generator + protocol; LayoutKIE-CRF; GST-aware repair and OCR normalisation; rigorous evaluation (multi-run,
  CIs, significance, real OCR, ablations, out-of-distribution analysis); integration into a working GST system ("rules compute, AI explains").

## 2. Related work
Visually-rich document KIE: LayoutLM/LayoutLMv2/LayoutLMv3, Donut, Florence-2; graph/CRF-based KIE; invoice and receipt datasets:
FATURA (10k invoices, 50 layouts, CC-BY-NC), SROIE, CORD, DocILE, FUNSD; synthetic document generation and sim-to-real; constraint-based
OCR post-correction. [Add 20–30 references; position our work as the CPU/low-resource, Indian-GST-specific end of this space.]

## 3. GSTInvoice-Synth
Layout = structure: header arrangement (split / stacked / right-vendor), label vocabulary ("Invoice No:", "Bill #", "Tax Invoice No:"…),
date formats, Indian/western/plain number formats, currency prefixes, column order and names, optional per-line tax columns, fonts,
totals placement, distractors (bank details, terms, signatures). v2 layouts (24–47) add inline field pairs and colon-style totals.
Document = random content: checksum-valid GSTINs across 10 states, intra- vs inter-state tax (CGST+SGST vs IGST), 1–6 items with HSN/SAC
and GST slabs, rounding. 25 entity types, BIO word labels. **Protocol:** train layouts 0–15, test on **unseen layouts 16–23** with disjoint seeds.

## 4. Method
4.1 Features (2^14 hashed + 8 numeric): word text/shape/affixes, regex flags (GSTIN, date, amount, integer, %, HSN-like), position buckets,
1–3 words to the left on the same line, first word of the line, word above, numeric density of the line.
4.2 **LayoutKIE-CRF**: linear-chain CRF over the reading order (lines, left→right), L-BFGS with L1/L2 (c1 = 0.05, c2 = 0.01), trained with
mixed simulated OCR noise (0/5/10%). Weights exported to the same hashed layout; NumPy Viterbi + forward–backward marginals (agreement
with CRFsuite: 940/940 tokens). L1 sparsity gives a 50 KB model.
4.3 **OCR token normaliser**: splits glued label–value tokens at colons ("PartyGSTIN:19DZ…"), glued currency–amount tokens ("Rs.2153.00"),
CamelCase labels ("TaxInvoiceNo:"), and repairs month tokens ("Ju1" → "Jul").
4.4 **GST-aware value repair**: numeric entities map confusable characters (O→0, l→1, S→5…), normalise decimal separators and drop
currency words; GSTINs fix characters by position and try confusable swaps until the GSTIN checksum validates.
4.5 Deployment: the model is one candidate in a self-consistency-checked ensemble (line items must sum to the subtotal, line taxes to
header taxes, totals to the grand total); it is chosen only when strictly more consistent than the rule extractors.

## 5. Experiments
**Baselines:** regex rules, layout heuristic, rules ensemble (all from the production system, *excluding* the learned model to avoid test
leakage), and an identical **linear (logistic-regression) model** as the no-sequence ablation.

**E8 – Main result (Table A, 3 runs × 80 unseen-layout invoices).** Clean: LayoutKIE-CRF 99.6 ± 0.6% (95% CI 98.9–99.9), fully correct 95.4%;
linear 97.9 ± 1.7%, 78.3%; best rules 44.9 ± 3.2%, 0%. 5% noise: CRF 89.3 ± 2.9% vs linear 86.8 ± 0.8% vs rules 39.4 ± 2.8%.
McNemar on fully-correct invoices: CRF vs linear p < 0.0001 (clean), p = 0.0074 (noise); all rules vs models p < 0.001.
Cost: CRF ~12 ms/invoice, 44 s training (320 docs) on CPU.

**E9 – Real OCR (Table B, Fig. 5; RapidOCR on rendered pages, n = 24 per condition).** Clean scans: CRF 75.8% → **85.2%** with the normaliser
(header 63.2% → 96.7%); best rule + the same normaliser 42.1%. Photo-style images (perspective on a desk, shadow, blur, JPEG): 31.4%;
after the camera-capture pipeline (document detection, perspective correction, enhancement): **84.5%**.

**Supplementary (earlier linear model, single run; Tables 1–6 in RESULTS.md):** E2 layout variety (same 320 docs over 1→16 layouts:
33.7 → 94.4%); E4 data efficiency (32 docs already 96.2%); E3 noise curves; E5 ablation (without left-of-word context 12.6%; column-header
features *hurt* unseen-layout items 97.7 → 99.8% when removed); E6/E7 out-of-distribution generators (30.4% / 77.6%; doubling layout
variety did not help — value-format shift: integer prices, "%"-less rates, several totals per line).

## 6. Discussion
(i) Learned left-context features generalise across structural variation that breaks rules, cheaply on CPU. (ii) Sequence modelling mainly
increases *fully-correct* invoices — what matters for automation. (iii) The sim-to-real gap is dominated by OCR tokenisation, not layout;
a 40-line domain-aware normaliser recovers most of it. (iv) Image normalisation (capture) matters more than model choice for photos.
(v) Structural diversity does not cover value-format diversity; synthesis must randomise number/percent formats and field packing.

## 7. Limitations and threats to validity
Synthetic invoices only (no real invoices yet); real-OCR test is 24 invoices per condition; photo distortions are simulated; supplementary
experiments use one run and the earlier linear model; no LayoutLMv3/Donut comparison yet (script: `ml/layoutlmv3_fatura_colab.py`);
English-only invoices. Before submission: add a real anonymised test set (protocol in `research/data_collection/`), run LayoutLMv3,
increase n for E9, and report all supplementary experiments with ≥3 runs.

## 8. Conclusion
A 50 KB CPU model trained purely on synthetic layouts reads unseen GST invoice layouts almost perfectly on clean text and, with
domain-aware OCR normalisation and capture preprocessing, reaches ~85% field accuracy on real OCR of scans and phone-style photos.

## Ethics and reproducibility
No personal data used. Real-invoice collection requires consent and anonymisation (tools provided). Code, generator and all result files are included.
