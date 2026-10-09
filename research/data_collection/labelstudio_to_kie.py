"""Convert a Label Studio JSON export (label_studio_config.xml) to the KIE training format
(words, 0-1000 boxes, BIO labels) used by research/train_kie.py and export_dataset.py.
Each labelled box's text is split into words; the box width is shared proportionally. Unlabelled
text is not included (run OCR over the page and merge if you want 'O' words too).
    python -m research.data_collection.labelstudio_to_kie export.json out_dir"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def convert(task: dict) -> dict:
    regions = {}
    for ann in (task.get("annotations") or [])[:1]:
        for r in ann.get("result", []):
            rg = regions.setdefault(r["id"], {})
            v = r["value"]
            rg.update(x=v.get("x", rg.get("x")), y=v.get("y", rg.get("y")), w=v.get("width", rg.get("w")), h=v.get("height", rg.get("h")))
            if r["type"] == "rectanglelabels":
                rg["label"] = v["rectanglelabels"][0]
            elif r["type"] == "textarea":
                rg["text"] = (v.get("text") or [""])[0]
    words, boxes, labels = [], [], []
    for rg in sorted(regions.values(), key=lambda r: (round(r["y"] or 0), r["x"] or 0)):
        if not rg.get("label") or not rg.get("text"):
            continue
        toks = rg["text"].split()
        total = sum(len(t) for t in toks) or 1
        x = rg["x"]
        for k, t in enumerate(toks):
            wdt = rg["w"] * len(t) / total
            boxes.append([int(10 * x), int(10 * rg["y"]), int(10 * (x + wdt)), int(10 * (rg["y"] + rg["h"]))])
            words.append(t)
            labels.append(("B-" if k == 0 else "I-") + rg["label"])
            x += wdt
    return {"id": str(task.get("id")), "image": Path(str(task.get("data", {}).get("image", ""))).name,
            "width": 1000, "height": 1000, "words": words, "boxes": boxes, "labels": labels, "source": "real"}


def main(export: str, out: str) -> None:
    o = Path(out)
    o.mkdir(parents=True, exist_ok=True)
    tasks = json.loads(Path(export).read_text())
    for t in tasks:
        rec = convert(t)
        (o / f"real_{rec['id']}.json").write_text(json.dumps(rec))
    print(f"converted {len(tasks)} tasks -> {o}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
