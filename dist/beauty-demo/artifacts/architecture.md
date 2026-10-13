# Implemented architecture and contracts

SAP-shaped synthetic invoices, lines and receipts → hashed Bronze ledger → validated Silver records → quality-gated Gold cashflow/RGM → shared metric registry / parameterized SQL → scoped tools and factual answers. Synthetic documents → paragraph chunks → permission-filtered lexical count vectors → cited context.

Source contract: line_id, invoice_id, market, USD currency and integer cents; units/returns and line monetary values. Invoices are headers; receipts are separately keyed invoice applications dated at/before the demo as-of clock. Input extraction from SAP is not implemented.

Silver validates uniqueness, source references, supported currency, header/line market consistency, nonnegative values, receipt bounds and financial reconciliation. Cashflow aggregates receipts at invoice grain before joining. RGM retains sales-line grain. Actual receipt cash is distinct from net invoiced revenue. No implicit FX conversion is performed.

Metric contract: allowlisted metric name, market scope, USD/% unit, expression, semantic_version, publish_version and fixed as-of date. Margin and discount percentages use ratios of sums. The same registry powers dashboard cards and agent tools.

Publication commits Silver, Gold tables, pointer and workspace revision in one SQLite transaction using an attached state database. SQLite's default rollback journals are retained; do not switch only one database to WAL. A failed batch remains in Bronze while prior products remain active. Replaying an identical batch does not create a new product version.

Retrieval contract: document_id, chunk_id, title, paragraph text and server-controlled ACLs. Missing ACLs deny access; filter before similarity scoring. Four short documents form one paragraph-sized chunk each. Local word-count cosine similarity is a transparent lexical-vector implementation, not a learned embedding model or cloud vector service. The local router/response assembler is deterministic, not an LLM.

Trace timings cover actual tool operations. Pipeline traces cover validation and DML before final transaction commit; they are not production end-to-end latency measurements.
