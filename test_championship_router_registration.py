"""Regression coverage for the shipped RC2 Championship route assembly."""

from fastapi.testclient import TestClient

from api.main_rc2 import app


EXPECTED = {
    ("GET", "/league/{league_id}/championship"),
    ("GET", "/league/{league_id}/championship/config"),
    ("PUT", "/league/{league_id}/championship/config"),
    ("POST", "/league/{league_id}/championship/activate"),
    ("POST", "/league/{league_id}/championship/freeze"),
    ("GET", "/league/{league_id}/championship/corrections"),
    ("POST", "/league/{league_id}/championship/corrections"),
    ("POST", "/league/{league_id}/championship/settle"),
    ("GET", "/league/{league_id}/championship/results"),
}


def _registered_championship_operations():
    return [
        (method, route.path)
        for route in app.routes
        if route.path.startswith("/league/{league_id}/championship")
        for method in route.methods
        if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    ]


def test_shipped_app_mounts_each_championship_operation_once():
    operations = _registered_championship_operations()
    assert set(operations) == EXPECTED
    assert len(operations) == len(EXPECTED)


def test_openapi_exposes_each_championship_operation_once():
    schema = app.openapi()
    operations = {
        (method.upper(), path)
        for path, item in schema["paths"].items()
        if path.startswith("/league/{league_id}/championship")
        for method in item
    }
    assert operations == EXPECTED


def test_unauthenticated_championship_reads_and_writes_remain_protected():
    client = TestClient(app)
    requests = [
        ("GET", "/league/1/championship"),
        ("GET", "/league/1/championship/config"),
        ("GET", "/league/1/championship/corrections"),
        ("GET", "/league/1/championship/results"),
        ("PUT", "/league/1/championship/config"),
        ("POST", "/league/1/championship/activate"),
        ("POST", "/league/1/championship/freeze"),
        ("POST", "/league/1/championship/corrections"),
        ("POST", "/league/1/championship/settle"),
    ]
    for method, path in requests:
        response = client.request(method, path, json={})
        assert response.status_code == 401, (method, path, response.text)
