from fastapi.testclient import TestClient
from catalog.main import app

client = TestClient(app)

def test_events_list():
    resp = client.get('/events')
    assert resp.status_code == 200
    assert len(resp.json()) == 4
    assert resp.json()[0]['id'] == 'evt-101'

def test_event_details_and_missing_id():
    resp = client.get('/events/evt-101')
    assert resp.status_code == 200
    assert resp.json()['title'].startswith('Coldplay')
    assert client.get('/events/nao-existe').status_code == 404

def test_catalog_metrics():
    client.get('/events')
    txt = client.get('/metrics').text
    assert 'catalog_requests_total' in txt
    assert 'catalog_request_duration_seconds_bucket' in txt
    assert 'http_status="200"' in txt
