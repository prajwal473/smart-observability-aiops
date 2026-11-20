from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_ingestion_without_token():
    response = client.post("/v1/ingest", json={})

    assert response.status_code == 401


def test_ingestion_with_invalid_token():
    response = client.post(
        "/v1/ingest",
        json={},
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401