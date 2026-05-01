// Package main implements the PulseWatch Checker Service.
// It performs health checks on registered endpoints and reports results to the Analytics service.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"sync"
	"time"
)

var (
	port         string
	analyticsURL string
	logger       *log.Logger
	startTime    time.Time

	mu        sync.RWMutex
	endpoints []Endpoint

	reportTimeout = 5 * time.Second
)

// Endpoint represents a monitored URL.
type Endpoint struct {
	URL  string `json:"url"`
	Name string `json:"name"`
}

// HealthResponse is returned by /health.
type HealthResponse struct {
	Status        string  `json:"status"`
	Service       string  `json:"service"`
	UptimeSeconds float64 `json:"uptime_seconds"`
}

// CheckResult is the result of a health check.
type CheckResult struct {
	Endpoint       string  `json:"endpoint"`
	StatusCode     int     `json:"status_code"`
	ResponseTimeMs float64 `json:"response_time_ms"`
	CheckedAt      string  `json:"checked_at"`
	Error          string  `json:"error,omitempty"`
}

func init() {
	logger = log.New(os.Stdout, "[checker] ", log.LstdFlags|log.Lmsgprefix)
	port = getEnv("CHECKER_PORT", "8080")
	analyticsURL = getEnv("ANALYTICS_URL", "http://localhost:5000")
	startTime = time.Now()
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	uptime := time.Since(startTime).Seconds()
	resp := HealthResponse{
		Status:        "ok",
		Service:       "checker",
		UptimeSeconds: uptime,
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func listEndpointsHandler(w http.ResponseWriter, r *http.Request) {
	mu.RLock()
	defer mu.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"endpoints": endpoints,
		"total":     len(endpoints),
	})
}

func addEndpointHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var ep Endpoint
	if err := json.NewDecoder(r.Body).Decode(&ep); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "invalid JSON body"})
		return
	}

	if ep.URL == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "field 'url' is required"})
		return
	}

	parsed, err := url.ParseRequestURI(ep.URL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "field 'url' must be a valid HTTP or HTTPS URL"})
		return
	}

	if ep.Name == "" {
		ep.Name = ep.URL
	}

	mu.Lock()
	for _, existing := range endpoints {
		if existing.URL == ep.URL {
			mu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusConflict)
			json.NewEncoder(w).Encode(map[string]string{"error": "endpoint already registered"})
			return
		}
	}
	endpoints = append(endpoints, ep)
	mu.Unlock()

	logger.Printf("Registered endpoint: %s (%s)", ep.Name, ep.URL)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(ep)
}

func deleteEndpointHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodDelete {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var body struct {
		URL string `json:"url"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.URL == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "field 'url' is required"})
		return
	}

	mu.Lock()
	found := false
	for i, ep := range endpoints {
		if ep.URL == body.URL {
			endpoints = append(endpoints[:i], endpoints[i+1:]...)
			found = true
			logger.Printf("Removed endpoint: %s (%s)", ep.Name, ep.URL)
			break
		}
	}
	mu.Unlock()

	if !found {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{"error": "endpoint not found"})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"message": "endpoint removed"})
}

// CheckEndpoint performs a health check on a single URL.
func CheckEndpoint(url string) CheckResult {
	start := time.Now()
	result := CheckResult{
		Endpoint:  url,
		CheckedAt: time.Now().UTC().Format(time.RFC3339),
	}

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Get(url)
	elapsed := time.Since(start).Seconds() * 1000

	result.ResponseTimeMs = elapsed

	if err != nil {
		result.StatusCode = 0
		result.Error = err.Error()
		logger.Printf("Check FAILED for %s: %v (%.1fms)", url, err, elapsed)
		return result
	}
	defer resp.Body.Close()

	result.StatusCode = resp.StatusCode
	logger.Printf("Check OK for %s: status=%d (%.1fms)", url, resp.StatusCode, elapsed)
	return result
}

func checkAllHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	mu.RLock()
	eps := make([]Endpoint, len(endpoints))
	copy(eps, endpoints)
	mu.RUnlock()

	if len(eps) == 0 {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"message": "no endpoints registered",
			"results": []CheckResult{},
		})
		return
	}

	results := make([]CheckResult, len(eps))
	var wg sync.WaitGroup
	for i, ep := range eps {
		wg.Add(1)
		go func(idx int, url string) {
			defer wg.Done()
			results[idx] = CheckEndpoint(url)
		}(i, ep.URL)
	}
	wg.Wait()

	// Report results to analytics service
	reported := 0
	for _, result := range results {
		if reportToAnalytics(result) {
			reported++
		}
	}
	logger.Printf("Checked %d endpoints, reported %d to analytics", len(results), reported)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"results":  results,
		"total":    len(results),
		"reported": reported,
	})
}

func reportToAnalytics(result CheckResult) bool {
	payload := map[string]interface{}{
		"endpoint":         result.Endpoint,
		"status_code":      result.StatusCode,
		"response_time_ms": result.ResponseTimeMs,
		"checked_at":       result.CheckedAt,
	}
	body, _ := json.Marshal(payload)

	client := &http.Client{Timeout: reportTimeout}
	resp, err := client.Post(analyticsURL+"/api/v1/records", "application/json", bytes.NewReader(body))
	if err != nil {
		logger.Printf("Failed to report to analytics: %v", err)
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == 201
}

func checkSingleHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var body struct {
		URL string `json:"url"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.URL == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		json.NewEncoder(w).Encode(map[string]string{"error": "field 'url' is required"})
		return
	}

	result := CheckEndpoint(body.URL)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/api/v1/endpoints", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			listEndpointsHandler(w, r)
		case http.MethodPost:
			addEndpointHandler(w, r)
		case http.MethodDelete:
			deleteEndpointHandler(w, r)
		default:
			http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/api/v1/check", checkSingleHandler)
	mux.HandleFunc("/api/v1/check-all", checkAllHandler)

	addr := ":" + port
	logger.Printf("Starting Checker Service on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		logger.Fatalf("Server failed: %v", err)
	}
}

// GetEndpoints returns a copy of registered endpoints (for testing).
func GetEndpoints() []Endpoint {
	mu.RLock()
	defer mu.RUnlock()
	result := make([]Endpoint, len(endpoints))
	copy(result, endpoints)
	return result
}

// ResetEndpoints clears all registered endpoints (for testing).
func ResetEndpoints() {
	mu.Lock()
	endpoints = nil
	mu.Unlock()
}

// GetPort returns the configured port.
func GetPort() string {
	return port
}

// SetPort sets the port (for testing).
func SetPort(p string) {
	port = p
}

// GetAnalyticsURL returns the configured analytics URL.
func GetAnalyticsURL() string {
	return analyticsURL
}

// SetAnalyticsURL sets the analytics URL (for testing).
func SetAnalyticsURL(u string) {
	analyticsURL = u
}

// SetReportTimeout sets the report timeout (for testing).
func SetReportTimeout(d time.Duration) {
	reportTimeout = d
}

// ParsePort converts port string to int safely.
func ParsePort(p string) (int, error) {
	return strconv.Atoi(p)
}

// FormatAddr creates an address string from host and port.
func FormatAddr(host string, portNum int) string {
	return fmt.Sprintf("%s:%d", host, portNum)
}
