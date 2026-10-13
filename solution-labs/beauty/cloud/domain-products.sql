-- Reference Delta transformations after a successful quality gate.
-- Do not promote these views if source key/grain/currency/reconciliation checks fail.
CREATE OR REPLACE VIEW YOUR_CATALOG.YOUR_SCHEMA.staged_rgm AS
SELECT line_id, market, product, gross_cents, discount_cents, net_cents,
       net_cents - cost_cents AS profit_cents
FROM YOUR_CATALOG.YOUR_SCHEMA.silver_lines;
CREATE OR REPLACE VIEW YOUR_CATALOG.YOUR_SCHEMA.staged_cashflow AS
WITH receipt_totals AS (
 SELECT invoice_id, SUM(amount_cents) AS paid_cents
 FROM YOUR_CATALOG.YOUR_SCHEMA.silver_receipts
 WHERE received_date <= DATE '2026-10-12' GROUP BY invoice_id
)
SELECT i.invoice_id, i.market, i.amount_cents, COALESCE(r.paid_cents,0) AS paid_cents,
       i.amount_cents-COALESCE(r.paid_cents,0) AS outstanding_cents,
       CASE WHEN i.due_date < DATE '2026-10-12'
            THEN i.amount_cents-COALESCE(r.paid_cents,0) ELSE 0 END AS overdue_cents
FROM YOUR_CATALOG.YOUR_SCHEMA.silver_invoices i
LEFT JOIN receipt_totals r ON i.invoice_id=r.invoice_id;
-- Multi-table Delta promotion is NOT a SQLite transaction. Materialize versioned
-- outputs, validate both, then publish a shared manifest/pointer consumed by views.
-- Learned document embeddings/index sync and model serving are separate contracts.
