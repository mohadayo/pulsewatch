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


def test_delete_records_via_json_body():
    """Gateway proxies DELETE with JSON body; analytics must accept it."""
    from app import app as _app
    c = _app.test_client()
    c.post("/api/v1/records", json={
        "endpoint": "https://body.example.com", "status_code": 200, "response_time_ms": 10,
    })
    resp = c.delete("/api/v1/records", json={"endpoint": "https://body.example.com"})
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1


def test_delete_records_query_takes_precedence_over_body(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://qs.example.com", "status_code": 200, "response_time_ms": 10,
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://body.example.com", "status_code": 200, "response_time_ms": 10,
    })
    resp = client.delete(
        "/api/v1/records?endpoint=https://qs.example.com",
        json={"endpoint": "https://body.example.com"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1
    list_resp = client.get("/api/v1/records")
    endpoints = [r["endpoint"] for r in list_resp.get_json()["records"]]
    assert "https://qs.example.com" not in endpoints
    assert "https://body.example.com" in endpoints


def test_delete_records_by_until(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://old.com", "status_code": 200, "response_time_ms": 10,
        "checked_at": "2025-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://new.com", "status_code": 200, "response_time_ms": 10,
        "checked_at": "2026-06-01T00:00:00+00:00",
    })
    resp = client.delete("/api/v1/records?until=2025-12-31T23:59:59%2B00:00")
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1
    list_resp = client.get("/api/v1/records")
    remaining = [r["endpoint"] for r in list_resp.get_json()["records"]]
    assert remaining == ["https://new.com"]


def test_delete_records_by_since(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://old.com", "status_code": 200, "response_time_ms": 10,
        "checked_at": "2025-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://new.com", "status_code": 200, "response_time_ms": 10,
        "checked_at": "2026-06-01T00:00:00+00:00",
    })
    resp = client.delete("/api/v1/records?since=2026-01-01T00:00:00%2B00:00")
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1
    list_resp = client.get("/api/v1/records")
    remaining = [r["endpoint"] for r in list_resp.get_json()["records"]]
    assert remaining == ["https://old.com"]


def test_delete_records_by_status_code(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://x.com", "status_code": 500, "response_time_ms": 10,
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://y.com", "status_code": 200, "response_time_ms": 10,
    })
    resp = client.delete("/api/v1/records?status_code=500")
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1
    list_resp = client.get("/api/v1/records")
    remaining = [r["status_code"] for r in list_resp.get_json()["records"]]
    assert remaining == [200]


def test_delete_records_by_healthy_false(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://up.com", "status_code": 200, "response_time_ms": 10,
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://down.com", "status_code": 503, "response_time_ms": 10,
    })
    resp = client.delete("/api/v1/records?healthy=false")
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1
    list_resp = client.get("/api/v1/records")
    remaining = [r["endpoint"] for r in list_resp.get_json()["records"]]
    assert remaining == ["https://up.com"]


def test_delete_records_combined_filters(client):
    """Records matching ALL filters are deleted."""
    client.post("/api/v1/records", json={
        "endpoint": "https://api.com", "status_code": 500, "response_time_ms": 10,
        "checked_at": "2025-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://api.com", "status_code": 200, "response_time_ms": 10,
        "checked_at": "2025-01-01T00:00:00+00:00",
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://other.com", "status_code": 500, "response_time_ms": 10,
        "checked_at": "2025-01-01T00:00:00+00:00",
    })
    resp = client.delete(
        "/api/v1/records?endpoint=https://api.com&status_code=500"
    )
    assert resp.status_code == 200
    assert resp.get_json()["deleted_count"] == 1


def test_delete_records_invalid_since(client):
    resp = client.delete("/api/v1/records?since=not-a-date")
    assert resp.status_code == 400
    assert "since" in resp.get_json()["error"].lower()


def test_delete_records_until_before_since(client):
    resp = client.delete(
        "/api/v1/records?since=2026-06-01T00:00:00%2B00:00&until=2025-01-01T00:00:00%2B00:00"
    )
    assert resp.status_code == 400


