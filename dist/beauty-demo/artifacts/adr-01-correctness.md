# ADR 01 — Correctness before similarity

Keep invoice headers, lines and receipt applications at declared grains. Aggregate receipts before joining. Use integer cents, explicit USD contract and ratios of sums. Reject rather than silently convert currencies or overapply receipts. Test reconciliation and weighted ratios.
