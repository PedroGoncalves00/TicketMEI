import importlib.util
import sqlite3
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

path = Path(__file__).resolve().parents[1] / 'payment' / 'main.py'
spec = importlib.util.spec_from_file_location('payment_main_test', path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'DB_PATH', tmp_path / 'payment.db')
    with TestClient(mod.app) as c:
        yield c


def rows():
    with sqlite3.connect(mod.DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT * FROM Payment ORDER BY rowid')]


def payload():
    return {'order_id': str(uuid4()), 'amount': 170.0}


def configure(client, rate, latency=0):
    response = client.post('/payments/configure-faults', json={
        'error_rate': rate, 'latency_seconds': latency,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_success_and_persistence(client):
    data = payload()
    response = client.post('/payments', json=data)
    assert response.status_code == 201
    result = response.json()
    assert result['status'] == 'SUCCESS'
    assert result['order_id'] == data['order_id']
    assert result['amount'] == 170.0
    assert result['id'] and result['processed_at']
    assert rows()[0]['status'] == 'SUCCESS'
    assert rows()[0]['amount'] == '170.00'


def test_fault_and_recovery(client):
    data = payload()
    assert configure(client, 100)['error_rate'] == 1.0
    response = client.post('/payments', json=data)
    assert response.status_code == 500
    assert response.json()['status'] == 'FAILED'
    assert rows()[0]['status'] == 'FAILED'
    configure(client, 0)
    assert client.post('/payments', json=data).status_code == 201
    assert [r['status'] for r in rows()] == ['FAILED', 'SUCCESS']


def test_percentage_and_validation(client):
    assert configure(client, 80)['error_rate'] == 0.8
    assert configure(client, 0.5)['error_rate'] == 0.5
    for rate, delay in [(-1, 0), (101, 0), (0, -1)]:
        assert client.post('/payments/configure-faults', json={
            'error_rate': rate, 'latency_seconds': delay}).status_code == 422
    for data in [{'order_id': '', 'amount': 1}, {'order_id': 'x', 'amount': -1}]:
        assert client.post('/payments', json=data).status_code == 422
    assert rows() == []


def test_latency(client):
    configure(client, 0, 0.12)
    start = perf_counter()
    assert client.post('/payments', json=payload()).status_code == 201
    assert perf_counter() - start >= 0.11


def test_success_is_idempotent(client):
    data = payload()
    first = client.post('/payments', json=data)
    configure(client, 1)
    second = client.post('/payments', json=data)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json() == second.json()
    assert len(rows()) == 1
    assert client.post('/payments', json={**data, 'amount': 180}).status_code == 409


def test_health_and_metrics(client):
    assert client.get('/health').json() == {'status': 'ok'}
    success = mod.payment_requests_total.labels(http_status='201')
    failure = mod.payment_requests_total.labels(http_status='500')
    before = (success._value.get(), failure._value.get())
    assert client.post('/payments', json=payload()).status_code == 201
    configure(client, 1)
    assert client.post('/payments', json=payload()).status_code == 500
    assert success._value.get() == before[0] + 1
    assert failure._value.get() == before[1] + 1
    text = client.get('/metrics').text
    assert 'payment_requests_total{http_status="201"}' in text
    assert 'payment_requests_total{http_status="500"}' in text
    assert 'payment_processing_duration_seconds_bucket' in text
    assert 'payment_processing_duration_seconds_count' in text
