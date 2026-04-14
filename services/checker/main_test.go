package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func setupTestMux() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/api/v1/endpoints", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			listEndpointsHandler(w, r)
		case http.MethodPost:
			addEndpointHandler(w, r)
		default:
			http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		}
	})
	mux.HandleFunc("/api/v1/check", checkSingleHandler)
	mux.HandleFunc("/api/v1/check-all", checkAllHandler)
	return mux
}

func TestHealthEndpoint(t *testing.T) {
	mux := setupTestMux()
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var resp HealthResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatal(err)
	}
	if resp.Status != "ok" {
		t.Errorf("expected status ok, got %s", resp.Status)
	}
	if resp.Service != "checker" {
		t.Errorf("expected service checker, got %s", resp.Service)
	}
}

func TestAddEndpoint(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	body := `{"url":"https://example.com","name":"Example"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d", w.Code)
	}

	var ep Endpoint
	json.NewDecoder(w.Body).Decode(&ep)
	if ep.URL != "https://example.com" {
		t.Errorf("expected url https://example.com, got %s", ep.URL)
	}
	if ep.Name != "Example" {
		t.Errorf("expected name Example, got %s", ep.Name)
	}

	eps := GetEndpoints()
	if len(eps) != 1 {
		t.Errorf("expected 1 endpoint, got %d", len(eps))
	}
}

func TestAddEndpointDefaultName(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	body := `{"url":"https://test.com"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d", w.Code)
	}

	var ep Endpoint
	json.NewDecoder(w.Body).Decode(&ep)
	if ep.Name != "https://test.com" {
		t.Errorf("expected name to default to URL, got %s", ep.Name)
	}
}

func TestAddEndpointMissingURL(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	body := `{"name":"no-url"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestAddEndpointInvalidJSON(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString("not json"))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestListEndpoints(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	// Add two endpoints
	for _, url := range []string{"https://a.com", "https://b.com"} {
		body := `{"url":"` + url + `"}`
		req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/v1/endpoints", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	json.NewDecoder(w.Body).Decode(&result)
	total := int(result["total"].(float64))
	if total != 2 {
		t.Errorf("expected 2 endpoints, got %d", total)
	}
}

func TestCheckSingleMissingURL(t *testing.T) {
	mux := setupTestMux()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/check", bytes.NewBufferString(`{}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestCheckSingleWithMockServer(t *testing.T) {
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"ok"}`))
	}))
	defer mockServer.Close()

	mux := setupTestMux()
	body := `{"url":"` + mockServer.URL + `"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/check", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result CheckResult
	json.NewDecoder(w.Body).Decode(&result)
	if result.StatusCode != 200 {
		t.Errorf("expected status 200, got %d", result.StatusCode)
	}
	if result.ResponseTimeMs <= 0 {
		t.Error("expected positive response time")
	}
}

func TestCheckAllNoEndpoints(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/check-all", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	json.NewDecoder(w.Body).Decode(&result)
	if result["message"] != "no endpoints registered" {
		t.Errorf("expected no endpoints message, got %v", result["message"])
	}
}

func TestCheckAllWithEndpoints(t *testing.T) {
	ResetEndpoints()

	// Create mock target server
	mockTarget := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer mockTarget.Close()

	// Create mock analytics server
	mockAnalytics := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	}))
	defer mockAnalytics.Close()

	SetAnalyticsURL(mockAnalytics.URL)
	defer SetAnalyticsURL("http://localhost:5000")

	mux := setupTestMux()

	// Register endpoint
	body := `{"url":"` + mockTarget.URL + `"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	// Check all
	req = httptest.NewRequest(http.MethodPost, "/api/v1/check-all", nil)
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	json.NewDecoder(w.Body).Decode(&result)
	total := int(result["total"].(float64))
	if total != 1 {
		t.Errorf("expected 1 result, got %d", total)
	}
	reported := int(result["reported"].(float64))
	if reported != 1 {
		t.Errorf("expected 1 reported, got %d", reported)
	}
}

func TestCheckEndpointFunction(t *testing.T) {
	mockServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer mockServer.Close()

	result := CheckEndpoint(mockServer.URL)
	if result.StatusCode != 200 {
		t.Errorf("expected 200, got %d", result.StatusCode)
	}
	if result.Endpoint != mockServer.URL {
		t.Errorf("expected endpoint %s, got %s", mockServer.URL, result.Endpoint)
	}
}

func TestCheckEndpointUnreachable(t *testing.T) {
	result := CheckEndpoint("http://localhost:19999")
	if result.StatusCode != 0 {
		t.Errorf("expected status 0 for unreachable, got %d", result.StatusCode)
	}
	if result.Error == "" {
		t.Error("expected error message for unreachable endpoint")
	}
}

func TestEndpointsMethodNotAllowed(t *testing.T) {
	mux := setupTestMux()
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/endpoints", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", w.Code)
	}
}

func TestCheckMethodNotAllowed(t *testing.T) {
	mux := setupTestMux()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/check", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", w.Code)
	}
}

func TestParsePort(t *testing.T) {
	p, err := ParsePort("8080")
	if err != nil {
		t.Fatal(err)
	}
	if p != 8080 {
		t.Errorf("expected 8080, got %d", p)
	}

	_, err = ParsePort("abc")
	if err == nil {
		t.Error("expected error for non-numeric port")
	}
}

func TestFormatAddr(t *testing.T) {
	addr := FormatAddr("0.0.0.0", 8080)
	if addr != "0.0.0.0:8080" {
		t.Errorf("expected 0.0.0.0:8080, got %s", addr)
	}
}
