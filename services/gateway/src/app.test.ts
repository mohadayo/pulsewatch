import request from "supertest";
import { app } from "./app";
import http from "http";

describe("Gateway Service", () => {
  describe("GET /health", () => {
    it("should return health status", async () => {
      const res = await request(app).get("/health");
      expect(res.status).toBe(200);
      expect(res.body.status).toBe("ok");
      expect(res.body.service).toBe("gateway");
      expect(res.body.uptime_seconds).toBeGreaterThanOrEqual(0);
    });
  });

  describe("POST /api/v1/endpoints", () => {
    it("should reject missing url", async () => {
      const res = await request(app)
        .post("/api/v1/endpoints")
        .send({ name: "test" });
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("url");
    });
  });

  describe("DELETE /api/v1/endpoints", () => {
    it("should reject missing url", async () => {
      const res = await request(app)
        .delete("/api/v1/endpoints")
        .send({});
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("url");
    });
  });

  describe("POST /api/v1/check", () => {
    it("should reject missing url", async () => {
      const res = await request(app)
        .post("/api/v1/check")
        .send({});
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("url");
    });
  });

  describe("GET /api/v1/status", () => {
    it("should return degraded when services are down", async () => {
      const res = await request(app).get("/api/v1/status");
      expect(res.status).toBe(200);
      expect(res.body.overall).toBe("degraded");
      expect(res.body.services).toBeDefined();
      expect(res.body.services.checker.healthy).toBe(false);
      expect(res.body.services.analytics.healthy).toBe(false);
    });
  });

  describe("proxy to checker service", () => {
    let mockChecker: http.Server;
    const originalEnv = process.env.CHECKER_URL;

    beforeAll((done) => {
      mockChecker = http
        .createServer((req, res) => {
          res.setHeader("Content-Type", "application/json");

          if (req.method === "GET" && req.url === "/api/v1/endpoints") {
            res.writeHead(200);
            res.end(JSON.stringify({ endpoints: [], total: 0 }));
          } else if (req.method === "POST" && req.url === "/api/v1/endpoints") {
            let body = "";
            req.on("data", (chunk) => (body += chunk));
            req.on("end", () => {
              const data = JSON.parse(body);
              res.writeHead(201);
              res.end(JSON.stringify(data));
            });
          } else if (req.method === "DELETE" && req.url === "/api/v1/endpoints") {
            let body = "";
            req.on("data", (chunk) => (body += chunk));
            req.on("end", () => {
              const data = JSON.parse(body);
              if (data.url === "https://exists.com") {
                res.writeHead(200);
                res.end(JSON.stringify({ message: "endpoint removed" }));
              } else {
                res.writeHead(404);
                res.end(JSON.stringify({ error: "endpoint not found" }));
              }
            });
          } else if (req.method === "POST" && req.url === "/api/v1/check-all") {
            res.writeHead(200);
            res.end(JSON.stringify({ results: [], total: 0, reported: 0 }));
          } else if (req.url === "/health") {
            res.writeHead(200);
            res.end(JSON.stringify({ status: "ok", service: "checker" }));
          } else {
            res.writeHead(404);
            res.end(JSON.stringify({ error: "not found" }));
          }
        })
        .listen(0, () => {
          const addr = mockChecker.address();
          if (addr && typeof addr !== "string") {
            process.env.CHECKER_URL = `http://127.0.0.1:${addr.port}`;
          }
          done();
        });
    });

    afterAll((done) => {
      process.env.CHECKER_URL = originalEnv;
      mockChecker.close(done);
    });

    it("should proxy GET /api/v1/endpoints", async () => {
      const res = await request(app).get("/api/v1/endpoints");
      expect(res.status).toBe(200);
      expect(res.body.endpoints).toEqual([]);
    });

    it("should proxy POST /api/v1/endpoints", async () => {
      const res = await request(app)
        .post("/api/v1/endpoints")
        .send({ url: "https://example.com", name: "Example" });
      expect(res.status).toBe(201);
      expect(res.body.url).toBe("https://example.com");
    });

    it("should proxy DELETE /api/v1/endpoints (success)", async () => {
      const res = await request(app)
        .delete("/api/v1/endpoints")
        .send({ url: "https://exists.com" });
      expect(res.status).toBe(200);
      expect(res.body.message).toBe("endpoint removed");
    });

    it("should proxy DELETE /api/v1/endpoints (not found)", async () => {
      const res = await request(app)
        .delete("/api/v1/endpoints")
        .send({ url: "https://nonexistent.com" });
      expect(res.status).toBe(404);
      expect(res.body.error).toBe("endpoint not found");
    });

    it("should proxy POST /api/v1/check-all", async () => {
      const res = await request(app).post("/api/v1/check-all");
      expect(res.status).toBe(200);
      expect(res.body.results).toEqual([]);
    });
  });

  describe("proxy to analytics service", () => {
    let mockAnalytics: http.Server;
    const originalEnv = process.env.ANALYTICS_URL;

    beforeAll((done) => {
      mockAnalytics = http
        .createServer((req, res) => {
          res.setHeader("Content-Type", "application/json");

          if (req.method === "GET" && req.url?.startsWith("/api/v1/records")) {
            res.writeHead(200);
            res.end(JSON.stringify({ records: [], total: 0 }));
          } else if (req.method === "POST" && req.url === "/api/v1/records") {
            let body = "";
            req.on("data", (chunk) => (body += chunk));
            req.on("end", () => {
              const data = JSON.parse(body);
              res.writeHead(201);
              res.end(
                JSON.stringify({
                  endpoint: data.endpoint,
                  status_code: data.status_code,
                  response_time_ms: data.response_time_ms,
                  healthy: data.status_code >= 200 && data.status_code < 400,
                  checked_at: "2026-01-01T00:00:00+00:00",
                })
              );
            });
          } else if (req.method === "DELETE" && req.url === "/api/v1/records") {
            let body = "";
            req.on("data", (chunk) => (body += chunk));
            req.on("end", () => {
              const data = JSON.parse(body);
              if (data.endpoint === "https://example.com") {
                res.writeHead(200);
                res.end(JSON.stringify({ message: "deleted", deleted: 3 }));
              } else {
                res.writeHead(200);
                res.end(JSON.stringify({ message: "deleted", deleted: 0 }));
              }
            });
          } else if (req.method === "GET" && req.url?.startsWith("/api/v1/report")) {
            res.writeHead(200);
            res.end(
              JSON.stringify({ endpoints: {}, forwarded_query: req.url.split("?")[1] || "" })
            );
          } else if (req.url === "/health") {
            res.writeHead(200);
            res.end(JSON.stringify({ status: "ok", service: "analytics" }));
          } else {
            res.writeHead(404);
            res.end(JSON.stringify({ error: "not found" }));
          }
        })
        .listen(0, () => {
          const addr = mockAnalytics.address();
          if (addr && typeof addr !== "string") {
            process.env.ANALYTICS_URL = `http://127.0.0.1:${addr.port}`;
          }
          done();
        });
    });

    afterAll((done) => {
      process.env.ANALYTICS_URL = originalEnv;
      mockAnalytics.close(done);
    });

    it("should proxy GET /api/v1/records", async () => {
      const res = await request(app).get("/api/v1/records");
      expect(res.status).toBe(200);
      expect(res.body.records).toEqual([]);
    });

    it("should proxy GET /api/v1/records with query params", async () => {
      const res = await request(app).get("/api/v1/records?endpoint=test&limit=5");
      expect(res.status).toBe(200);
      expect(res.body.records).toEqual([]);
    });

    it("should proxy POST /api/v1/records", async () => {
      const res = await request(app)
        .post("/api/v1/records")
        .send({
          endpoint: "https://example.com",
          status_code: 200,
          response_time_ms: 42.0,
        });
      expect(res.status).toBe(201);
      expect(res.body.endpoint).toBe("https://example.com");
      expect(res.body.status_code).toBe(200);
      expect(res.body.healthy).toBe(true);
    });

    it("should reject POST /api/v1/records missing endpoint", async () => {
      const res = await request(app)
        .post("/api/v1/records")
        .send({ status_code: 200, response_time_ms: 1 });
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("endpoint");
    });

    it("should reject POST /api/v1/records missing status_code", async () => {
      const res = await request(app)
        .post("/api/v1/records")
        .send({ endpoint: "https://example.com", response_time_ms: 1 });
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("status_code");
    });

    it("should reject POST /api/v1/records missing response_time_ms", async () => {
      const res = await request(app)
        .post("/api/v1/records")
        .send({ endpoint: "https://example.com", status_code: 200 });
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("response_time_ms");
    });

    it("should accept POST /api/v1/records with status_code=0", async () => {
      const res = await request(app)
        .post("/api/v1/records")
        .send({
          endpoint: "https://example.com",
          status_code: 0,
          response_time_ms: 0,
        });
      // status_code=0 should not be treated as missing (truthy-falsy guard handled by !== undefined)
      expect(res.status).not.toBe(400);
    });

    it("should reject DELETE /api/v1/records with no filters", async () => {
      const res = await request(app)
        .delete("/api/v1/records")
        .send({});
      expect(res.status).toBe(400);
      expect(res.body.error).toContain("endpoint");
      expect(res.body.error).toContain("since");
      expect(res.body.error).toContain("until");
    });

    it("should treat empty string field as missing", async () => {
      const res = await request(app)
        .delete("/api/v1/records")
        .send({ endpoint: "" });
      expect(res.status).toBe(400);
    });

    it("should proxy DELETE /api/v1/records by endpoint", async () => {
      const res = await request(app)
        .delete("/api/v1/records")
        .send({ endpoint: "https://example.com" });
      expect(res.status).toBe(200);
      expect(res.body.deleted).toBe(3);
    });

    it("should proxy DELETE /api/v1/records by until", async () => {
      const res = await request(app)
        .delete("/api/v1/records")
        .send({ until: "2025-01-01T00:00:00Z" });
      expect(res.status).toBe(200);
    });

    it("should proxy DELETE /api/v1/records by status_code", async () => {
      const res = await request(app)
        .delete("/api/v1/records")
        .send({ status_code: 500 });
      expect(res.status).toBe(200);
    });

    it("should proxy DELETE /api/v1/records by healthy", async () => {
      const res = await request(app)
        .delete("/api/v1/records")
        .send({ healthy: false });
      expect(res.status).toBe(200);
    });

    it("should proxy GET /api/v1/report", async () => {
      const res = await request(app).get("/api/v1/report");
      expect(res.status).toBe(200);
      expect(res.body.endpoints).toEqual({});
      expect(res.body.forwarded_query).toBe("");
    });

    it("should proxy GET /api/v1/report with query params", async () => {
      const res = await request(app).get(
        "/api/v1/report?endpoint=https%3A%2F%2Fa.example.com%2Fh&since=2026-01-01T00%3A00%3A00Z"
      );
      expect(res.status).toBe(200);
      expect(res.body.forwarded_query).toContain("endpoint=https%3A%2F%2Fa.example.com%2Fh");
      expect(res.body.forwarded_query).toContain("since=2026-01-01T00%3A00%3A00Z");
    });
  });

  describe("proxy timeout", () => {
    let slowServer: http.Server;
    const originalEnv = process.env.CHECKER_URL;
    const originalTimeout = process.env.PROXY_TIMEOUT_MS;

    beforeAll((done) => {
      process.env.PROXY_TIMEOUT_MS = "200";
      slowServer = http
        .createServer((_req, res) => {
          setTimeout(() => {
            res.setHeader("Content-Type", "application/json");
            res.writeHead(200);
            res.end(JSON.stringify({ endpoints: [], total: 0 }));
          }, 2000);
        })
        .listen(0, () => {
          const addr = slowServer.address();
          if (addr && typeof addr !== "string") {
            process.env.CHECKER_URL = `http://127.0.0.1:${addr.port}`;
          }
          done();
        });
    });

    afterAll((done) => {
      process.env.CHECKER_URL = originalEnv;
      process.env.PROXY_TIMEOUT_MS = originalTimeout;
      slowServer.close(done);
    });

    it("should return 504 when upstream times out", async () => {
      const res = await request(app).get("/api/v1/endpoints");
      expect(res.status).toBe(504);
      expect(res.body.error).toBe("Gateway timeout");
    }, 10000);
  });
});
