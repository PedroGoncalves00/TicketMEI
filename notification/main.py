"""TicketMEI Notification — consumidor RabbitMQ e envio de email simulado."""
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

log = logging.getLogger('ticketmei.notification')
DB_PATH = Path(os.getenv('NOTIFICATION_DB_PATH', '/data/notifications.db'))
RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://ticketmei:ticketmei_dev@rabbitmq:5672/%2F')
QUEUE_NAME = 'order_created'

notifications_processed_total = Counter('notifications_processed_total', 'Notificacoes processadas', ['status'])
notification_processing_duration_seconds = Histogram('notification_processing_duration_seconds', 'Duracao da notificacao em segundos')


def db_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db


def init_db():
    with db_connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS notifications (
            order_id TEXT PRIMARY KEY, email TEXT NOT NULL, status TEXT NOT NULL,
            processed_at TEXT NOT NULL)''')


def process_order_created(payload: dict):
    """Guarda uma notificação por encomenda, mesmo após redelivery RabbitMQ."""
    start = time.perf_counter()
    try:
        order_id = payload['order_id']
        email = payload['email']
        if payload.get('event_type') != 'OrderCreated' or not order_id or '@' not in email:
            raise ValueError('Mensagem OrderCreated invalida')
        with db_connection() as db:
            if db.execute('SELECT 1 FROM notifications WHERE order_id=?', (order_id,)).fetchone():
                return False
        time.sleep(0.1)  # exigência do enunciado: simular 100ms de envio
        with db_connection() as db:
            cursor = db.execute('''INSERT OR IGNORE INTO notifications
                (order_id, email, status, processed_at) VALUES (?, ?, ?, ?)''',
                (order_id, email, 'SENT', datetime.now(timezone.utc).isoformat()))
        if cursor.rowcount:
            log.info('EMAIL_SIMULADO order_id=%s para=%s status=SENT', order_id, email)
            notifications_processed_total.labels(status='SENT').inc()
            return True
        return False
    finally:
        notification_processing_duration_seconds.observe(time.perf_counter() - start)


def consumer_worker(stop: threading.Event):
    while not stop.is_set():
        connection = None
        try:
            import pika
            connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)

            def callback(ch, method, properties, body):
                try:
                    process_order_created(json.loads(body))
                except Exception:
                    log.exception('Notificacao falhou; mensagem rejeitada')
                    notifications_processed_total.labels(status='FAILED').inc()
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                else:
                    ch.basic_ack(delivery_tag=method.delivery_tag)

            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=callback)
            while not stop.is_set():
                connection.process_data_events(time_limit=1)
        except Exception:
            log.exception('Falha no consumidor RabbitMQ; tentativa de reconexao')
        finally:
            if connection and connection.is_open:
                connection.close()
        stop.wait(2)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = threading.Event()
    thread = None
    if os.getenv('DISABLE_NOTIFICATION_CONSUMER', '0') != '1':
        thread = threading.Thread(target=consumer_worker, args=(stop,), daemon=True)
        thread.start()
    yield
    stop.set()
    if thread:
        thread.join(timeout=3)

app = FastAPI(title='TicketMEI Notification', version='2.0.0', lifespan=lifespan)

@app.get('/notifications/{order_id}')
async def get_notification(order_id: str):
    with db_connection() as db:
        row = db.execute('SELECT * FROM notifications WHERE order_id=?', (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Notificacao ainda nao processada')
    return dict(row)

@app.get('/metrics', include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get('/health', include_in_schema=False)
async def health():
    return {'status': 'ok'}
