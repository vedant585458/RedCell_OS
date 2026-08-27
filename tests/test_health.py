"""Unit tests for the backend health check endpoint."""

from app.main import create_app
from fastapi.testclient import TestClient


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["app_name"] == "RedCell_OS"
    assert "timestamp_utc" in data
    assert "environment" in data


def test_api_v1_health_endpoint():
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
