"""PulseWatch Analytics Service - Processes health check data and generates reports."""

import logging
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

# In-memory store for health check results
health_records: list[dict] = []
start_time = time.time()


@app.route("/health")
def health():
    uptime = time.time() - start_time
    return jsonify({"status": "ok", "service": "analytics", "uptime_seconds": round(uptime, 2)})


@app.route("/api/v1/records", methods=["POST"])
def add_record():
    data = request.get_json()
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

    try:
        status_code = int(status_code)
    except (ValueError, TypeError):
        return jsonify({"error": "Field 'status_code' must be an integer"}), 400

    try:
        response_time_ms = float(response_time_ms)
    except (ValueError, TypeError):
        return jsonify({"error": "Field 'response_time_ms' must be a number"}), 400

    if response_time_ms < 0:
        return jsonify({"error": "Field 'response_time_ms' must be non-negative"}), 400

    record = {
        "endpoint": endpoint,
        "status_code": status_code,
        "response_time_ms": response_time_ms,
        "checked_at": data.get("checked_at", datetime.now(timezone.utc).isoformat()),
        "healthy": 200 <= status_code < 400,
    }
    health_records.append(record)
    logger.info(
        "Recorded health check for %s: status=%d, time=%.1fms",
        endpoint, record["status_code"], record["response_time_ms"]
    )
    return jsonify(record), 201


@app.route("/api/v1/records", methods=["GET"])
def list_records():
    endpoint = request.args.get("endpoint")
    limit = request.args.get("limit", 100, type=int)

    filtered = health_records
    if endpoint:
        filtered = [r for r in filtered if r["endpoint"] == endpoint]

    result = filtered[-limit:]
    logger.info("Listed %d records (filter=%s, limit=%d)", len(result), endpoint, limit)
    return jsonify({"records": result, "total": len(filtered)})


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
    if not health_records:
        return jsonify({"message": "No records available", "endpoints": {}})

    endpoints: dict[str, dict] = {}
    for r in health_records:
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
