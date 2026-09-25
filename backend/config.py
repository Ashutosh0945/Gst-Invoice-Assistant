"""Central configuration. Every threshold that affects a financial decision lives here."""
from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- infrastructure ---
    database_url: str = "postgresql+psycopg2://gst:gst@localhost:5432/gst"
    data_dir: Path = Path("data")
    api_key: str | None = None
    api_url: str = "http://localhost:8000"
    # True on Vercel (or any serverless host): use NullPool instead of
    # SQLAlchemy's own connection pool, since PgBouncer (e.g. Supabase's
    # pooled connection string) already pools in front of Postgres, and a
    # serverless function's process doesn't live long enough for its own
    # pool to pay off. Auto-detects Vercel's VERCEL=1 env var; override
    # explicitly with SERVERLESS_DB=true on other serverless hosts.
    serverless_db: bool = bool(os.environ.get("VERCEL"))

    # --- buyer identity (your company) ---
    our_gstin: str | None = None

    # --- ingestion / OCR ---
    render_dpi: int = 200
    native_text_min_words: int = 25      # >= this many embedded words => treat page as digital
    ocr_lang: str = "en"
    ocr_use_gpu: bool = False
    layoutlm_model_path: str | None = None

    # --- deterministic validation tolerances (INR) ---
    line_tolerance: Decimal = Decimal("0.05")     # absolute, per-line arithmetic
    line_tolerance_rel: Decimal = Decimal("0.001")  # or 0.1% of the line value, whichever is larger
    amount_tolerance: Decimal = Decimal("1.00")   # invoice-level totals / round-off
    po_price_tolerance_pct: Decimal = Decimal("2.0")
    po_qty_epsilon: Decimal = Decimal("0.0005")
    duplicate_date_window_days: int = 3
    duplicate_similarity: float = 0.80

    # --- decision policy ---
    # When true, an invoice without a PO number is a WARNING (lowers confidence).
    # Many businesses buy services without POs, so the default treats it as INFO.
    po_required: bool = False
    auto_approve_threshold: float = 0.90
    hsn_reference_path: Path | None = None       # CSV: code,description[,gst_rate]; default = bundled seed

    # --- e-invoice QR verification ---
    # PEM public key(s) published by the e-invoice portal (NIC/IRP), used to verify
    # the RS256 signature on the signed QR code. Comma-separated list of paths.
    # Empty => QR contents are still decoded and compared, but marked UNVERIFIED.
    einvoice_public_key_paths: str = ""
    einvoice_amount_tolerance: Decimal = Decimal("1.00")

    # --- GSTR-2B reconciliation ---
    gstr2b_amount_tolerance: Decimal = Decimal("1.00")     # INR, per invoice (taxable + tax)
    gstr2b_fuzzy_threshold: float = 0.80                    # invoice-number similarity for a fuzzy match (amounts must agree)
    gstr2b_lookback_days: int = 180                         # how far back a late-filed invoice may be matched

    # --- ITC eligibility ---
    itc_payment_days: int = 180                             # Rule 37: pay the vendor within 180 days
    itc_blocked_credits_path: Path | None = None            # default = data/itc/blocked_credits.csv
    # SAC/HSN prefixes that are YOUR OWN line of business. Section 17(5) lets you
    # claim some otherwise-blocked credits (e.g. passenger transport, rent-a-cab,
    # food) when you supply the same category onward. Comma-separated, e.g. "9964,9966".
    itc_same_line_prefixes: str = ""

    # --- personal app ---
    console_enabled: bool = True                       # business console API (staff login or API_KEY required)
    cors_origins: str = ""                             # comma-separated; empty = same-origin only
    session_secret: str = "change-me-in-production"   # signs login sessions (set a long random value!)
    session_days: int = 30
    cookie_secure: bool = False                        # true when served over HTTPS
    assistant_model: str = "openai/gpt-4o-mini"        # any OpenRouter model that supports tool calling
    tax_rules_path: Path | None = None                 # default: data/tax/rules_india.json

    # --- LLM explanation layer (optional) ---
    openrouter_api_key: str | None = Field(default=None)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    llm_enabled: bool = True
    llm_timeout_s: float = 45.0
    llm_max_retries: int = 3

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def einvoice_key_paths(self) -> list[Path]:
        return [Path(p.strip()) for p in self.einvoice_public_key_paths.split(",") if p.strip()]

    @property
    def same_line_prefixes(self) -> list[str]:
        return [p.strip() for p in self.itc_same_line_prefixes.split(",") if p.strip()]

    @property
    def llm_active(self) -> bool:
        return bool(self.llm_enabled and self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
