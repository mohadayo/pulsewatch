import express, { Request, Response, NextFunction } from "express";

const app = express();
app.use(express.json());

function checkerUrl(): string {
  return process.env.CHECKER_URL || "http://localhost:8080";
}
function analyticsUrl(): string {
  return process.env.ANALYTICS_URL || "http://localhost:5000";
}
function proxyTimeoutMs(): number {
  return parseInt(process.env.PROXY_TIMEOUT_MS || "10000", 10);
}
const startTime = Date.now();

const logger = {
  info: (msg: string, ...args: unknown[]) =>
    console.log(`${new Date().toISOString()} [INFO] gateway: ${msg}`, ...args),
  warn: (msg: string, ...args: unknown[]) =>
    console.warn(`${new Date().toISOString()} [WARN] gateway: ${msg}`, ...args),
  error: (msg: string, ...args: unknown[]) =>
    console.error(`${new Date().toISOString()} [ERROR] gateway: ${msg}`, ...args),
};

async function proxyRequest(
  baseUrl: string,
  path: string,
  method: string,
  body?: unknown
): Promise<{ status: number; data: unknown }> {
  const url = `${baseUrl}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), proxyTimeoutMs());

  const options: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
    signal: controller.signal,
  };
  if (body && method !== "GET") {
    options.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(url, options);
    const data = await response.json();
    return { status: response.status, data };
  } finally {
    clearTimeout(timeout);
  }
}

// Health check
app.get("/health", (_req: Request, res: Response) => {
  const uptimeSeconds = (Date.now() - startTime) / 1000;
  res.json({ status: "ok", service: "gateway", uptime_seconds: Number(uptimeSeconds.toFixed(2)) });
});

// Service status - aggregate health from all services
app.get("/api/v1/status", async (_req: Request, res: Response) => {
  const services: Record<string, unknown> = {};

  try {
    const checker = await proxyRequest(checkerUrl(), "/health", "GET");
    services.checker = { healthy: true, ...checker.data as object };
  } catch {
    services.checker = { healthy: false, error: "unreachable" };
  }

  try {
    const analytics = await proxyRequest(analyticsUrl(), "/health", "GET");
    services.analytics = { healthy: true, ...analytics.data as object };
  } catch {
    services.analytics = { healthy: false, error: "unreachable" };
  }

  const allHealthy = Object.values(services).every(
    (s) => (s as Record<string, unknown>).healthy === true
  );

  logger.info(`Status check: all_healthy=${allHealthy}`);
  res.json({ overall: allHealthy ? "healthy" : "degraded", services });
});

// Endpoints CRUD - proxy to checker
app.get("/api/v1/endpoints", async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await proxyRequest(checkerUrl(), "/api/v1/endpoints", "GET");
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

app.post("/api/v1/endpoints", async (req: Request, res: Response, next: NextFunction) => {
  try {
    if (!req.body.url) {
      res.status(400).json({ error: "Field 'url' is required" });
      return;
    }
    const result = await proxyRequest(checkerUrl(), "/api/v1/endpoints", "POST", req.body);
    logger.info(`Registered endpoint: ${req.body.url}`);
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

app.delete("/api/v1/endpoints", async (req: Request, res: Response, next: NextFunction) => {
  try {
    if (!req.body.url) {
      res.status(400).json({ error: "Field 'url' is required" });
      return;
    }
    const result = await proxyRequest(checkerUrl(), "/api/v1/endpoints", "DELETE", req.body);
    logger.info(`Removed endpoint: ${req.body.url}`);
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

// Health check operations - proxy to checker
app.post("/api/v1/check", async (req: Request, res: Response, next: NextFunction) => {
  try {
    if (!req.body.url) {
      res.status(400).json({ error: "Field 'url' is required" });
      return;
    }
    const result = await proxyRequest(checkerUrl(), "/api/v1/check", "POST", req.body);
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

app.post("/api/v1/check-all", async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await proxyRequest(checkerUrl(), "/api/v1/check-all", "POST");
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

// Analytics - proxy to analytics service
app.get("/api/v1/records", async (req: Request, res: Response, next: NextFunction) => {
  try {
    const query = req.url.split("?")[1] || "";
    const path = query ? `/api/v1/records?${query}` : "/api/v1/records";
    const result = await proxyRequest(analyticsUrl(), path, "GET");
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

const DELETE_FILTER_FIELDS = [
  "endpoint",
  "since",
  "until",
  "status_code",
  "healthy",
] as const;

app.delete("/api/v1/records", async (req: Request, res: Response, next: NextFunction) => {
  try {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const hasAnyFilter = DELETE_FILTER_FIELDS.some(
      (field) => body[field] !== undefined && body[field] !== null && body[field] !== "",
    );
    if (!hasAnyFilter) {
      res.status(400).json({
        error: `At least one of: ${DELETE_FILTER_FIELDS.join(", ")} is required`,
      });
      return;
    }
    const result = await proxyRequest(analyticsUrl(), "/api/v1/records", "DELETE", body);
    const summary = DELETE_FILTER_FIELDS
      .filter((f) => body[f] !== undefined && body[f] !== null && body[f] !== "")
      .map((f) => `${f}=${String(body[f])}`)
      .join(", ");
    logger.info(`Deleted records with filters: ${summary}`);
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

app.get("/api/v1/report", async (req: Request, res: Response, next: NextFunction) => {
  try {
    const query = req.url.split("?")[1] || "";
    const path = query ? `/api/v1/report?${query}` : "/api/v1/report";
    const result = await proxyRequest(analyticsUrl(), path, "GET");
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

// Error handler
app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
  if (err.name === "AbortError") {
    logger.error(`Proxy timeout: ${err.message}`);
    res.status(504).json({ error: "Gateway timeout", message: "Upstream service did not respond in time" });
    return;
  }
  logger.error(`Unhandled error: ${err.message}`);
  res.status(502).json({ error: "Service unavailable", message: err.message });
});

export { app, proxyRequest };
