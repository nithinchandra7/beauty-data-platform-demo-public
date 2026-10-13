-- Reference scaffolds; validated against official syntax, not a live workspace.
-- YAML 1.1 requires a supporting Databricks runtime/SQL warehouse.
-- These source tables must already be quality-gated, scoped and published.
CREATE OR REPLACE VIEW YOUR_CATALOG.YOUR_SCHEMA.rgm_metrics
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
source: YOUR_CATALOG.YOUR_SCHEMA.gold_rgm
dimensions:
  - name: market
    expr: market
measures:
  - name: net_revenue
    expr: SUM(net_cents) / 100.0
  - name: margin_pct
    expr: 100.0 * SUM(profit_cents) / NULLIF(SUM(net_cents), 0)
  - name: discount_pct
    expr: 100.0 * SUM(discount_cents) / NULLIF(SUM(gross_cents), 0)
$$;
CREATE OR REPLACE VIEW YOUR_CATALOG.YOUR_SCHEMA.cashflow_metrics
WITH METRICS LANGUAGE YAML AS $$
version: 1.1
source: YOUR_CATALOG.YOUR_SCHEMA.gold_cashflow
dimensions:
  - name: market
    expr: market
measures:
  - name: cash_collected
    expr: SUM(paid_cents) / 100.0
  - name: receivables
    expr: SUM(outstanding_cents) / 100.0
  - name: overdue
    expr: SUM(overdue_cents) / 100.0
$$;
-- Reference query; grants/row filters must derive allowed markets from identity.
SELECT market, MEASURE(net_revenue), MEASURE(margin_pct)
FROM YOUR_CATALOG.YOUR_SCHEMA.rgm_metrics
WHERE market IN ('US', 'CA') GROUP BY market;
