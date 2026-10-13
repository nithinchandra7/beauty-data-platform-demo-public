import pytest
from fastapi.testclient import TestClient

from solution_labs.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(state_root=tmp_path)) as connection:
        yield connection


def test_beauty_api_query_pipeline_and_role_denial(client):
    headers = {"X-Demo-Identity": "commercial"}
    state = client.post("/api/labs/beauty/runs", headers=headers, json={}).json()
    url = "/api/labs/beauty/runs/" + state["run_id"]
    assert client.get(url, headers=headers).status_code == 200
    assert (
        client.post(url + "/questions", headers=headers, json={"question": "cashflow"}).status_code
        == 403
    )
    assert (
        client.post(
            url + "/questions", headers=headers, json={"question": "revenue", "market": "GB"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            url + "/questions",
            headers=headers,
            json={"question": "revenue", "metric": "DROP TABLE"},
        ).status_code
        == 422
    )
    assert (
        client.post(url + "/pipeline", headers=headers, json={"scenario": "bad_batch"}).json()[
            "publish_version"
        ]
        == 1
    )
    assert client.post(
        url + "/questions", headers=headers, json={"question": "explain promotion policy"}
    ).json()["citations"]
