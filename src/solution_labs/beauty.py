"""Reconciled domain products, shared SQL metrics and permission-filtered lexical vectors."""

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .common import Store, Trace

AS_OF = date(2026, 10, 12)
DEFINITIONS = {
    "net_revenue": (
        "SUM(net_cents)",
        "Net invoiced sales after returns and discounts",
        "rgm",
        "USD",
    ),
    "margin_pct": (
        "100.0*SUM(profit_cents)/NULLIF(SUM(net_cents),0)",
        "100 × total profit / total net revenue",
        "rgm",
        "%",
    ),
    "discount_pct": (
        "100.0*SUM(discount_cents)/NULLIF(SUM(gross_cents),0)",
        "100 × total discounts / gross sales after returns",
        "rgm",
        "%",
    ),
    "cash_collected": (
        "SUM(paid_cents)",
        "Actual receipts applied to invoices as of the demo clock",
        "cashflow",
        "USD",
    ),
    "receivables": (
        "SUM(outstanding_cents)",
        "Invoice balance minus applied receipts",
        "cashflow",
        "USD",
    ),
    "overdue": (
        "SUM(overdue_cents)",
        "Outstanding balances with due date before the demo clock",
        "cashflow",
        "USD",
    ),
}
SCOPES = {"finance": ["US", "GB", "CA"], "commercial": ["US", "CA"]}
DOCUMENTS: list[dict[str, Any]] = [
    {
        "document_id": "D01",
        "title": "Promotion evaluation",
        "acl": ["commercial", "finance"],
        "text": (
            "Promotion evaluation compares net revenue after returns and discounts "
            "with product cost. Margin is a ratio of aggregate profit to aggregate "
            "revenue. Discount efficiency must be reviewed with returns and net "
            "units."
        ),
    },
    {
        "document_id": "D02",
        "title": "Returns and commercial planning",
        "acl": ["commercial", "finance"],
        "text": (
            "Returns reduce gross eligible sales and product cost at the invoice "
            "line grain. Commercial planning should reconcile return quantities "
            "and avoid double counting. Revenue growth management uses consistent "
            "market filters."
        ),
    },
    {
        "document_id": "D03",
        "title": "Treasury collection policy",
        "acl": ["finance"],
        "text": (
            "Treasury cash collection records actual receipts. Invoiced revenue is "
            "not collected cash. Receivables use invoice balance minus applied "
            "receipts; overdue balances use the agreed as-of clock. Finance-only "
            "treasury reserve code ORCHID-PRIVATE."
        ),
    },
    {
        "document_id": "D04",
        "title": "Metric ownership",
        "acl": ["commercial", "finance"],
        "text": (
            "Business metric definitions are versioned. Publish only reconciled "
            "data products. A failed source batch preserves the last valid version "
            "and its refresh marker. Market and role permissions are checked by "
            "each tool."
        ),
    },
]


def fixtures() -> dict[str, list[dict[str, Any]]]:
    lines, invoices, receipts = [], [], []
    for index in range(60):
        invoice_id, market = f"I{index:03}", ["US", "GB", "CA"][index % 3]
        amount = 0
        for item in range(2):
            units = 4 + index % 13 + item
            returns = 1 if index % 7 == 0 else 0
            price, cost = 1800 + item * 1200 + index * 7, 900 + item * 500
            gross = (units - returns) * price
            discount = gross * (10 if index % 4 == 0 else 5) // 100
            net = gross - discount
            lines.append(
                {
                    "line_id": f"{invoice_id}-{item}",
                    "invoice_id": invoice_id,
                    "market": market,
                    "currency": "USD",
                    "units": units,
                    "returns": returns,
                    "gross_cents": gross,
                    "discount_cents": discount,
                    "net_cents": net,
                    "cost_cents": (units - returns) * cost,
                    "product": ["skincare", "haircare"][item],
                }
            )
            amount += net
        due = AS_OF + timedelta(days=(index % 5 - 2) * 10)
        invoices.append(
            {
                "invoice_id": invoice_id,
                "market": market,
                "currency": "USD",
                "amount_cents": amount,
                "due_date": due.isoformat(),
            }
        )
        fraction = [0, 0.5, 1][index % 3]
        paid = int(amount * fraction)
        if paid:
            receipts.extend(
                [
                    {
                        "receipt_id": f"R{index:03}-{n}",
                        "invoice_id": invoice_id,
                        "amount_cents": paid // 2 if n == 0 else paid - paid // 2,
                        "currency": "USD",
                        "received_date": AS_OF.isoformat(),
                    }
                    for n in range(2)
                ]
            )
    return {"lines": lines, "invoices": invoices, "receipts": receipts}


