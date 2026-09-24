"""Fine-tune LayoutLMv3 for GST invoice field extraction.

    pip install -r requirements-ml.txt
    python -m ml.generate_dataset --n 750
    python -m ml.train_layoutlm --data data/layoutlm_dataset --out models/layoutlmv3-gst
    python -m ml.benchmark --model models/layoutlmv3-gst

Runs on CPU but is slow; a free Colab T4 GPU finishes 3 epochs on 1,500
invoices in roughly 20-30 minutes (see ml/train_layoutlm_colab.ipynb).
Then set LAYOUTLM_MODEL_PATH=models/layoutlmv3-gst and the pipeline uses it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.extraction.labels import ID2LABEL, LABEL2ID, LABELS

BASE_MODEL = "microsoft/layoutlmv3-base"


def load_split(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def build_dataset(rows: list[dict], root: Path, processor):
    import torch
    from PIL import Image

    class InvoiceDataset(torch.utils.data.Dataset):
        def __len__(self):
            return len(rows)

        def __getitem__(self, idx):
            r = rows[idx]
            image = Image.open(root / r["image"]).convert("RGB")
            enc = processor(image, r["words"], boxes=r["bboxes"],
                            word_labels=[LABEL2ID[l] for l in r["labels"]],
                            truncation=True, padding="max_length", max_length=512, return_tensors="pt")
            return {k: v.squeeze(0) for k, v in enc.items()}

    return InvoiceDataset()


def compute_metrics_fn():
    from seqeval.metrics import classification_report, f1_score, precision_score, recall_score

    def compute(p):
        preds = np.argmax(p.predictions, axis=2)
        true_l, pred_l = [], []
        for pr, lab in zip(preds, p.label_ids):
            t, q = [], []
            for pi, li in zip(pr, lab):
                if li == -100:
                    continue
                t.append(ID2LABEL[int(li)])
                q.append(ID2LABEL[int(pi)])
            true_l.append(t)
            pred_l.append(q)
        compute.last_report = classification_report(true_l, pred_l, digits=3)
        return {"precision": precision_score(true_l, pred_l), "recall": recall_score(true_l, pred_l),
                "f1": f1_score(true_l, pred_l)}

    compute.last_report = ""
    return compute


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/layoutlm_dataset")
    ap.add_argument("--out", default="models/layoutlmv3-gst")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=3e-5)
    args = ap.parse_args()

    from transformers import (AutoProcessor, LayoutLMv3ForTokenClassification, Trainer, TrainingArguments,
                              set_seed)

    set_seed(42)
    root = Path(args.data)
    processor = AutoProcessor.from_pretrained(BASE_MODEL, apply_ocr=False)
    model = LayoutLMv3ForTokenClassification.from_pretrained(
        BASE_MODEL, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID)

    train = build_dataset(load_split(root / "train.jsonl"), root, processor)
    val = build_dataset(load_split(root / "val.jsonl"), root, processor)
    metrics = compute_metrics_fn()

    targs = TrainingArguments(
        output_dir=str(Path(args.out) / "checkpoints"), num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, per_device_eval_batch_size=args.batch,
        learning_rate=args.lr, warmup_ratio=0.1, weight_decay=0.01,
        eval_strategy="epoch", save_strategy="epoch", load_best_model_at_end=True,
        metric_for_best_model="f1", save_total_limit=1, logging_steps=25, report_to=[],
        fp16=__import__("torch").cuda.is_available(), dataloader_num_workers=2,
    )
    trainer = Trainer(model=model, args=targs, train_dataset=train, eval_dataset=val, compute_metrics=metrics)
    trainer.train()
    result = trainer.evaluate()

    out = Path(args.out)
    trainer.save_model(str(out))
    processor.save_pretrained(str(out))
    (out / "eval.json").write_text(json.dumps(result, indent=2))
    (out / "classification_report.txt").write_text(metrics.last_report)
    print(json.dumps(result, indent=2))
    print(metrics.last_report)
    print(f"Saved model to {out}. Next: python -m ml.benchmark --model {out}")


if __name__ == "__main__":
    main()
