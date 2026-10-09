# Research: GST-LayoutKIE + GSTInvoice-Synth

| File | What it is |
|---|---|
| `gst_synth.py` | Multi-layout GST invoice generator (48 layouts) with word-level BIO labels |
| `noise.py` | OCR-noise simulation (character confusions, splits/merges, jitter, skew) |
| `train_kie.py` | Trains the linear model (ablation) and exports NumPy weights |
| `rigor.py` | **E8 main result**: 3 runs, CRF vs linear vs rules, bootstrap CIs, McNemar tests; trains/exports **LayoutKIE-CRF** |
| `real_ocr.py` | **E9**: real OCR (RapidOCR) on scans, photo-style images and photos after camera optimisation |
| `../backend/extraction/learned.py` | The model at inference time (pure NumPy) + GST-rule value repair |
| `run_experiments.py` | E1 main comparison · E2 layouts · E3 noise · E4 data efficiency · E5 ablation · E6/E7 out-of-distribution · final model |
| `make_report.py` → `RESULTS.md`, `figures/` | Tables and figures from `results/*.json` |
| `PAPER_DRAFT.md` | Paper draft with the measured numbers and limitations |
| `export_dataset.py` | Exports GSTInvoice-Synth (JSON + optional PNG) for release or LayoutLMv3 |
| `data_collection/` | Consent form, collection protocol, anonymiser, Label Studio config + converter |
| `../ml/layoutlmv3_fatura_colab.py` | LayoutLMv3 (+ optional FATURA) baseline — run on Colab/Kaggle |

Install research extras: `pip install -r research/requirements.txt` (not needed by the app; the app only uses the exported 50 KB NumPy model).
