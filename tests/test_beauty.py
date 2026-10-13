from copy import deepcopy

import pytest

from solution_labs.beauty import Beauty, fixtures, retrieve, validate


def test_revenue_cash_and_receivables_reconcile_at_correct_grains(tmp_path):
    beauty = Beauty(tmp_path)
    state = beauty.create("finance", "clean")
    data = fixtures()
    net = sum(r["net_cents"] for r in data["lines"]) / 100
    cash = sum(r["amount_cents"] for r in data["receipts"]) / 100
    key = state["run_id"]
    assert beauty.metric(key, "finance", "net_revenue")["value"] == net
    assert beauty.metric(key, "finance", "cash_collected")["value"] == cash
    balance = (
        sum(r["net_cents"] for r in data["lines"])
        - sum(r["amount_cents"] for r in data["receipts"])
    ) / 100
    assert beauty.metric(key, "finance", "receivables")["value"] == balance
    expected = (
        100
        * sum(r["net_cents"] - r["cost_cents"] for r in data["lines"])
        / sum(r["net_cents"] for r in data["lines"])
    )
    assert beauty.metric(key, "finance", "margin_pct")["value"] == round(expected, 4)


@pytest.mark.parametrize("scenario", ["bad_batch", "duplicate", "currency"])
def test_bad_batches_preserve_gold_and_replay_is_idempotent(tmp_path, scenario):
    beauty = Beauty(tmp_path)
    state = beauty.create("finance", "clean")
    before = state["metrics"]
    failed = beauty.pipeline(state["run_id"], "finance", scenario)
    assert failed["quality"] and failed["publish_version"] == 1
    assert failed["metrics"] == before and failed["bronze_batches"] == 2
    replay = beauty.pipeline(state["run_id"], "finance", "clean")
    assert replay["publish_version"] == 1 and not replay["quality"]


def test_market_finance_and_workspace_permissions(tmp_path):
    beauty = Beauty(tmp_path)
    state = beauty.create("commercial", "clean")
    assert len(state["metrics"]) == 3
    for metric, market in [("cash_collected", "all"), ("net_revenue", "GB")]:
        with pytest.raises(PermissionError):
            beauty.metric(state["run_id"], "commercial", metric, market)
    with pytest.raises(LookupError):
        beauty.snapshot(state["run_id"], "finance")
    with pytest.raises(ValueError):
        beauty.metric(state["run_id"], "commercial", "DROP TABLE")
    us = beauty.metric(state["run_id"], "commercial", "net_revenue", "US")
    assert us["markets"] == ["US"] and us["rows"] == 40


def test_finance_denial_happens_before_retrieval(tmp_path):
    beauty = Beauty(tmp_path)
    state = beauty.create("commercial", "clean")
    with pytest.raises(PermissionError):
        beauty.ask(state["run_id"], "commercial", "Explain treasury cashflow policy", None, "all")
    assert all(d["document_id"] != "D03" for d in retrieve("treasury cash reserve", "commercial"))


def test_answers_are_calculated_and_citations_are_authorized(tmp_path):
    beauty = Beauty(tmp_path)
    state = beauty.create("finance", "clean")
    answer = beauty.ask(
        state["run_id"], "finance", "What is net revenue and explain promotion policy?", None, "US"
    )
    assert answer["evidence"] == beauty.metric(state["run_id"], "finance", "net_revenue", "US")
    assert answer["citations"] and "SQL" not in answer["answer"]
    policy = beauty.ask(state["run_id"], "finance", "Explain promotion policy", None, "all")
    assert policy["evidence"] is None and policy["citations"]


