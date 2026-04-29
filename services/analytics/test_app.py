"""Tests for Analytics Service."""

import pytest

from app import app, health_records


@pytest.fixture
def client():
    app.config["TESTING"] = True
    health_records.clear()
    with app.test_client() as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "analytics"
    assert "uptime_seconds" in data


def test_add_record(client):
    payload = {"endpoint": "https://example.com", "status_code": 200, "response_time_ms": 42.5}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["endpoint"] == "https://example.com"
    assert data["status_code"] == 200
    assert data["response_time_ms"] == 42.5
    assert data["healthy"] is True


def test_add_record_unhealthy(client):
    payload = {"endpoint": "https://down.example.com", "status_code": 503, "response_time_ms": 1200}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["healthy"] is False


def test_add_record_missing_endpoint(client):
    payload = {"status_code": 200, "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_missing_status_code(client):
    payload = {"endpoint": "https://example.com", "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_missing_response_time(client):
    payload = {"endpoint": "https://example.com", "status_code": 200}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_empty_body(client):
    resp = client.post("/api/v1/records", content_type="application/json")
    assert resp.status_code == 400


def test_add_record_negative_response_time(client):
    payload = {"endpoint": "https://example.com", "status_code": 200, "response_time_ms": -5.0}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "non-negative" in data["error"]


def test_add_record_zero_response_time(client):
    payload = {"endpoint": "https://example.com", "status_code": 200, "response_time_ms": 0}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 201


def test_add_record_invalid_status_code(client):
    payload = {"endpoint": "https://example.com", "status_code": "abc", "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "integer" in data["error"]


def test_add_record_invalid_response_time(client):
    payload = {"endpoint": "https://example.com", "status_code": 200, "response_time_ms": "fast"}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400
    data = resp.get_json()
    assert "number" in data["error"]


def test_list_records(client):
    for i in range(3):
        client.post("/api/v1/records", json={
            "endpoint": "https://example.com",
            "status_code": 200,
            "response_time_ms": 10 + i,
        })
    resp = client.get("/api/v1/records")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 3
    assert len(data["records"]) == 3


def test_list_records_with_filter(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://b.com", "status_code": 200, "response_time_ms": 20})
    resp = client.get("/api/v1/records?endpoint=https://a.com")
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["endpoint"] == "https://a.com"


def test_list_records_with_limit(client):
    for i in range(5):
        client.post("/api/v1/records", json={"endpoint": "https://x.com", "status_code": 200, "response_time_ms": i})
    resp = client.get("/api/v1/records?limit=2")
    data = resp.get_json()
    assert len(data["records"]) == 2


def test_delete_records_success(client):
    client.post("/api/v1/records", json={"endpoint": "https://del.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://del.com", "status_code": 200, "response_time_ms": 20})
    client.post("/api/v1/records", json={"endpoint": "https://keep.com", "status_code": 200, "response_time_ms": 30})

    resp = client.delete("/api/v1/records?endpoint=https://del.com")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["message"] == "Records deleted"
    assert data["deleted_count"] == 2

    list_resp = client.get("/api/v1/records")
    assert list_resp.get_json()["total"] == 1


def test_delete_records_not_found(client):
    resp = client.delete("/api/v1/records?endpoint=https://nonexistent.com")
    assert resp.status_code == 404
    data = resp.get_json()
    assert "No records found" in data["error"]


def test_delete_records_missing_param(client):
    resp = client.delete("/api/v1/records")
    assert resp.status_code == 400
    data = resp.get_json()
    assert "endpoint" in data["error"].lower()


def test_delete_records_preserves_other_endpoints(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://b.com", "status_code": 200, "response_time_ms": 20})
    client.post("/api/v1/records", json={"endpoint": "https://c.com", "status_code": 200, "response_time_ms": 30})

    client.delete("/api/v1/records?endpoint=https://b.com")

    list_resp = client.get("/api/v1/records")
    data = list_resp.get_json()
    assert data["total"] == 2
    endpoints = [r["endpoint"] for r in data["records"]]
    assert "https://b.com" not in endpoints
    assert "https://a.com" in endpoints
    assert "https://c.com" in endpoints


def test_delete_records_updates_report(client):
    client.post("/api/v1/records", json={"endpoint": "https://x.com", "status_code": 200, "response_time_ms": 50})
    client.post("/api/v1/records", json={"endpoint": "https://y.com", "status_code": 200, "response_time_ms": 100})

    client.delete("/api/v1/records?endpoint=https://x.com")

    report_resp = client.get("/api/v1/report")
    data = report_resp.get_json()
    assert "https://x.com" not in data["endpoints"]
    assert "https://y.com" in data["endpoints"]


def test_report_empty(client):
    resp = client.get("/api/v1/report")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["endpoints"] == {}


def test_report_with_data(client):
    client.post("/api/v1/records", json={"endpoint": "https://api.com", "status_code": 200, "response_time_ms": 50})
    client.post("/api/v1/records", json={"endpoint": "https://api.com", "status_code": 200, "response_time_ms": 100})
    client.post("/api/v1/records", json={"endpoint": "https://api.com", "status_code": 500, "response_time_ms": 200})

    resp = client.get("/api/v1/report")
    data = resp.get_json()
    ep = data["endpoints"]["https://api.com"]
    assert ep["total_checks"] == 3
    assert ep["healthy_checks"] == 2
    assert ep["uptime_percent"] == pytest.approx(66.67, abs=0.01)
    assert ep["avg_response_time_ms"] == pytest.approx(116.67, abs=0.01)
    assert ep["min_response_time_ms"] == 50.0
    assert ep["max_response_time_ms"] == 200.0
