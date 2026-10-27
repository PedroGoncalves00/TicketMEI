import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

path = Path(__file__).resolve().parents[1] / 'notification' / 'main.py'
spec = importlib.util.spec_from_file_location('notification_main_test', path)

mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def test_notification_is_idempotent_and_has_metrics(tmp_path):
    mod.DB_PATH = tmp_path / 'notifications.db'
    with patch.dict(os.environ, {'DISABLE_NOTIFICATION_CONSUMER':'1'}):
        with TestClient(mod.app) as client:
            payload = {'event_type':'OrderCreated', 'order_id':'order-123', 'email':'a@example.com'}
            assert mod.process_order_created(payload) is True
            assert mod.process_order_created(payload) is False
            assert client.get('/notifications/order-123').json()['status'] == 'SENT'
            assert client.get('/notifications/inexistente').status_code == 404
            txt = client.get('/metrics').text
            assert 'notifications_processed_total' in txt
            assert 'notification_processing_duration_seconds_bucket' in txt


def test_bad_notification_raises(tmp_path):
    mod.DB_PATH = tmp_path / 'notifications.db'
    with patch.dict(os.environ, {'DISABLE_NOTIFICATION_CONSUMER':'1'}):
        with TestClient(mod.app):
            try:
                mod.process_order_created({'event_type':'bad', 'order_id':'a', 'email':'a@b.pt'})
            except ValueError:
                pass
            else:
                raise AssertionError('Mensagem invalida devia falhar')
