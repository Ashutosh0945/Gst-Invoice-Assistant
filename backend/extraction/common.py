"""Shared parsing helpers + reading-order reconstruction."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from backend.schemas import OCRWord, PageData

_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def parse_decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    t = re.sub(r"(?i)(rs\.?|inr|₹|/-|%)", "", str(text)).replace(",", "").replace(" ", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        return None
    try:
        v = Decimal(m.group(0))
    except InvalidOperation:
        return None
    return -v if neg else v


DATE_PAT = (r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[ \-][A-Za-z]{3,9}[ \-,]*\d{2,4}")
_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%Y-%m-%d",
            "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%d-%B-%Y", "%d %b, %Y", "%d %B, %Y", "%d %b %y", "%d-%b-%y"]


def parse_date(text: str | None) -> date | None:
    """Day-first (Indian convention)."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text.strip().rstrip(".,"))
    for f in _FORMATS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            continue
    return None


@dataclass
class Line:
    page: int
    words: list[OCRWord]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def y(self) -> float:
        return sum((w.bbox[1] + w.bbox[3]) / 2 for w in self.words) / len(self.words)

    @property
    def height(self) -> float:
        return statistics.median(w.bbox[3] - w.bbox[1] for w in self.words)

    @property
    def conf(self) -> float:
        return sum(w.conf for w in self.words) / len(self.words)


def words_to_lines(pages: list[PageData]) -> list[Line]:
    """Cluster words into visual lines (per page), each sorted left-to-right."""
    lines: list[Line] = []
    for p in pages:
        ws = [w for w in p.words if w.text.strip()]
        if not ws:
            continue
        h = statistics.median(w.bbox[3] - w.bbox[1] for w in ws)
        ws.sort(key=lambda w: (w.bbox[1] + w.bbox[3]) / 2)
        cur: list[OCRWord] = []
        cur_y = 0.0
        for w in ws:
            yc = (w.bbox[1] + w.bbox[3]) / 2
            if cur and abs(yc - cur_y) > 0.6 * h:
                lines.append(Line(p.page, sorted(cur, key=lambda x: x.bbox[0])))
                cur = []
            cur.append(w)
            cur_y = sum((x.bbox[1] + x.bbox[3]) / 2 for x in cur) / len(cur)
        if cur:
            lines.append(Line(p.page, sorted(cur, key=lambda x: x.bbox[0])))
    return lines
