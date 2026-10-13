"""Executed independent synthetic evaluation; never measures client outcomes."""

import hashlib
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .beauty import Beauty
from .beauty import fixtures as beauty_fixtures

ROOT = Path(os.getenv("SOLUTION_DEMO_ROOT", Path.cwd())).resolve()


def fingerprint() -> str:
    digest = hashlib.sha256()
    for file in sorted((ROOT / "src/solution_labs").glob("*.py")):
        if file.name in {"evaluation.py"}:
            continue
        digest.update(file.name.encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def evaluation(project: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(dir=ROOT / ".tools") as directory:
        root = Path(directory)
        beauty = Beauty(root)

        def run(scenario: str) -> dict[str, Any]:
            role = "commercial" if scenario in {"authorization", "retrieval_acl"} else "finance"
            state = beauty.create(
                role, scenario if scenario in {"bad_batch", "duplicate", "currency"} else "clean"
            )
            if scenario == "reconciliation":
                records = beauty_fixtures()
                net = beauty.metric(state["run_id"], role, "net_revenue")["value"]
                cash = beauty.metric(state["run_id"], role, "cash_collected")["value"]
                passed = (
                    net == sum(r["net_cents"] for r in records["lines"]) / 100
                    and cash == sum(r["amount_cents"] for r in records["receipts"]) / 100
                )
            elif scenario in {"bad_batch", "duplicate", "currency"}:
                passed = bool(state["quality"]) and state["publish_version"] == 1
            elif scenario == "authorization":
                try:
                    beauty.ask(
                        state["run_id"], role, "Explain treasury cashflow policy", None, "all"
                    )
                except PermissionError:
                    passed = True
                else:
                    passed = False
            elif scenario == "retrieval_acl":
                from .beauty import retrieve

                state = beauty.ask(state["run_id"], role, "Explain promotion policy", None, "all")
                passed = all(
                    d["document_id"] != "D03" for d in retrieve("treasury cash reserve", role)
                ) and bool(state["citations"])
            elif scenario == "clarification":
                state = beauty.ask(state["run_id"], role, "Revenue and margin", None, "all")
                passed = bool(state.get("clarification")) and (not state["evidence"])
            else:
                metric = beauty.metric(state["run_id"], role, "margin_pct")
                rows = beauty_fixtures()["lines"]
                expected = (
                    100
                    * sum(r["net_cents"] - r["cost_cents"] for r in rows)
                    / sum(r["net_cents"] for r in rows)
                )
                passed = abs(metric["value"] - expected) < 0.0001
            return {"passed": passed, "output": state}

        scenarios = [
            "reconciliation",
            "ratios",
            "bad_batch",
            "duplicate",
            "currency",
            "authorization",
            "retrieval_acl",
            "clarification",
        ]
        results = []
        for scenario in scenarios:
            times = []
            result = None
            for _ in range(10):
                start = time.perf_counter()
                result = run(scenario)
                times.append((time.perf_counter() - start) * 1000)
            assert result is not None
            results.append(
                {
                    "scenario": scenario,
                    "runs": 10,
                    "passed": result["passed"],
                    "p50_ms": round(statistics.median(times), 3),
                    "p95_ms": round(max(times), 3),
                    "output": result["output"],
                }
            )
    return {
        "project": project,
        "implementation_fingerprint": fingerprint(),
        "passed": all(r["passed"] for r in results),
        "environment": {
            "python": sys.version.split()[0],
            "backend": "SQLite",
            "cloud_verified": False,
        },
        "method": "Ten sequential fresh-workspace runs per case. Timing includes workspace creation and scenario execution; nearest-rank p95 is the maximum of ten. Local synthetic measurement only.",
        "scenarios": results,
    }