@pytest.mark.parametrize(
    "question",
    [
        "revenue and margin",
        "SELECT * FROM cashflow",
        "predict next year's growth",
        "revenue last year",
        "not margin",
        "gross revenue",
        "margin in dollars",
        "cash collected next month",
        "What was revenue in January?",
        "Revenue by product",
        "Revenue in euros",
    ],
)
def test_unsupported_or_ambiguous_questions_clarify(tmp_path, question):
    beauty = Beauty(tmp_path)
    state = beauty.create("finance", "clean")
    answer = beauty.ask(state["run_id"], "finance", question, None, "all")
    assert answer.get("clarification") and answer["evidence"] is None


def test_zero_lexical_overlap_and_invalid_workspace(tmp_path):
    assert retrieve("xyzzy", "commercial") == []
    beauty = Beauty(tmp_path)
    with pytest.raises(ValueError):
        beauty.connection("../../etc/passwd")
    state = beauty.create("finance", "clean")
    answer = beauty.ask(state["run_id"], "finance", "Explain xyzzy policy", None, "all")
    assert not answer["citations"] and "No authorized" in answer["answer"]


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda d: d["lines"].append(dict(d["lines"][0])), "Duplicate"),
        (lambda d: d["lines"][0].update(invoice_id="unknown"), "Orphan"),
        (lambda d: d["lines"][0].update(market="CA"), "market mismatch"),
        (lambda d: d["lines"][0].update(net_cents=-1), "Negative"),
        (lambda d: d["lines"][0].update(returns=999), "impossible"),
        (lambda d: d["receipts"][0].update(amount_cents=99999999), "exceeds"),
        (lambda d: d["receipts"][0].update(invoice_id="unknown"), "Orphan"),
        (lambda d: d["receipts"][0].update(received_date="2099-01-01"), "Future"),
    ],
)
def test_source_quality_contract(mutation, expected):
    data = deepcopy(fixtures())
    mutation(data)
    assert any(expected in message for message in validate(data))


def test_policy_retrieval_cannot_extend_market_scope(tmp_path):
    beauty = Beauty(tmp_path)
    state = beauty.create("commercial", "clean")
    with pytest.raises(PermissionError):
        beauty.ask(state["run_id"], "commercial", "Explain promotion policy", None, "GB")


def test_explicit_metric_does_not_override_unsupported_time_or_currency(tmp_path):
    beauty = Beauty(tmp_path)
    state = beauty.create("finance", "clean")
    result = beauty.ask(state["run_id"], "finance", "revenue in January", "net_revenue", "all")
    assert result.get("clarification") and result["trace"]["stages"][0]["component"] == "tools"


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("lines", "units", -1),
        ("lines", "returns", -1),
        ("lines", "net_cents", 0.5),
        ("invoices", "due_date", "bad-date"),
        ("invoices", "invoice_id", None),
        ("invoices", "market", "DE"),
    ],
)
def test_preflight_types_dates_and_markets_fail_closed(table, field, value):
    data = deepcopy(fixtures())
    data[table][0][field] = value
    assert validate(data)


def test_dashboard_uses_one_read_snapshot_during_concurrent_publication(tmp_path, monkeypatch):
    from threading import Event, Thread

    import solution_labs.beauty as module

    beauty = Beauty(tmp_path)
    state = beauty.create("finance", "clean")
    raw = fixtures()
    raw["lines"][0]["gross_cents"] += 100
    raw["lines"][0]["net_cents"] += 100
    raw["invoices"][0]["amount_cents"] += 100
    monkeypatch.setattr(module, "fixtures", lambda: deepcopy(raw))
    started = Event()
    outcomes = []

    def writer():
        started.set()
        outcomes.append(beauty.pipeline(state["run_id"], "finance", "clean"))

    with beauty.read(state["run_id"], "finance") as (connection, old, _revision):
        first = beauty.query_metric(connection, "finance", "net_revenue")
        thread = Thread(target=writer)
        thread.start()
        assert started.wait(2)
        second = beauty.query_metric(connection, "finance", "cash_collected")
        assert first["publish_version"] == second["publish_version"] == old["publish_version"] == 1
    thread.join(5)
    assert not thread.is_alive() and outcomes[0]["publish_version"] == 2
