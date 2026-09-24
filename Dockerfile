# Core image: API + rule engine + ETL. Does NOT include the heavy
# ML stack (paddleocr/torch/transformers) -- see Dockerfile.ml for that image.
# This image alone can already ingest born-digital PDFs, validate, reconcile,
# score, and serve the API.
FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY sql ./sql
COPY data/hsn ./data/hsn
COPY data/itc ./data/itc
COPY data/benchmarks ./data/benchmarks
COPY scripts ./scripts
COPY ml ./ml

ENV PYTHONPATH=/srv
EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