def test_delete_records_invalid_status_code(client):
    resp = client.delete("/api/v1/records?status_code=999")
    assert resp.status_code == 400


def test_delete_records_no_match_404(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://existing.com", "status_code": 200, "response_time_ms": 10,
    })
    resp = client.delete("/api/v1/records?status_code=404")
    assert resp.status_code == 404
    assert "no records found" in resp.get_json()["error"].lower()


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


def test_list_records_filter_healthy_true(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 500, "response_time_ms": 20})
    resp = client.get("/api/v1/records?healthy=true")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["status_code"] == 200


def test_list_records_filter_healthy_false(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 503, "response_time_ms": 20})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 502, "response_time_ms": 30})
    resp = client.get("/api/v1/records?healthy=false")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert all(r["healthy"] is False for r in data["records"])


def test_list_records_healthy_accepts_aliases(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 500, "response_time_ms": 20})
    for alias in ("1", "yes", "TRUE"):
        resp = client.get(f"/api/v1/records?healthy={alias}")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 1
    for alias in ("0", "no", "FALSE"):
        resp = client.get(f"/api/v1/records?healthy={alias}")
        assert resp.status_code == 200
        assert resp.get_json()["total"] == 1


def test_list_records_healthy_rejects_invalid(client):
    resp = client.get("/api/v1/records?healthy=maybe")
    assert resp.status_code == 400
    assert "healthy" in resp.get_json()["error"]


def test_report_filter_healthy_only_unhealthy(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 500, "response_time_ms": 50})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 502, "response_time_ms": 100})
    resp = client.get("/api/v1/report?healthy=false")
    assert resp.status_code == 200
    data = resp.get_json()
    stats = data["endpoints"]["https://a.com"]
    assert stats["total_checks"] == 2
    assert stats["healthy_checks"] == 0
    assert stats["uptime_percent"] == 0


def test_report_healthy_rejects_invalid(client):
    resp = client.get("/api/v1/report?healthy=meh")
    assert resp.status_code == 400


def test_list_records_filter_status_code(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 404, "response_time_ms": 20})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 500, "response_time_ms": 30})
    client.post("/api/v1/records", json={"endpoint": "https://b.com", "status_code": 404, "response_time_ms": 40})
    resp = client.get("/api/v1/records?status_code=404")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert all(r["status_code"] == 404 for r in data["records"])


def test_list_records_status_code_combined_with_endpoint(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 500, "response_time_ms": 20})
    client.post("/api/v1/records", json={"endpoint": "https://b.com", "status_code": 500, "response_time_ms": 30})
    resp = client.get("/api/v1/records?endpoint=https://a.com&status_code=500")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["endpoint"] == "https://a.com"
    assert data["records"][0]["status_code"] == 500


def test_list_records_status_code_rejects_non_integer(client):
    resp = client.get("/api/v1/records?status_code=abc")
    assert resp.status_code == 400
    assert "status_code" in resp.get_json()["error"]


def test_list_records_status_code_rejects_out_of_range(client):
    resp = client.get("/api/v1/records?status_code=42")
    assert resp.status_code == 400
    assert "status_code" in resp.get_json()["error"]
    resp = client.get("/api/v1/records?status_code=999")
    assert resp.status_code == 400


def test_report_filter_status_code(client):
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 200, "response_time_ms": 10})
    client.post("/api/v1/records", json={"endpoint": "https://a.com", "status_code": 500, "response_time_ms": 50})
    client.post("/api/v1/records", json={"endpoint": "https://b.com", "status_code": 500, "response_time_ms": 70})
    resp = client.get("/api/v1/report?status_code=500")
    assert resp.status_code == 200
    data = resp.get_json()
    eps = data["endpoints"]
    assert set(eps.keys()) == {"https://a.com", "https://b.com"}
    assert eps["https://a.com"]["total_checks"] == 1
    assert eps["https://b.com"]["total_checks"] == 1


