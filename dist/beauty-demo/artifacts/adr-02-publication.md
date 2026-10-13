# ADR 02 — Preserve a consistent last-valid publication

Store failed batches as Bronze evidence; do not replace valid Gold. Commit both state and product pointer with the tables in one transaction. Hash-identical replays leave the product version unchanged. Separate source/batch validation from product serving.