def validate(data: dict[str, list[dict[str, Any]]]) -> list[str]:
    failures: list[str] = []
    contracts = {
        "lines": (
            ["line_id", "invoice_id", "market", "currency", "product"],
            ["units", "returns", "gross_cents", "discount_cents", "net_cents", "cost_cents"],
        ),
        "invoices": (["invoice_id", "market", "currency", "due_date"], ["amount_cents"]),
        "receipts": (["receipt_id", "invoice_id", "currency", "received_date"], ["amount_cents"]),
    }
    for table, (strings, numbers) in contracts.items():
        for row in data.get(table, []):
            if any(not isinstance(row.get(key), str) or not row[key].strip() for key in strings):
                failures.append(f"Missing/invalid {table} key or text field")
            if any(
                not isinstance(row.get(key), int) or isinstance(row.get(key), bool) or row[key] < 0
                for key in numbers
            ):
                failures.append("Negative/impossible or noninteger monetary/unit value")
            for field in ["due_date", "received_date"]:
                if field in row:
                    try:
                        date.fromisoformat(row[field])
                    except (ValueError, TypeError):
                        failures.append("Missing/invalid source date")
    if any(table not in data for table in contracts) or any(
        not data.get(table) for table in ["lines", "invoices"]
    ):
        failures.append("Missing/empty required source table")
    if failures:
        return sorted(set(failures))
    for table, key in [
        ("lines", "line_id"),
        ("invoices", "invoice_id"),
        ("receipts", "receipt_id"),
    ]:
        ids = [r[key] for r in data[table]]
        if len(ids) != len(set(ids)):
            failures.append(f"Duplicate {table} key")
        if any(r.get("currency") != "USD" for r in data[table]):
            failures.append("Currency contract requires USD; no implicit FX conversion")
        if table != "receipts" and any(
            r.get("market") not in SCOPES["finance"] for r in data[table]
        ):
            failures.append("Unknown market contract")
    headers = {r["invoice_id"]: r for r in data["invoices"]}
    amounts: Counter[str] = Counter()
    paid: Counter[str] = Counter()
    for row in data["lines"]:
        if row["invoice_id"] not in headers:
            failures.append("Orphan invoice line")
        elif row["market"] != headers[row["invoice_id"]]["market"]:
            failures.append("Header/line market mismatch")
        if (
            row["units"] < row["returns"]
            or min(
                row["net_cents"],
                row["cost_cents"],
                row["discount_cents"],
                row["gross_cents"],
                row["units"],
                row["returns"],
            )
            < 0
        ):
            failures.append("Negative/impossible commercial value")
        if row["net_cents"] != row["gross_cents"] - row["discount_cents"]:
            failures.append("Line net reconciliation failed")
        amounts[row["invoice_id"]] += row["net_cents"]
    for row in data["receipts"]:
        if row["invoice_id"] not in headers or row["amount_cents"] < 0:
            failures.append("Orphan/invalid receipt")
        if date.fromisoformat(row["received_date"]) > AS_OF:
            failures.append("Future receipt")
        paid[row["invoice_id"]] += row["amount_cents"]
    for key, header in headers.items():
        if amounts[key] != header["amount_cents"]:
            failures.append("Invoice/line reconciliation failed")
        if paid[key] > header["amount_cents"]:
            failures.append("Receipt application exceeds invoice amount")
    return sorted(set(failures))


