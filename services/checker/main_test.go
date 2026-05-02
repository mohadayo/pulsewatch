package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
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
		case http.MethodDelete:
			deleteEndpointHandler(w, r)
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

func TestDeleteEndpoint(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	// Add an endpoint
	addBody := `{"url":"https://delete-me.com","name":"DeleteMe"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(addBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusCreated {
		t.Fatalf("expected 201 on add, got %d", w.Code)
	}

	// Delete it
	delBody := `{"url":"https://delete-me.com"}`
	req = httptest.NewRequest(http.MethodDelete, "/api/v1/endpoints", bytes.NewBufferString(delBody))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 on delete, got %d", w.Code)
	}

	var result map[string]string
	json.NewDecoder(w.Body).Decode(&result)
	if result["message"] != "endpoint removed" {
		t.Errorf("expected 'endpoint removed', got %s", result["message"])
	}

	eps := GetEndpoints()
	if len(eps) != 0 {
		t.Errorf("expected 0 endpoints after delete, got %d", len(eps))
	}
}

func TestDeleteEndpointNotFound(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	body := `{"url":"https://nonexistent.com"}`
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestDeleteEndpointMissingURL(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	req := httptest.NewRequest(http.MethodDelete, "/api/v1/endpoints", bytes.NewBufferString(`{}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestDeleteEndpointPreservesOthers(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	// Add three endpoints
	for _, url := range []string{"https://a.com", "https://b.com", "https://c.com"} {
		body := `{"url":"` + url + `"}`
		req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
	}

	// Delete the middle one
	delBody := `{"url":"https://b.com"}`
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/endpoints", bytes.NewBufferString(delBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	eps := GetEndpoints()
	if len(eps) != 2 {
		t.Fatalf("expected 2 endpoints, got %d", len(eps))
	}
	for _, ep := range eps {
		if ep.URL == "https://b.com" {
			t.Error("deleted endpoint should not be present")
		}
	}
}

func TestAddEndpointInvalidURL(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	body := `{"url":"not-a-url"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}

	var result map[string]string
	json.NewDecoder(w.Body).Decode(&result)
	if result["error"] != "field 'url' must be a valid HTTP or HTTPS URL" {
		t.Errorf("unexpected error: %s", result["error"])
	}
}

func TestAddEndpointDuplicate(t *testing.T) {
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

	// Try adding the same URL again
	req = httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusConflict {
		t.Fatalf("expected 409 for duplicate, got %d", w.Code)
	}

	eps := GetEndpoints()
	if len(eps) != 1 {
		t.Errorf("expected 1 endpoint, got %d", len(eps))
	}
}

func TestAddEndpointFTPScheme(t *testing.T) {
	ResetEndpoints()
	mux := setupTestMux()

	body := `{"url":"ftp://files.example.com/data"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for ftp URL, got %d", w.Code)
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

func TestCheckSingleInvalidURL(t *testing.T) {
	mux := setupTestMux()

	tests := []struct {
		name string
		url  string
	}{
		{"not a URL", "not-a-url"},
		{"FTP scheme", "ftp://files.example.com/data"},
		{"missing host", "http://"},
		{"file scheme", "file:///etc/passwd"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			body := `{"url":"` + tc.url + `"}`
			req := httptest.NewRequest(http.MethodPost, "/api/v1/check", bytes.NewBufferString(body))
			req.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			mux.ServeHTTP(w, req)

			if w.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for %q, got %d", tc.url, w.Code)
			}

			var result map[string]string
			json.NewDecoder(w.Body).Decode(&result)
			if result["error"] != "field 'url' must be a valid HTTP or HTTPS URL" {
				t.Errorf("unexpected error: %s", result["error"])
			}
		})
	}
}

func TestCheckAllMultipleEndpoints(t *testing.T) {
	ResetEndpoints()

	mockTarget1 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer mockTarget1.Close()

	mockTarget2 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer mockTarget2.Close()

	mockAnalytics := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusCreated)
	}))
	defer mockAnalytics.Close()

	SetAnalyticsURL(mockAnalytics.URL)
	defer SetAnalyticsURL("http://localhost:5000")

	mux := setupTestMux()

	for _, u := range []string{mockTarget1.URL, mockTarget2.URL} {
		body := `{"url":"` + u + `"}`
		req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		if w.Code != http.StatusCreated {
			t.Fatalf("expected 201, got %d", w.Code)
		}
	}

	req := httptest.NewRequest(http.MethodPost, "/api/v1/check-all", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	json.NewDecoder(w.Body).Decode(&result)
	total := int(result["total"].(float64))
	if total != 2 {
		t.Errorf("expected 2 results, got %d", total)
	}
	reported := int(result["reported"].(float64))
	if reported != 2 {
		t.Errorf("expected 2 reported, got %d", reported)
	}
}

func TestCheckAllAnalyticsNon201(t *testing.T) {
	ResetEndpoints()

	mockTarget := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer mockTarget.Close()

	mockAnalytics := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer mockAnalytics.Close()

	SetAnalyticsURL(mockAnalytics.URL)
	defer SetAnalyticsURL("http://localhost:5000")

	mux := setupTestMux()

	body := `{"url":"` + mockTarget.URL + `"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/endpoints", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	req = httptest.NewRequest(http.MethodPost, "/api/v1/check-all", nil)
	w = httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	json.NewDecoder(w.Body).Decode(&result)
	reported := int(result["reported"].(float64))
	if reported != 0 {
		t.Errorf("expected 0 reported when analytics returns 500, got %d", reported)
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
	req := httptest.NewRequest(http.MethodPatch, "/api/v1/endpoints", nil)
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

func TestReportToAnalyticsSuccess(t *testing.T) {
	mockAnalytics := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/records" {
			t.Errorf("expected path /api/v1/records, got %s", r.URL.Path)
		}
		w.WriteHeader(http.StatusCreated)
	}))
	defer mockAnalytics.Close()

	oldURL := GetAnalyticsURL()
	SetAnalyticsURL(mockAnalytics.URL)
	defer SetAnalyticsURL(oldURL)

	result := CheckResult{
		Endpoint:       "https://example.com",
		StatusCode:     200,
		ResponseTimeMs: 42.5,
		CheckedAt:      "2026-01-01T00:00:00Z",
	}
	if !reportToAnalytics(result) {
		t.Error("expected reportToAnalytics to return true")
	}
}

func TestReportToAnalyticsUnreachable(t *testing.T) {
	oldURL := GetAnalyticsURL()
	SetAnalyticsURL("http://localhost:19999")
	defer SetAnalyticsURL(oldURL)

	result := CheckResult{
		Endpoint:   "https://example.com",
		StatusCode: 200,
	}
	if reportToAnalytics(result) {
		t.Error("expected reportToAnalytics to return false for unreachable server")
	}
}

func TestReportToAnalyticsTimeout(t *testing.T) {
	slowServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(200 * time.Millisecond)
		w.WriteHeader(http.StatusCreated)
	}))
	defer slowServer.Close()

	oldURL := GetAnalyticsURL()
	SetAnalyticsURL(slowServer.URL)
	defer SetAnalyticsURL(oldURL)

	SetReportTimeout(50 * time.Millisecond)
	defer SetReportTimeout(5 * time.Second)

	result := CheckResult{
		Endpoint:   "https://example.com",
		StatusCode: 200,
	}
	if reportToAnalytics(result) {
		t.Error("expected reportToAnalytics to return false due to timeout")
	}
}
