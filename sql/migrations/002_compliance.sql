-- Upgrade an existing (v0.1) PostgreSQL database to v0.2.
-- New databases don't need this: scripts/init_db.py creates everything.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS irn VARCHAR(64);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_status VARCHAR(24);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS einvoice_data JSONB;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gstr2b_status VARCHAR(24);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS gstr2b_record_id UUID;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_date DATE;
CREATE INDEX IF NOT EXISTS ix_invoices_irn ON invoices (irn);
CREATE INDEX IF NOT EXISTS ix_invoices_einvoice_status ON invoices (einvoice_status);
CREATE INDEX IF NOT EXISTS ix_invoices_gstr2b_status ON invoices (gstr2b_status);
-- The three new tables (gstr2b_imports, gstr2b_records, itc_assessments) are created by:
--   python scripts/init_db.py
-- Then assess credit for existing invoices:  curl -X POST http://localhost:8000/api/v1/itc/reassess
