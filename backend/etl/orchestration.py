"""Prefect orchestration for the invoice pipeline.

Watches data/inbox/ for new files, and for each one:
  1. creates a ProcessingJob row (status tracking, retries, error capture)
  2. runs the full pipeline via app.services.pipeline_service
  3. moves the source file to data/raw/ (processed) on success
  4. updates the job row with the outcome

This is the ONLY place that manages retries/backoff for the ingestion stage;
app.services.pipeline_service itself is a plain synchronous function so it
can also be called directly (API upload, CLI) without pulling in Prefect.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from prefect import flow, get_run_logger, task
from prefect.task_runners import ThreadPoolTaskRunner
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.base import SessionLocal
from backend.db.models import ProcessingJob
from backend.services.pipeline_service import process_invoice_file

logger = logging.getLogger(__name__)


@task(retries=0)  # retry policy is handled explicitly per-job below (records attempts in the DB)
def discover_inbox_files() -> list[str]:
    settings = get_settings()
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    return [
        str(p) for p in sorted(settings.inbox_dir.iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]


@task
def create_job(path: str) -> str:
    db = SessionLocal()
    try:
        job = ProcessingJob(source_filename=Path(path).name, stage="INGESTED", status="PENDING")
        db.add(job)
        db.commit()
        db.refresh(job)
        return str(job.id)
    finally:
        db.close()


@task
def run_pipeline_for_job(job_id: str, path: str) -> dict:
    """Runs the pipeline for one file with the job's own retry/backoff loop,
    recording every attempt, so a transient failure (e.g. LLM timeout,
    momentary DB contention) doesn't require re-discovering the file.
    """
    run_logger = get_run_logger()
    db: Session = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        job.status = "RUNNING"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        while job.attempts < job.max_attempts:
            job.attempts += 1
            db.commit()
            try:
                invoice = process_invoice_file(db, path)
                job.status = "SUCCEEDED"
                job.stage = "PERSISTED"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                return {"invoice_id": str(invoice.id), "status": invoice.status, "job_id": job_id}
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any stage failure retries here
                run_logger.warning("Attempt %d/%d failed for %s: %s", job.attempts, job.max_attempts, path, exc)
                job.error_message = str(exc)
                db.commit()

        job.status = "FAILED"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"invoice_id": None, "status": "FAILED", "job_id": job_id, "error": job.error_message}
    finally:
        db.close()


@task
def archive_file(path: str, outcome: dict) -> None:
    settings = get_settings()
    src = Path(path)
    if not src.exists():
        return
    dest_dir = settings.raw_dir if outcome.get("status") != "FAILED" else settings.staging_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest_dir / src.name))


@flow(name="process-one-invoice")
def process_one_invoice_flow(path: str) -> dict:
    job_id = create_job(path)
    outcome = run_pipeline_for_job(job_id, path)
    archive_file(path, outcome)
    return outcome


@flow(name="process-inbox", task_runner=ThreadPoolTaskRunner(max_workers=4))
def process_inbox_flow() -> list[dict]:
    """Entry point for a scheduled/triggered batch run: processes every file
    currently sitting in data/inbox/ concurrently (bounded by max_workers)."""
    run_logger = get_run_logger()
    files = discover_inbox_files()
    run_logger.info("Found %d file(s) in inbox.", len(files))
    outcomes = [process_one_invoice_flow(path) for path in files]
    return outcomes


if __name__ == "__main__":
    process_inbox_flow()
