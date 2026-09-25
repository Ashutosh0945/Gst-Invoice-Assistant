# API image for Render (or any Docker host). Does NOT include the heavy OCR/ML
# stack -- see Dockerfile.ml for photo/scan support.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY sql ./sql
COPY data/hsn ./data/hsn
COPY data/itc ./data/itc
COPY data/tax ./data/tax
COPY data/benchmarks ./data/benchmarks
COPY scripts ./scripts

ENV PYTHONPATH=/srv PYTHONUNBUFFERED=1
EXPOSE 8000

# Render (and most hosts) tell the app which port to use via $PORT.
# Tables are created on every start; this is safe to repeat (existing tables are left alone).
CMD ["sh", "-c", "python scripts/init_db.py && uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
