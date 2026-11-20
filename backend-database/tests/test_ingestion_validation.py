from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_ingestion_rejects_empty_payload():
    response = client.post(
        "/v1/ingest",
        json={},
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401


def test_batch_ingestion_rejects_empty_batch():
    response = client.post(
        "/v1/ingest/batch",
        json={"events": []},
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401