def retrieve(question: str, role: str) -> list[dict[str, Any]]:
    def tokens(text: str) -> Counter[str]:
        return Counter(re.findall(r"[a-z]{3,}", text.lower()))

    query = tokens(question)
    results = []
    # Authorization precedes scoring and is not supplied by the user question.
    for doc in DOCUMENTS:
        if role not in doc.get("acl", []):
            continue
        vector = tokens(doc["text"])
        denominator = math.sqrt(
            sum(v * v for v in query.values()) * sum(v * v for v in vector.values())
        )
        score = (
            sum(value * vector[word] for word, value in query.items()) / denominator
            if denominator
            else 0
        )
        if score > 0:
            results.append(
                {
                    "document_id": doc["document_id"],
                    "chunk_id": doc["document_id"] + "-01",
                    "title": doc["title"],
                    "text": doc["text"],
                    "similarity": round(score, 4),
                }
            )
    return sorted(results, key=lambda doc: (-doc["similarity"], doc["document_id"]))[:3]


def unsupported(question: str) -> bool:
    return bool(
        re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|"
            r"november|december|quarter|monthly|yearly|daily|weekly|last|next|past|previous|"
            r"yesterday|tomorrow|gross|dollars|euros?|eur|gbp|pounds?|cad|yen|by|per|each|"
            r"breakdown|compare|trend|growth|not|without|instead|select|drop|delete|insert|"
            r"update|union|month|year)\b|20\d{2}",
            question,
            re.I,
        )
    )


def route(question: str) -> str | None:
    if unsupported(question):
        return None
    if re.search(
        r"\b(gross|dollars|next|previous|past|month|year|daily|weekly|quarter)\b", question, re.I
    ):
        return None
    if re.search(r"\b(select|drop|delete|insert|update|union)\b", question, re.I):
        return None
    if re.search(
        r"\b(not|without|instead|last|yesterday|tomorrow|compare|trend|growth)\b|20\d{2}",
        question,
        re.I,
    ):
        return None
    aliases = {
        "net_revenue": ["net revenue", "revenue"],
        "margin_pct": ["margin"],
        "discount_pct": ["discount rate", "discount percentage"],
        "cash_collected": ["cash collected", "cashflow", "cash flow"],
        "receivables": ["receivables", "outstanding"],
        "overdue": ["overdue"],
    }
    lowered = question.lower()
    found = {key for key, words in aliases.items() if any(word in lowered for word in words)}
    if "overdue" in found:
        found.discard("receivables")
    return next(iter(found)) if len(found) == 1 else None


