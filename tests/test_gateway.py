import importlib.util
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

path = Path(__file__).resolve().parents[1] / 'api-gateway' / 'main.py'
spec = importlib.util.spec_from_file_location('gateway_main', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def mock_catalog(request: httpx.Request):
    if request.url.path == '/events':
        return httpx.Response(200, json=[{'id': 'evt-101'}])
    if request.url.path == '/events/evt-101':
        return httpx.Response(200, json={'id': 'evt-101'})
    return httpx.Response(404, json={'detail': 'Evento nao encontrado'})

def test_proxy_and_metrics():
    with TestClient(module.app) as client:
        module.app.state.catalog_client = httpx.AsyncClient(
            base_url='http://catalog:8001', transport=httpx.MockTransport(mock_catalog)
        )
        assert client.get('/events').json() == [{'id':'evt-101'}]
        assert client.get('/events/evt-101').json()['id'] == 'evt-101'
        assert client.get('/events/unknown').status_code == 404
        metrics = client.get('/metrics').text
        assert 'gateway_requests_total' in metrics
        assert 'gateway_request_duration_seconds_bucket' in metrics
        assert 'http_status="404"' in metrics

def test_catalog_unavailable_yields_502():
    def unavailable(request):
        raise httpx.ConnectError('Falha simulada', request=request)
    with TestClient(module.app) as client:
        module.app.state.catalog_client = httpx.AsyncClient(
            base_url='http://catalog:8001', transport=httpx.MockTransport(unavailable)
        )
        assert client.get('/events').status_code == 502