def test_report_status_code_rejects_invalid(client):
    resp = client.get("/api/v1/report?status_code=notanint")
    assert resp.status_code == 400
    assert "status_code" in resp.get_json()["error"]


def test_report_includes_percentiles(client):
    for i in range(1, 11):
        client.post(
            "/api/v1/records",
            json={
                "endpoint": "https://percentile.test",
                "status_code": 200,
                "response_time_ms": float(i * 10),
            },
        )
    data = client.get("/api/v1/report").get_json()
    stats = data["endpoints"]["https://percentile.test"]
    assert stats["min_response_time_ms"] == 10.0
    assert stats["max_response_time_ms"] == 100.0
    assert stats["p50_response_time_ms"] == 55.0
    assert stats["p95_response_time_ms"] >= 90.0
    assert stats["p99_response_time_ms"] >= 95.0


def test_report_percentile_single_sample(client):
    client.post(
        "/api/v1/records",
        json={
            "endpoint": "https://one.test",
            "status_code": 200,
            "response_time_ms": 42.0,
        },
    )
    stats = client.get("/api/v1/report").get_json()["endpoints"]["https://one.test"]
    assert stats["p50_response_time_ms"] == 42.0
    assert stats["p95_response_time_ms"] == 42.0
    assert stats["p99_response_time_ms"] == 42.0


def test_list_records_sort_by_response_time_asc(client):
    for v in [50.0, 10.0, 30.0]:
        client.post(
            "/api/v1/records",
            json={
                "endpoint": "https://sort.test",
                "status_code": 200,
                "response_time_ms": v,
            },
        )
    resp = client.get("/api/v1/records?sort=response_time_ms&order=asc")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sort"] == "response_time_ms"
    assert data["order"] == "asc"
    rts = [r["response_time_ms"] for r in data["records"]]
    assert rts == [10.0, 30.0, 50.0]


def test_list_records_sort_by_response_time_desc(client):
    for v in [50.0, 10.0, 30.0]:
        client.post(
            "/api/v1/records",
            json={
                "endpoint": "https://sort.test",
                "status_code": 200,
                "response_time_ms": v,
            },
        )
    rts = [r["response_time_ms"] for r in client.get(
        "/api/v1/records?sort=response_time_ms&order=desc"
    ).get_json()["records"]]
    assert rts == [50.0, 30.0, 10.0]


def test_list_records_sort_by_endpoint(client):
    for ep in ["https://zebra.test", "https://apple.test", "https://mango.test"]:
        client.post(
            "/api/v1/records",
            json={"endpoint": ep, "status_code": 200, "response_time_ms": 1.0},
        )
    eps = [r["endpoint"] for r in client.get(
        "/api/v1/records?sort=endpoint"
    ).get_json()["records"]]
    assert eps == ["https://apple.test", "https://mango.test", "https://zebra.test"]


def test_list_records_rejects_invalid_sort_field(client):
    resp = client.get("/api/v1/records?sort=bogus")
    assert resp.status_code == 400
    assert "sort" in resp.get_json()["error"]


def test_list_records_rejects_invalid_sort_order(client):
    resp = client.get("/api/v1/records?order=sideways")
    assert resp.status_code == 400
    assert "order" in resp.get_json()["error"]