class Beauty:
    def __init__(self, root: Path):
        self.store = Store(root)

    def create(self, role: str, scenario: str) -> dict[str, Any]:
        data = {
            "scenario": scenario,
            "publish_version": 0,
            "source_hash": "",
            "quality": [],
            "bronze_batches": 0,
        }
        key, _ = self.store.create("beauty", role, data)
        self.pipeline(key, role, "clean")
        if scenario != "clean":
            return self.pipeline(key, role, scenario)
        return self.snapshot(key, role)

    def connection(self, key: str) -> sqlite3.Connection:
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("Invalid workspace ID")
        connection = sqlite3.connect(self.store.root / "runtime" / f"beauty-{key}.sqlite")
        connection.row_factory = sqlite3.Row
        return connection

    def pipeline(self, key: str, role: str, scenario: str) -> dict[str, Any]:
        state, revision = self.store.load(key, "beauty", role)
        trace = Trace()
        with trace.stage("bronze", "Receive SAP-shaped synthetic batch"):
            raw = fixtures()
            if scenario == "bad_batch":
                raw["invoices"][0]["amount_cents"] += 100
            elif scenario == "duplicate":
                raw["lines"].append(dict(raw["lines"][0]))
            elif scenario == "currency":
                raw["invoices"][0]["currency"] = "EUR"
            digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        with trace.stage("quality", "Validate keys, currency and ledger reconciliation"):
            failures = validate(raw)
        state["quality"], state["scenario"] = failures, scenario
        connection = self.connection(key)
        try:
            connection.execute("ATTACH DATABASE ? AS state", (str(self.store.path),))
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS bronze (batch_hash TEXT PRIMARY KEY,payload TEXT)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO bronze VALUES (?,?)", (digest, json.dumps(raw))
                )
                state["bronze_batches"] = connection.execute(
                    "SELECT COUNT(*) FROM bronze"
                ).fetchone()[0]
                if not failures and digest != state["source_hash"]:
                    with trace.stage(
                        "gold", "Publish reconciled Silver and Gold snapshot atomically"
                    ):
                        connection.execute(
                            "CREATE TABLE IF NOT EXISTS rgm (line_id TEXT PRIMARY KEY,market "
                            "TEXT,product TEXT,gross_cents INTEGER,discount_cents "
                            "INTEGER,net_cents INTEGER,profit_cents INTEGER)"
                        )
                        connection.execute(
                            "CREATE TABLE IF NOT EXISTS cashflow (invoice_id TEXT PRIMARY "
                            "KEY,market TEXT,amount_cents INTEGER,paid_cents "
                            "INTEGER,outstanding_cents INTEGER,overdue_cents INTEGER)"
                        )
                        connection.execute(
                            "CREATE TABLE IF NOT EXISTS silver (kind TEXT,business_key "
                            "TEXT,payload TEXT,PRIMARY KEY(kind,business_key))"
                        )
                        connection.execute("DELETE FROM silver")
                        connection.execute("DELETE FROM rgm")
                        connection.execute("DELETE FROM cashflow")
                        for table, id_key in [
                            ("lines", "line_id"),
                            ("invoices", "invoice_id"),
                            ("receipts", "receipt_id"),
                        ]:
                            connection.executemany(
                                "INSERT INTO silver VALUES (?,?,?)",
                                [(table, r[id_key], json.dumps(r)) for r in raw[table]],
                            )
                        connection.executemany(
                            "INSERT INTO rgm VALUES (?,?,?,?,?,?,?)",
                            [
                                (
                                    r["line_id"],
                                    r["market"],
                                    r["product"],
                                    r["gross_cents"],
                                    r["discount_cents"],
                                    r["net_cents"],
                                    r["net_cents"] - r["cost_cents"],
                                )
                                for r in raw["lines"]
                            ],
                        )
                        receipts: Counter[str] = Counter()
                        for receipt in raw["receipts"]:
                            receipts[receipt["invoice_id"]] += receipt["amount_cents"]
                        connection.executemany(
                            "INSERT INTO cashflow VALUES (?,?,?,?,?,?)",
                            [
                                (
                                    r["invoice_id"],
                                    r["market"],
                                    r["amount_cents"],
                                    receipts[r["invoice_id"]],
                                    r["amount_cents"] - receipts[r["invoice_id"]],
                                    r["amount_cents"] - receipts[r["invoice_id"]]
                                    if date.fromisoformat(r["due_date"]) < AS_OF
                                    else 0,
                                )
                                for r in raw["invoices"]
                            ],
                        )
                        state["source_hash"], state["publish_version"] = (
                            digest,
                            state["publish_version"] + 1,
                        )
                        connection.execute(
                            "CREATE TABLE IF NOT EXISTS publication (id INTEGER PRIMARY KEY "
                            "CHECK(id=1),version INTEGER,source_hash TEXT)"
                        )
                        connection.execute(
                            "INSERT OR REPLACE INTO publication VALUES (1,?,?)",
                            (state["publish_version"], digest),
                        )
                state["trace"] = trace.result()
                result = connection.execute(
                    "UPDATE state.runs SET payload=?,revision=revision+1 WHERE id=? AND revision=?",
                    (json.dumps(state), key, revision),
                )
                if result.rowcount != 1:
                    from .common import ConflictError

                    raise ConflictError("Pipeline workspace changed; reload and retry")
        finally:
            connection.close()
        return self.snapshot(key, role)

    @contextmanager
    def read(self, key: str, role: str) -> Iterator[tuple[sqlite3.Connection, dict[str, Any], int]]:
        self.store.load(key, "beauty", role)
        connection = self.connection(key)
        try:
            connection.execute("ATTACH DATABASE ? AS state", (str(self.store.path),))
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT payload,revision FROM state.runs WHERE id=? AND kind='beauty' AND owner=?",
                (key, role),
            ).fetchone()
            if row is None:
                raise LookupError("Workspace not found")
            yield connection, json.loads(row["payload"]), int(row["revision"])
        finally:
            connection.close()

    def metric(self, key: str, role: str, metric: str, market: str = "all") -> dict[str, Any]:
        with self.read(key, role) as (connection, _, _revision):
            return self.query_metric(connection, role, metric, market)

    def query_metric(
        self, connection: sqlite3.Connection, role: str, metric: str, market: str = "all"
    ) -> dict[str, Any]:
        if metric not in DEFINITIONS:
            raise ValueError("Metric is not allowlisted")
        expression, definition, table, unit = DEFINITIONS[metric]
        if table == "cashflow" and role != "finance":
            raise PermissionError("Finance metric requires the finance demo identity")
        markets = SCOPES[role] if market == "all" else [market]
        if any(item not in SCOPES[role] for item in markets):
            raise PermissionError("Market is outside this identity's scope")
        placeholders = ",".join("?" for _ in markets)
        sql = (
            f"SELECT {expression} AS value,COUNT(*) AS rows FROM {table} "  # noqa: S608
            f"WHERE market IN ({placeholders})"
        )
        row = connection.execute(sql, markets).fetchone()
        version = connection.execute("SELECT version FROM publication WHERE id=1").fetchone()[0]
        value = row["value"] / 100 if unit == "USD" and row["value"] is not None else row["value"]
        return {
            "metric": metric,
            "value": round(value, 4) if value is not None else None,
            "unit": unit,
            "definition": definition,
            "markets": markets,
            "rows": row["rows"],
            "publish_version": version,
            "semantic_version": "metrics-1.0",
            "sql": sql,
            "parameters": markets,
            "currency": "USD",
            "as_of": AS_OF.isoformat(),
        }

    def snapshot(self, key: str, role: str) -> dict[str, Any]:
        with self.read(key, role) as (connection, state, revision):
            metrics = [
                self.query_metric(connection, role, name)
                for name in DEFINITIONS
                if role == "finance" or DEFINITIONS[name][2] != "cashflow"
            ]
        return state | {
            "run_id": key,
            "revision": revision,
            "role": role,
            "markets": SCOPES[role],
            "metrics": metrics,
            "synthetic": True,
            "as_of": AS_OF.isoformat(),
            "counts": {"invoice_lines": 120, "invoices": 60, "documents": len(DOCUMENTS)},
            "retrieval_mode": (
                "Local lexical count vectors; cloud semantic embeddings are a reference"
            ),
        }

    def ask(
        self, key: str, role: str, question: str, metric: str | None, market: str
    ) -> dict[str, Any]:
        self.store.load(key, "beauty", role)
        trace = Trace()
        clarify = False
        with trace.stage("tools", "Authorize identity and resolve allowlisted tool"):
            if market != "all" and market not in SCOPES[role]:
                raise PermissionError("Market is outside this identity's scope")
            if role != "finance" and re.search(
                r"cash|treasury|receivable|overdue|bank", question, re.I
            ):
                raise PermissionError("Finance question requires the finance demo identity")
            name = metric or route(question)
            clarify = bool(
                unsupported(question)
                or (
                    name is None
                    and (
                        re.search(r"revenue|margin|discount|receivable|cash", question, re.I)
                        or not re.search(
                            r"policy|explain|promotion|return|definition", question, re.I
                        )
                    )
                )
            )
        if clarify:
            return {
                "clarification": (
                    "Choose one supported aggregate metric and market. "
                    "Time/grouping/currency conversions are not implemented; "
                    "results use USD/% at the displayed as-of date."
                ),
                "evidence": None,
                "citations": [],
                "trace": trace.result(),
            }
        with trace.stage("metrics", "Calculate a governed metric using parameterized SQL"):
            evidence = self.metric(key, role, name, market) if name else None
        with trace.stage("index", "Filter document permissions before lexical-vector scoring"):
            citations = retrieve(question, role)
        with trace.stage("agent", "Render a factual answer from authorized evidence"):
            if evidence:
                answer = (
                    f"{evidence['metric'].replace('_', ' ')}: "
                    f"{evidence['value']} {evidence['unit']} across "
                    f"{', '.join(evidence['markets'])}. {evidence['definition']}. "
                    f"Published version {evidence['publish_version']}."
                )
            elif citations:
                answer = citations[0]["text"]
            else:
                answer = "No authorized document matches. Rephrase the question."
        return {
            "answer": answer,
            "evidence": evidence,
            "citations": citations,
            "trace": trace.result(),
            "mode": "Deterministic tool router and factual templates; no local LLM",
        }
