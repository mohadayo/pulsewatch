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
    assert data["limit"] == 2


def test_list_records_rejects_zero_limit(client):
    resp = client.get("/api/v1/records?limit=0")
    assert resp.status_code == 400


def test_list_records_rejects_negative_limit(client):
    resp = client.get("/api/v1/records?limit=-5")
    assert resp.status_code == 400


def test_list_records_rejects_limit_above_max(client):
    resp = client.get("/api/v1/records?limit=99999")
    assert resp.status_code == 400


def test_list_records_rejects_non_numeric_limit(client):
    resp = client.get("/api/v1/records?limit=abc")
    assert resp.status_code == 400


def test_list_records_with_offset(client):
    for i in range(5):
        client.post("/api/v1/records", json={"endpoint": "https://x.com", "status_code": 200, "response_time_ms": i})
    resp = client.get("/api/v1/records?limit=2&offset=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["records"]) == 2
    assert data["offset"] == 2
    assert data["total"] == 5
    # offset starts from index 2 → response_time_ms 2 and 3
    times = [r["response_time_ms"] for r in data["records"]]
    assert times == [2.0, 3.0]


def test_list_records_offset_beyond_total(client):
    for i in range(3):
        client.post("/api/v1/records", json={"endpoint": "https://x.com", "status_code": 200, "response_time_ms": i})
    resp = client.get("/api/v1/records?offset=10")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["records"]) == 0
    assert data["total"] == 3


def test_list_records_rejects_negative_offset(client):
    resp = client.get("/api/v1/records?offset=-1")
    assert resp.status_code == 400


def test_list_records_rejects_non_numeric_offset(client):
    resp = client.get("/api/v1/records?offset=abc")
    assert resp.status_code == 400


def test_list_records_filter_since(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 1,
        "checked_at": "2024-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 2,
        "checked_at": "2025-06-01T00:00:00+00:00",
    })
    resp = client.get("/api/v1/records?since=2025-01-01T00:00:00%2B00:00")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["response_time_ms"] == 2.0


def test_list_records_filter_until(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 1,
        "checked_at": "2024-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 2,
        "checked_at": "2025-06-01T00:00:00+00:00",
    })
    resp = client.get("/api/v1/records?until=2024-12-31T23:59:59%2B00:00")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["response_time_ms"] == 1.0


