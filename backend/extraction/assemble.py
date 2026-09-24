"""Turn labelled entities (from LayoutLMv3) into an InvoiceData. Pure and unit-testable."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from backend.extraction.common import parse_date, parse_decimal
from backend.extraction.labels import HEADER_ATTR, ITEM_ATTR
from backend.schemas import InvoiceData, LineItem
from backend.validation.gst import state_code_from_text

DECIMAL_ATTRS = {"quantity", "unit_price", "discount", "taxable_value", "gst_rate", "cgst", "sgst", "igst",
                 "line_total", "subtotal", "total_cgst", "total_sgst", "total_igst", "round_off", "grand_total"}


@dataclass
class Entity:
    etype: str
    text: str
    conf: float
    page: int
    y: float       # y of the entity's first word (page pixels)
    h: float       # median word height


def group_entities(word_preds: list[tuple[str, str, float, int, float, float]]) -> list[Entity]:
    """word_preds: (word, BIO-label, conf, page, y, h) in reading order.

    'Open entity per type' grouping: I-X continues the most recent open X even if other-typed words sit in
    between (row-major reading order interleaves table columns). B-X always opens a new entity.
    """
    done: list[Entity] = []
    open_: dict[str, Entity] = {}
    counts: dict[str, int] = {}
    for word, label, conf, page, y, h in word_preds:
        if label == "O":
            continue
        prefix, etype = label.split("-", 1)
        cur = open_.get(etype)
        if prefix == "I" and cur is not None and cur.page == page:
            cur.text += " " + word
            counts[etype] += 1
            cur.conf += (conf - cur.conf) / counts[etype]
        else:
            ent = Entity(etype, word, conf, page, y, h)
            open_[etype] = ent
            counts[etype] = 1
            done.append(ent)
    return done


def assemble_invoice(entities: list[Entity]) -> InvoiceData:
    inv = InvoiceData()
    best: dict[str, Entity] = {}
    for e in entities:
        if e.etype in HEADER_ATTR and (e.etype not in best or e.conf > best[e.etype].conf):
            best[e.etype] = e
    for etype, e in best.items():
        attr = HEADER_ATTR[etype]
        if attr in DECIMAL_ATTRS:
            val = parse_decimal(e.text)
        elif attr == "invoice_date":
            val = parse_date(e.text)
        elif attr == "place_of_supply":
            val = state_code_from_text(e.text)
        elif attr in ("vendor_gstin", "buyer_gstin"):
            val = re.sub(r"[^A-Z0-9]", "", e.text.upper())
        else:
            val = e.text.strip()
        if val is not None:
            setattr(inv, attr, val)
            inv.field_confidence[attr] = round(e.conf, 4)

    items = sorted((e for e in entities if e.etype in ITEM_ATTR), key=lambda e: (e.page, e.y))
    if items:
        hgt = statistics.median(e.h for e in items) or 1.0
        rows: list[dict[str, Entity]] = []
        last_key = None
        for e in items:
            key = (e.page, e.y)
            if not rows or e.etype in rows[-1] or (last_key and (e.page != last_key[0] or e.y - last_key[1] > 0.6 * hgt)):
                rows.append({})
                last_key = key
            rows[-1][e.etype] = e
        for n, row in enumerate(rows, start=1):
            li = LineItem(line_no=n)
            for etype, e in row.items():
                attr = ITEM_ATTR[etype]
                if attr in DECIMAL_ATTRS:
                    setattr(li, attr, parse_decimal(e.text))
                elif attr == "hsn_sac":
                    li.hsn_sac = re.sub(r"\D", "", e.text) or None
                else:
                    setattr(li, attr, e.text.strip())
            li.confidence = round(sum(e.conf for e in row.values()) / len(row), 4)
            inv.items.append(li)
    return inv
