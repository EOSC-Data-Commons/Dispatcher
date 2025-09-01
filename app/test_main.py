from fastapi.testclient import TestClient

from .main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "API running"}

def test_read_config():
    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == app.config.config
