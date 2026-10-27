import importlib.util
from pathlib import Path
import httpx
from fastapi.testclient import TestClient

from test_gateway import module as mod

def fake_order(request):
    if request.method == 'POST' and request.url.path == '/orders':
        return httpx.Response(202, json={'id':'order-123','status':'PENDING'})
    if request.url.path == '/orders/order-123':
        return httpx.Response(200, json={'id':'order-123','status':'PENDING'})
    return httpx.Response(404, json={'detail':'not found'})


def test_order_routes_and_metrics():
    with TestClient(mod.app) as client:
        mod.app.state.order_client = httpx.AsyncClient(base_url='http://order:8002',
                                                        transport=httpx.MockTransport(fake_order))
        assert client.post('/orders', json={'customer_id':'a'}).status_code == 202
        assert client.get('/orders/order-123').json()['status'] == 'PENDING'
        assert client.get('/orders/missing').status_code == 404
        txt = client.get('/metrics').text
        assert 'endpoint="/orders"' in txt
        assert 'http_status="202"' in txt


def test_broker_proxy_failure():
    def unavailable(request):
        raise httpx.ConnectError('fail', request=request)
    with TestClient(mod.app) as client:
        mod.app.state.order_client = httpx.AsyncClient(base_url='http://order:8002',
                                                        transport=httpx.MockTransport(unavailable))
        assert client.post('/orders', json={'customer_id':'a'}).status_code == 502
