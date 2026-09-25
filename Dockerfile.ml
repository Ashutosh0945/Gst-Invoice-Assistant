# ML-enabled worker image: adds PaddleOCR + LayoutLMv3 (torch/transformers)
# on top of the base image, for the Prefect worker that actually OCRs
# scanned invoices and/or runs the fine-tuned LayoutLMv3 extractor.
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ml.txt

COPY backend ./backend
COPY sql ./sql
COPY data/hsn ./data/hsn
COPY data/itc ./data/itc
COPY data/tax ./data/tax
COPY ml ./ml
COPY scripts ./scripts

ENV PYTHONPATH=/srv
CMD ["python", "-m", "backend.etl.orchestration"]
