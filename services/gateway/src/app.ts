import express, { Request, Response, NextFunction } from "express";

const app = express();
app.use(express.json());

function checkerUrl(): string {
  return process.env.CHECKER_URL || "http://localhost:8080";
}
function analyticsUrl(): string {
  return process.env.ANALYTICS_URL || "http://localhost:5000";
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
  const options: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body && method !== "GET") {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  const data = await response.json();
  return { status: response.status, data };
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

app.get("/api/v1/report", async (_req: Request, res: Response, next: NextFunction) => {
  try {
    const result = await proxyRequest(analyticsUrl(), "/api/v1/report", "GET");
    res.status(result.status).json(result.data);
  } catch (err) {
    next(err);
  }
});

// Error handler
app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
  logger.error(`Unhandled error: ${err.message}`);
  res.status(502).json({ error: "Service unavailable", message: err.message });
});

export { app, proxyRequest };
