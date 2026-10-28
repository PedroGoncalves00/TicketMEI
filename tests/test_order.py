import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

path = Path(__file__).resolve().parents[1] / 'order' / 'main.py'
spec = importlib.util.spec_from_file_location('order_main_test', path)


mod = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {'DISABLE_OUTBOX_PUBLISHER': '1'}):
    spec.loader.exec_module(mod)

def test_order_pending_and_get(tmp_path):
    mod.DB_PATH = tmp_path / 'orders.db'
    with patch.dict(os.environ, {'DISABLE_OUTBOX_PUBLISHER': '1'}):
        with TestClient(mod.app) as client:
            def fake_catalog(request):
                return httpx.Response(200, json={'id': 'evt-101', 'price_eur': 85})
            mock = httpx.AsyncClient(base_url='http://catalog:8001', transport=httpx.MockTransport(fake_catalog))
            mod.app.state.catalog_client = mock
            payload = {'customer_id':'customer-1','event_id':'evt-101','email':'abc@example.com','quantity':2}
            resp = client.post('/orders', json=payload)
            assert resp.status_code == 202, resp.text
            oid = resp.json()['id']
            assert resp.json()['status'] == 'PENDING'
            assert resp.json()['total_amount'] == '170.00'
            assert client.get(f'/orders/{oid}').json()['customer_id'] == 'customer-1'
            assert mod.count_pending() == 1
            assert 'orders_initiated_total' in client.get('/metrics').text
            assert 'orders_outbox_pending' in client.get('/metrics').text


def test_quantity_and_missing_order(tmp_path):
    mod.DB_PATH = tmp_path / 'orders.db'
    with patch.dict(os.environ, {'DISABLE_OUTBOX_PUBLISHER': '1'}):
        with TestClient(mod.app) as client:
            base = {'customer_id':'a','event_id':'evt-101','email':'abc@example.com'}
            assert client.post('/orders', json={**base, 'quantity':0}).status_code == 422
            assert client.post('/orders', json={**base, 'quantity':5}).status_code == 422
            assert client.get('/orders/inexistente').status_code == 404


def test_unknown_event(tmp_path):
    mod.DB_PATH = tmp_path / 'orders.db'
    with patch.dict(os.environ, {'DISABLE_OUTBOX_PUBLISHER': '1'}):
        with TestClient(mod.app) as client:
            mod.app.state.catalog_client = httpx.AsyncClient(
                base_url='http://catalog:8001', transport=httpx.MockTransport(
                    lambda req: httpx.Response(404, json={'detail':'not found'})))
            resp = client.post('/orders', json={'customer_id':'a','event_id':'bad','quantity':1,'email':'a@b.pt'})
            assert resp.status_code == 404