def test_records_lock_concurrent_writes():
    from app import health_records, records_lock
    import threading as _threading

    health_records.clear()

    def writer(tag):
        for i in range(40):
            with records_lock:
                health_records.append({
                    "endpoint": f"https://{tag}.test",
                    "status_code": 200,
                    "response_time_ms": float(i),
                    "checked_at": "2024-01-01T00:00:00+00:00",
                    "healthy": True,
                })

    threads = [_threading.Thread(target=writer, args=(f"t{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(health_records) == 4 * 40


# --- min/max_response_time_ms filter ---


def _seed_response_times(client):
    for rt in [50.0, 150.0, 250.0, 500.0, 1000.0]:
        client.post("/api/v1/records", json={
            "endpoint": "https://example.com",
            "status_code": 200,
            "response_time_ms": rt,
        })


def test_records_min_response_time_filter(client):
    _seed_response_times(client)
    resp = client.get("/api/v1/records?min_response_time_ms=200")
    assert resp.status_code == 200
    data = resp.get_json()
    times = sorted(r["response_time_ms"] for r in data["records"])
    assert times == [250.0, 500.0, 1000.0]


def test_records_max_response_time_filter(client):
    _seed_response_times(client)
    resp = client.get("/api/v1/records?max_response_time_ms=200")
    assert resp.status_code == 200
    data = resp.get_json()
    times = sorted(r["response_time_ms"] for r in data["records"])
    assert times == [50.0, 150.0]


def test_records_response_time_range_filter(client):
    _seed_response_times(client)
    resp = client.get(
        "/api/v1/records?min_response_time_ms=100&max_response_time_ms=400"
    )
    data = resp.get_json()
    times = sorted(r["response_time_ms"] for r in data["records"])
    assert times == [150.0, 250.0]


def test_records_response_time_inclusive_boundaries(client):
    _seed_response_times(client)
    resp = client.get(
        "/api/v1/records?min_response_time_ms=150&max_response_time_ms=500"
    )
    data = resp.get_json()
    times = sorted(r["response_time_ms"] for r in data["records"])
    assert times == [150.0, 250.0, 500.0]


def test_records_min_response_time_invalid(client):
    cases = [
        "/api/v1/records?min_response_time_ms=abc",
        "/api/v1/records?min_response_time_ms=-1",
        "/api/v1/records?min_response_time_ms=inf",
        "/api/v1/records?min_response_time_ms=nan",
    ]
    for url in cases:
        resp = client.get(url)
        assert resp.status_code == 400, f"expected 400 for {url}"


def test_records_max_response_time_invalid(client):
    resp = client.get("/api/v1/records?max_response_time_ms=xyz")
    assert resp.status_code == 400


def test_records_max_less_than_min(client):
    resp = client.get(
        "/api/v1/records?min_response_time_ms=200&max_response_time_ms=100"
    )
    assert resp.status_code == 400
    assert "max_response_time_ms" in resp.get_json()["error"]


def test_records_response_time_combined_with_endpoint(client):
    client.post("/api/v1/records", json={
        "endpoint": "https://a.example.com", "status_code": 200, "response_time_ms": 100,
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://a.example.com", "status_code": 200, "response_time_ms": 300,
    })
    client.post("/api/v1/records", json={
        "endpoint": "https://b.example.com", "status_code": 200, "response_time_ms": 300,
    })
    resp = client.get(
        "/api/v1/records?endpoint=https://a.example.com&min_response_time_ms=200"
    )
    data = resp.get_json()
    assert data["total"] == 1
    assert data["records"][0]["response_time_ms"] == 300


def test_report_min_response_time_filter(client):
    _seed_response_times(client)
    resp = client.get("/api/v1/report?min_response_time_ms=300")
    assert resp.status_code == 200
    data = resp.get_json()
    ep_data = data["endpoints"]["https://example.com"]
    assert ep_data["total_checks"] == 2
    assert ep_data["min_response_time_ms"] == 500.0
    assert ep_data["max_response_time_ms"] == 1000.0


def test_report_response_time_range(client):
    _seed_response_times(client)
    resp = client.get(
        "/api/v1/report?min_response_time_ms=100&max_response_time_ms=600"
    )
    data = resp.get_json()
    ep_data = data["endpoints"]["https://example.com"]
    assert ep_data["total_checks"] == 3
    assert ep_data["min_response_time_ms"] == 150.0
    assert ep_data["max_response_time_ms"] == 500.0


def test_report_max_less_than_min_returns_400(client):
    resp = client.get(
        "/api/v1/report?min_response_time_ms=500&max_response_time_ms=100"
    )
    assert resp.status_code == 400


def test_report_response_time_invalid(client):
    resp = client.get("/api/v1/report?min_response_time_ms=bad")
    assert resp.status_code == 400
