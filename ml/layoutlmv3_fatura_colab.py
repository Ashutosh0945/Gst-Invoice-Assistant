"""LayoutLMv3 baseline on GSTInvoice-Synth (+ optional FATURA pre-training). RUN ON COLAB/KAGGLE (GPU, internet).
NOT run in the development environment (no access to Hugging Face/Zenodo there) — results must be produced by you.

    !pip install -q "transformers>=4.40" datasets seqeval accelerate pymupdf
    !python -m research.export_dataset --out gstinvoice-synth --docs-per-layout 40 --images
    !python ml/layoutlmv3_fatura_colab.py --data gstinvoice-synth --out models/layoutlmv3-gst
Optional FATURA (CC-BY-NC-4.0, 10k invoices, 50 layouts): https://zenodo.org/record/8261508 — download and write a converter
to the same JSON format (words, 0-1000 boxes, labels) for its annotation files, then pass --pretrain fatura_json_dir.
Then compare with GST-LayoutKIE using research/run_experiments.score on the test_unseen split.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.extraction.labels import ID2LABEL, LABEL2ID, LABELS


def load(split_dir: Path):
    return [json.loads(p.read_text()) for p in sorted(split_dir.glob("*.json"))]


def to_dataset(recs, root: Path, processor):
    import torch
    from PIL import Image

    class DS(torch.utils.data.Dataset):
        def __len__(self):
            return len(recs)

        def __getitem__(self, i):
            r = recs[i]
            img = Image.open(root / r["image"]).convert("RGB")
            enc = processor(img, r["words"], boxes=r["boxes"], word_labels=[LABEL2ID.get(l, 0) for l in r["labels"]],
                            truncation=True, padding="max_length", max_length=512, return_tensors="pt")
            return {k: v.squeeze(0) for k, v in enc.items()}
    return DS()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="gstinvoice-synth")
    ap.add_argument("--out", default="models/layoutlmv3-gst")
    ap.add_argument("--pretrain", default=None, help="optional dir of FATURA records converted to the same JSON format")
    ap.add_argument("--epochs", type=float, default=4)
    a = ap.parse_args()
    from transformers import AutoProcessor, LayoutLMv3ForTokenClassification, Trainer, TrainingArguments

    processor = AutoProcessor.from_pretrained("microsoft/layoutlmv3-base", apply_ocr=False)
    model = LayoutLMv3ForTokenClassification.from_pretrained("microsoft/layoutlmv3-base", num_labels=len(LABELS),
                                                             id2label=ID2LABEL, label2id=LABEL2ID)
    root = Path(a.data)
    stages = ([("pretrain", Path(a.pretrain))] if a.pretrain else []) + [("gst", root / "train")]
    for name, d in stages:
        ds = to_dataset(load(d), d, processor)
        args = TrainingArguments(output_dir=f"{a.out}/{name}", num_train_epochs=a.epochs, per_device_train_batch_size=4,
                                 learning_rate=3e-5, warmup_ratio=0.1, save_strategy="no", report_to=[], fp16=True, logging_steps=50)
        Trainer(model=model, args=args, train_dataset=ds).train()
    model.save_pretrained(a.out)
    processor.save_pretrained(a.out)
    print("Saved. Evaluate on", root / "test_unseen", "with backend.extraction.layoutlm + research.run_experiments.score")


if __name__ == "__main__":
    main()