def test_list_records_filter_since_and_until(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 1,
        "checked_at": "2024-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 2,
        "checked_at": "2024-06-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 200, "response_time_ms": 3,
        "checked_at": "2025-06-01T00:00:00+00:00",
    })
    resp = client.get(
        "/api/v1/records?since=2024-03-01T00:00:00%2B00:00&until=2024-12-31T23:59:59%2B00:00"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["response_time_ms"] == 2.0


def test_list_records_rejects_invalid_since(client):
    resp = client.get("/api/v1/records?since=not-a-date")
    assert resp.status_code == 400
    assert "since" in resp.get_json()["error"]


def test_list_records_rejects_invalid_until(client):
    resp = client.get("/api/v1/records?until=2024-13-99T00:00:00")
    assert resp.status_code == 400
    assert "until" in resp.get_json()["error"]


def test_list_records_rejects_until_before_since(client):
    resp = client.get(
        "/api/v1/records?since=2025-01-01T00:00:00%2B00:00&until=2024-01-01T00:00:00%2B00:00"
    )
    assert resp.status_code == 400
    assert "until" in resp.get_json()["error"].lower()


def test_add_record_rejects_endpoint_without_scheme(client):
    payload = {"endpoint": "example.com/path", "status_code": 200, "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400
    assert "http://" in resp.get_json()["error"]


def test_add_record_rejects_blank_endpoint(client):
    payload = {"endpoint": "   ", "status_code": 200, "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_rejects_overlong_endpoint(client):
    payload = {
        "endpoint": "https://" + "a" * 3000,
        "status_code": 200,
        "response_time_ms": 10,
    }
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400
    assert "at most" in resp.get_json()["error"]


def test_add_record_rejects_status_code_out_of_range_low(client):
    payload = {"endpoint": "https://e.com", "status_code": 99, "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_rejects_status_code_out_of_range_high(client):
    payload = {"endpoint": "https://e.com", "status_code": 600, "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_accepts_status_code_at_boundary(client):
    for code in (100, 599):
        payload = {"endpoint": "https://e.com", "status_code": code, "response_time_ms": 1}
        resp = client.post("/api/v1/records", json=payload)
        assert resp.status_code == 201, f"failed for {code}"


def test_add_record_rejects_response_time_above_max(client):
    payload = {
        "endpoint": "https://e.com",
        "status_code": 200,
        "response_time_ms": 600001,
    }
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_rejects_invalid_checked_at(client):
    payload = {
        "endpoint": "https://e.com",
        "status_code": 200,
        "response_time_ms": 10,
        "checked_at": "banana",
    }
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


def test_add_record_accepts_iso8601_checked_at(client):
    payload = {
        "endpoint": "https://e.com",
        "status_code": 200,
        "response_time_ms": 10,
        "checked_at": "2026-05-07T12:34:56+00:00",
    }
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 201
    assert resp.get_json()["checked_at"] == "2026-05-07T12:34:56+00:00"


def test_add_record_strips_endpoint(client):
    payload = {
        "endpoint": "  https://e.com/path  ",
        "status_code": 200,
        "response_time_ms": 10,
    }
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 201
    assert resp.get_json()["endpoint"] == "https://e.com/path"


def test_add_record_rejects_status_code_boolean(client):
    payload = {"endpoint": "https://e.com", "status_code": True, "response_time_ms": 10}
    resp = client.post("/api/v1/records", json=payload)
    assert resp.status_code == 400


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


def test_records_store_max_capacity(client, monkeypatch):
    monkeypatch.setattr("app.MAX_RECORDS", 3)
    for i in range(5):
        client.post("/api/v1/records", json={
            "endpoint": f"https://ep-{i}.com",
            "status_code": 200,
            "response_time_ms": 10 + i,
        })
    resp = client.get("/api/v1/records")
    data = resp.get_json()
    assert data["total"] == 3
    endpoints = [r["endpoint"] for r in data["records"]]
    assert "https://ep-0.com" not in endpoints
    assert "https://ep-1.com" not in endpoints
    assert "https://ep-4.com" in endpoints


def test_records_store_within_capacity(client, monkeypatch):
    monkeypatch.setattr("app.MAX_RECORDS", 10)
    for i in range(3):
        client.post("/api/v1/records", json={
            "endpoint": f"https://ep-{i}.com",
            "status_code": 200,
            "response_time_ms": 10,
        })
    resp = client.get("/api/v1/records")
    data = resp.get_json()
    assert data["total"] == 3


def test_records_store_eviction_preserves_order(client, monkeypatch):
    monkeypatch.setattr("app.MAX_RECORDS", 2)
    for i in range(4):
        client.post("/api/v1/records", json={
            "endpoint": f"https://ep-{i}.com",
            "status_code": 200,
            "response_time_ms": float(i),
        })
    resp = client.get("/api/v1/records")
    data = resp.get_json()
    assert data["total"] == 2
    assert data["records"][0]["endpoint"] == "https://ep-2.com"
    assert data["records"][1]["endpoint"] == "https://ep-3.com"


def test_report_filters_by_endpoint(client):
    health_records.append({
        "endpoint": "https://a.example.com/h",
        "status_code": 200,
        "response_time_ms": 10.0,
        "checked_at": "2026-01-01T00:00:00+00:00",
        "healthy": True,
    })
    health_records.append({
        "endpoint": "https://b.example.com/h",
        "status_code": 500,
        "response_time_ms": 100.0,
        "checked_at": "2026-01-01T00:00:00+00:00",
        "healthy": False,
    })
    resp = client.get("/api/v1/report?endpoint=https://a.example.com/h")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "https://a.example.com/h" in data["endpoints"]
    assert "https://b.example.com/h" not in data["endpoints"]


def test_report_filters_by_since(client):
    health_records.append({
        "endpoint": "https://x.example.com/h",
        "status_code": 200,
        "response_time_ms": 10.0,
        "checked_at": "2024-01-01T00:00:00+00:00",
        "healthy": True,
    })
    health_records.append({
        "endpoint": "https://x.example.com/h",
        "status_code": 200,
        "response_time_ms": 20.0,
        "checked_at": "2026-06-01T00:00:00+00:00",
        "healthy": True,
    })
    resp = client.get("/api/v1/report?since=2026-01-01T00:00:00Z")
    assert resp.status_code == 200
    data = resp.get_json()
    stats = data["endpoints"]["https://x.example.com/h"]
    assert stats["total_checks"] == 1
    assert stats["avg_response_time_ms"] == 20.0


def test_report_filters_by_until(client):
    health_records.append({
        "endpoint": "https://x.example.com/h",
        "status_code": 200,
        "response_time_ms": 10.0,
        "checked_at": "2024-01-01T00:00:00+00:00",
        "healthy": True,
    })
    health_records.append({
        "endpoint": "https://x.example.com/h",
        "status_code": 200,
        "response_time_ms": 20.0,
        "checked_at": "2026-06-01T00:00:00+00:00",
        "healthy": True,
    })
    resp = client.get("/api/v1/report?until=2025-01-01T00:00:00Z")
    assert resp.status_code == 200
    data = resp.get_json()
    stats = data["endpoints"]["https://x.example.com/h"]
    assert stats["total_checks"] == 1
    assert stats["avg_response_time_ms"] == 10.0


def test_report_rejects_invalid_since(client):
    resp = client.get("/api/v1/report?since=garbage")
    assert resp.status_code == 400
    assert "since" in resp.get_json()["error"]


def test_report_rejects_until_before_since(client):
    resp = client.get("/api/v1/report?since=2026-06-01T00:00:00Z&until=2024-01-01T00:00:00Z")
    assert resp.status_code == 400


def test_report_returns_no_records_when_filter_excludes_all(client):
    health_records.append({
        "endpoint": "https://x.example.com/h",
        "status_code": 200,
        "response_time_ms": 10.0,
        "checked_at": "2024-01-01T00:00:00+00:00",
        "healthy": True,
    })
    resp = client.get("/api/v1/report?endpoint=https://does-not-exist.example/h")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["endpoints"] == {}
