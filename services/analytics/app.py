"""PulseWatch Analytics Service - Processes health check data and generates reports."""

import logging
import math
import os
import time
from datetime import datetime, timezone
from flask import Flask, jsonify, request

app = Flask(__name__)

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("analytics")

PORT = int(os.environ.get("ANALYTICS_PORT", 5000))
MAX_RECORDS = int(os.environ.get("MAX_RECORDS", "10000"))
MAX_ENDPOINT_LENGTH = int(os.environ.get("MAX_ENDPOINT_LENGTH", "2048"))
MAX_RESPONSE_TIME_MS = float(os.environ.get("MAX_RESPONSE_TIME_MS", "600000"))
LIST_DEFAULT_LIMIT = int(os.environ.get("LIST_DEFAULT_LIMIT", "100"))
LIST_MAX_LIMIT = int(os.environ.get("LIST_MAX_LIMIT", "1000"))

# In-memory store for health check results
health_records: list[dict] = []
start_time = time.time()


@app.route("/health")
def health():
    uptime = time.time() - start_time
    return jsonify({"status": "ok", "service": "analytics", "uptime_seconds": round(uptime, 2)})


@app.route("/api/v1/records", methods=["POST"])
def add_record():
    data = request.get_json(silent=True)
    if not data:
        logger.warning("Received empty payload for record creation")
        return jsonify({"error": "Request body is required"}), 400

    endpoint = data.get("endpoint")
    status_code = data.get("status_code")
    response_time_ms = data.get("response_time_ms")

    if not endpoint:
        return jsonify({"error": "Field 'endpoint' is required"}), 400
    if status_code is None:
        return jsonify({"error": "Field 'status_code' is required"}), 400
    if response_time_ms is None:
        return jsonify({"error": "Field 'response_time_ms' is required"}), 400

    if not isinstance(endpoint, str):
        return jsonify({"error": "Field 'endpoint' must be a string"}), 400
    endpoint = endpoint.strip()
    if not endpoint:
        return jsonify({"error": "Field 'endpoint' must not be blank"}), 400
    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        return jsonify({
            "error": f"Field 'endpoint' must be at most {MAX_ENDPOINT_LENGTH} characters"
        }), 400
    if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        return jsonify({
            "error": "Field 'endpoint' must start with http:// or https://"
        }), 400

    if isinstance(status_code, bool):
        return jsonify({"error": "Field 'status_code' must be an integer"}), 400
    try:
        status_code = int(status_code)
    except (ValueError, TypeError):
        return jsonify({"error": "Field 'status_code' must be an integer"}), 400
    if not (100 <= status_code <= 599):
        return jsonify({
            "error": "Field 'status_code' must be between 100 and 599"
        }), 400

    try:
        response_time_ms = float(response_time_ms)
    except (ValueError, TypeError):
        return jsonify({"error": "Field 'response_time_ms' must be a number"}), 400
    if not math.isfinite(response_time_ms):
        return jsonify({"error": "Field 'response_time_ms' must be a finite number"}), 400
    if response_time_ms < 0:
        return jsonify({"error": "Field 'response_time_ms' must be non-negative"}), 400
    if response_time_ms > MAX_RESPONSE_TIME_MS:
        return jsonify({
            "error": f"Field 'response_time_ms' must be at most {MAX_RESPONSE_TIME_MS}"
        }), 400

    checked_at_input = data.get("checked_at")
    if checked_at_input is not None:
        if not isinstance(checked_at_input, str):
            return jsonify({"error": "Field 'checked_at' must be an ISO 8601 string"}), 400
        try:
            datetime.fromisoformat(checked_at_input.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "Field 'checked_at' must be ISO 8601"}), 400
        checked_at_value = checked_at_input
    else:
        checked_at_value = datetime.now(timezone.utc).isoformat()

    record = {
        "endpoint": endpoint,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "checked_at": checked_at_value,
        "healthy": 200 <= status_code < 400,
    }
    health_records.append(record)

    if len(health_records) > MAX_RECORDS:
        removed = len(health_records) - MAX_RECORDS
        del health_records[:removed]
        logger.info("Evicted %d old records (store capped at %d)", removed, MAX_RECORDS)

    logger.info(
        "Recorded health check for %s: status=%d, time=%.1fms",
        endpoint, record["status_code"], record["response_time_ms"]
    )
    return jsonify(record), 201


