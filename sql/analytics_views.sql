-- Analytics views for reporting/BI on top of the normalized OLTP schema.
-- These are pure read models: nothing here is written to by the app, and
-- none of them are required for the pipeline to function -- they exist to
-- make the Streamlit dashboard (and any external BI tool) fast and simple.

CREATE OR REPLACE VIEW v_invoice_status_summary AS
SELECT
    status,
    COUNT(*) AS invoice_count,
    SUM(grand_total) AS total_value,
    AVG(confidence_score) AS avg_confidence
FROM invoices
GROUP BY status;

CREATE OR REPLACE VIEW v_daily_intake AS
SELECT
    date_trunc('day', created_at) AS intake_day,
    COUNT(*) AS invoices_ingested,
    SUM(CASE WHEN status = 'AUTO_APPROVED' THEN 1 ELSE 0 END) AS auto_approved,
    SUM(CASE WHEN status = 'NEEDS_REVIEW' THEN 1 ELSE 0 END) AS needs_review,
    SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected
FROM invoices
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE VIEW v_gst_liability_by_rate AS
SELECT
    il.gst_rate,
    COUNT(DISTINCT il.invoice_id) AS invoice_count,
    SUM(il.taxable_value) AS total_taxable_value,
    SUM(COALESCE(il.cgst, 0) + COALESCE(il.sgst, 0) + COALESCE(il.igst, 0)) AS total_gst
FROM invoice_lines il
JOIN invoices i ON i.id = il.invoice_id
WHERE i.status IN ('AUTO_APPROVED', 'APPROVED')
GROUP BY il.gst_rate
ORDER BY il.gst_rate;

CREATE OR REPLACE VIEW v_hsn_summary AS
SELECT
    il.hsn_sac,
    COUNT(*) AS line_count,
    SUM(il.taxable_value) AS total_taxable_value,
    AVG(il.gst_rate) AS avg_gst_rate
FROM invoice_lines il
JOIN invoices i ON i.id = il.invoice_id
WHERE i.status IN ('AUTO_APPROVED', 'APPROVED')
GROUP BY il.hsn_sac
ORDER BY total_taxable_value DESC NULLS LAST;

CREATE OR REPLACE VIEW v_vendor_spend AS
SELECT
    v.id AS vendor_id,
    v.name AS vendor_name,
    v.gstin,
    COUNT(i.id) AS invoice_count,
    SUM(i.grand_total) AS total_spend,
    AVG(i.confidence_score) AS avg_confidence,
    SUM(CASE WHEN vf.severity = 'ERROR' THEN 1 ELSE 0 END) AS error_finding_count
FROM vendors v
LEFT JOIN invoices i ON i.vendor_id = v.id
LEFT JOIN validation_findings vf ON vf.invoice_id = i.id
GROUP BY v.id, v.name, v.gstin
ORDER BY total_spend DESC NULLS LAST;

CREATE OR REPLACE VIEW v_finding_frequency AS
SELECT
    code,
    category,
    severity,
    COUNT(*) AS occurrence_count,
    COUNT(DISTINCT invoice_id) AS invoice_count
FROM validation_findings
GROUP BY code, category, severity
ORDER BY occurrence_count DESC;

CREATE OR REPLACE VIEW v_reconciliation_summary AS
SELECT
    status,
    COUNT(*) AS line_count,
    SUM(COALESCE(price_invoiced, 0) * COALESCE(qty_invoiced, 0)) AS total_invoiced_value
FROM reconciliation_results
GROUP BY status;

CREATE OR REPLACE VIEW v_review_queue AS
SELECT
    i.id,
    i.source_filename,
    i.vendor_name_raw,
    i.invoice_number,
    i.invoice_date,
    i.grand_total,
    i.confidence_score,
    i.created_at,
    COUNT(vf.id) FILTER (WHERE vf.severity = 'ERROR') AS error_count,
    COUNT(vf.id) FILTER (WHERE vf.severity = 'WARNING') AS warning_count
FROM invoices i
LEFT JOIN validation_findings vf ON vf.invoice_id = i.id
WHERE i.status = 'NEEDS_REVIEW'
GROUP BY i.id, i.source_filename, i.vendor_name_raw, i.invoice_number,
         i.invoice_date, i.grand_total, i.confidence_score, i.created_at
ORDER BY i.created_at ASC;

CREATE OR REPLACE VIEW v_processing_job_health AS
SELECT
    stage,
    status,
    COUNT(*) AS job_count,
    AVG(EXTRACT(EPOCH FROM (finished_at - started_at))) AS avg_duration_seconds,
    AVG(attempts) AS avg_attempts
FROM processing_jobs
GROUP BY stage, status;