def _parse_iso8601_arg(value: str, name: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as e:
        raise ValueError(f"Query parameter '{name}' must be ISO 8601") from e


def _record_checked_at(record: dict) -> datetime | None:
    raw = record.get("checked_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@app.route("/api/v1/records", methods=["GET"])
def list_records():
    endpoint = request.args.get("endpoint")
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    since_raw = request.args.get("since")
    until_raw = request.args.get("until")

    if limit_raw is None:
        limit = LIST_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            return jsonify({"error": "Query parameter 'limit' must be an integer"}), 400
        if limit < 1 or limit > LIST_MAX_LIMIT:
            return jsonify({
                "error": f"Query parameter 'limit' must be between 1 and {LIST_MAX_LIMIT}"
            }), 400

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            return jsonify({"error": "Query parameter 'offset' must be an integer"}), 400
        if offset < 0:
            return jsonify({"error": "Query parameter 'offset' must be non-negative"}), 400

    since = until = None
    try:
        if since_raw is not None:
            since = _parse_iso8601_arg(since_raw, "since")
        if until_raw is not None:
            until = _parse_iso8601_arg(until_raw, "until")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if since is not None and until is not None and until < since:
        return jsonify({"error": "Query parameter 'until' must be greater than or equal to 'since'"}), 400

    filtered = health_records
    if endpoint:
        filtered = [r for r in filtered if r["endpoint"] == endpoint]
    if since is not None or until is not None:
        narrowed = []
        for r in filtered:
            checked_at = _record_checked_at(r)
            if checked_at is None:
                continue
            if since is not None and checked_at < since:
                continue
            if until is not None and checked_at > until:
                continue
            narrowed.append(r)
        filtered = narrowed

    total = len(filtered)
    result = filtered[offset:offset + limit]
    logger.info(
        "Listed %d records (filter=%s, limit=%d, offset=%d, total=%d)",
        len(result), endpoint, limit, offset, total,
    )
    return jsonify({
        "records": result,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@app.route("/api/v1/records", methods=["DELETE"])
def delete_records():
    endpoint = request.args.get("endpoint")
    if not endpoint:
        logger.warning("Delete request missing endpoint parameter")
        return jsonify({"error": "Query parameter 'endpoint' is required"}), 400

    before_count = len(health_records)
    health_records[:] = [r for r in health_records if r["endpoint"] != endpoint]
    deleted_count = before_count - len(health_records)

    if deleted_count == 0:
        logger.info("No records found for deletion: %s", endpoint)
        return jsonify({"error": "No records found for the specified endpoint"}), 404

    logger.info("Deleted %d records for endpoint=%s", deleted_count, endpoint)
    return jsonify({"message": "Records deleted", "deleted_count": deleted_count})


@app.route("/api/v1/report", methods=["GET"])
def report():
    endpoint_filter = request.args.get("endpoint")
    since_raw = request.args.get("since")
    until_raw = request.args.get("until")

    since = until = None
    try:
        if since_raw is not None:
            since = _parse_iso8601_arg(since_raw, "since")
        if until_raw is not None:
            until = _parse_iso8601_arg(until_raw, "until")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if since is not None and until is not None and until < since:
        return jsonify({"error": "Query parameter 'until' must be greater than or equal to 'since'"}), 400

    filtered = health_records
    if endpoint_filter:
        filtered = [r for r in filtered if r["endpoint"] == endpoint_filter]
    if since is not None or until is not None:
        narrowed = []
        for r in filtered:
            checked_at = _record_checked_at(r)
            if checked_at is None:
                continue
            if since is not None and checked_at < since:
                continue
            if until is not None and checked_at > until:
                continue
            narrowed.append(r)
        filtered = narrowed

    if not filtered:
        return jsonify({"message": "No records available", "endpoints": {}})

    endpoints: dict[str, dict] = {}
    for r in filtered:
        ep = r["endpoint"]
        if ep not in endpoints:
            endpoints[ep] = {
                "total_checks": 0,
                "healthy_checks": 0,
                "total_response_time_ms": 0.0,
                "min_response_time_ms": float("inf"),
                "max_response_time_ms": 0.0,
            }
        stats = endpoints[ep]
        stats["total_checks"] += 1
        if r["healthy"]:
            stats["healthy_checks"] += 1
        stats["total_response_time_ms"] += r["response_time_ms"]
        stats["min_response_time_ms"] = min(stats["min_response_time_ms"], r["response_time_ms"])
        stats["max_response_time_ms"] = max(stats["max_response_time_ms"], r["response_time_ms"])

    report_data: dict[str, dict] = {}
    for ep, stats in endpoints.items():
        total = stats["total_checks"]
        report_data[ep] = {
            "total_checks": total,
            "healthy_checks": stats["healthy_checks"],
            "uptime_percent": round(stats["healthy_checks"] / total * 100, 2) if total > 0 else 0,
            "avg_response_time_ms": round(stats["total_response_time_ms"] / total, 2) if total > 0 else 0,
            "min_response_time_ms": round(stats["min_response_time_ms"], 2),
            "max_response_time_ms": round(stats["max_response_time_ms"], 2),
        }

    logger.info("Generated report for %d endpoints", len(report_data))
    return jsonify({"endpoints": report_data})


if __name__ == "__main__":
    logger.info("Starting Analytics Service on port %d", PORT)
    app.run(host="0.0.0.0", port=PORT)
