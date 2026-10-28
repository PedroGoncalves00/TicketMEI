"""TicketMEI Order — compras PENDING e outbox durável para RabbitMQ."""
import json
import logging
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

log = logging.getLogger('ticketmei.order')
DB_PATH = Path(os.getenv('ORDER_DB_PATH', '/data/orders.db'))
CATALOG_URL = os.getenv('CATALOG_URL', 'http://catalog:8001')
RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://ticketmei:ticketmei_dev@rabbitmq:5672/%2F')
QUEUE_NAME = 'order_created'

orders_initiated_total = Counter('orders_initiated_total', 'Compras criadas', ['status'])
order_request_duration_seconds = Histogram('order_request_duration_seconds', 'Latencia de criacao de compra')
orders_outbox_pending = Gauge('orders_outbox_pending', 'Eventos OrderCreated ainda por publicar')

class OrderInput(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=4, strict=True)
    email: str = Field(min_length=3, max_length=254)

    @field_validator('customer_id', 'event_id', 'email')
    @classmethod
    def no_blank(cls, value: str):
        if not value.strip():
            raise ValueError('Campo obrigatorio')
        return value.strip()

    @field_validator('email')
    @classmethod
    def simple_email(cls, value: str):
        if '@' not in value or '.' not in value.rsplit('@', 1)[-1]:
            raise ValueError('Email invalido')
        return value


def db_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def init_db():
    with db_connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
          event_id TEXT NOT NULL, email TEXT NOT NULL,
          created_at TEXT NOT NULL, total_amount TEXT NOT NULL,
          quantity INTEGER NOT NULL, status TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS outbox (
          id TEXT PRIMARY KEY, payload TEXT NOT NULL, published_at TEXT)''')


def count_pending():
    with db_connection() as db:
        return db.execute('SELECT count(*) FROM outbox WHERE published_at IS NULL').fetchone()[0]


def outbox_publisher(stop: threading.Event):
    """Reenvia mensagens pendentes; a compra fica guardada mesmo com broker offline.

    Utiliza confirmação de publicação, fila durável e mensagens persistentes.
    """
    while not stop.is_set():
        try:
            with db_connection() as db:
                row = db.execute('SELECT id, payload FROM outbox WHERE published_at IS NULL ORDER BY rowid LIMIT 1').fetchone()
            if row is not None:
                import pika  # dependência necessária apenas no contentor real
                conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
                try:
                    channel = conn.channel()
                    channel.queue_declare(queue=QUEUE_NAME, durable=True)
                    channel.confirm_delivery()
                    ok = channel.basic_publish(
                        exchange='', routing_key=QUEUE_NAME, body=row['payload'].encode('utf-8'),
                        properties=pika.BasicProperties(delivery_mode=2, content_type='application/json'),
                        mandatory=True,
                    )
                    if not ok:
                        raise RuntimeError('Broker nao confirmou publicacao')
                    with db_connection() as db:
                        db.execute('UPDATE outbox SET published_at = ? WHERE id = ?',
                                   (datetime.now(timezone.utc).isoformat(), row['id']))
                finally:
                    conn.close()
        except Exception:
            log.exception('Falha ao publicar OrderCreated; sera tentado novamente')
        stop.wait(0.5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = threading.Event()
    thread = None
    if os.getenv('DISABLE_OUTBOX_PUBLISHER', '0') != '1':
        thread = threading.Thread(target=outbox_publisher, args=(stop,), daemon=True)
        thread.start()
    async with httpx.AsyncClient(base_url=CATALOG_URL, timeout=5.0) as client:
        app.state.catalog_client = client
        yield
    stop.set()
    if thread:
        thread.join(timeout=3)

app = FastAPI(title='TicketMEI Order', version='2.0.0', lifespan=lifespan)

@app.post('/orders', status_code=202)
async def create_order(payload: OrderInput, request: Request):
    start = perf_counter()
    try:
        try:
            catalog_resp = await request.app.state.catalog_client.get(f'/events/{payload.event_id}')
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail='Catalog indisponivel')
        if catalog_resp.status_code == 404:
            raise HTTPException(status_code=404, detail='Evento nao encontrado')
        if catalog_resp.status_code != 200:
            raise HTTPException(status_code=502, detail='Erro no Catalog')
        try:
            price = Decimal(str(catalog_resp.json()['price_eur']))
            if not price.is_finite() or price < 0:
                raise ValueError('preco invalido')
        except (ValueError, KeyError, TypeError, InvalidOperation):
            raise HTTPException(status_code=502, detail='Dados invalidos do Catalog')
        order_id = str(uuid4())
        amount = (price * payload.quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        now = datetime.now(timezone.utc).isoformat()
        order = {
            'id': order_id, 'customer_id': payload.customer_id,
            'event_id': payload.event_id, 'email': payload.email,
            'created_at': now, 'total_amount': str(amount),
            'quantity': payload.quantity, 'status': 'PENDING',
        }
        message = {'event_type': 'OrderCreated', 'order_id': order_id,
                   'email': payload.email, 'created_at': now}
        # Transação única: evita criar uma compra sem registar a notificação pendente.
        with db_connection() as db:
            db.execute('''INSERT INTO orders
                       (id, customer_id, event_id, email, created_at, total_amount, quantity, status)
                       VALUES (:id, :customer_id, :event_id, :email, :created_at, :total_amount, :quantity, :status)''', order)
            db.execute('INSERT INTO outbox (id, payload) VALUES (?, ?)', (order_id, json.dumps(message)))
        orders_initiated_total.labels(status='PENDING').inc()
        return order
    finally:
        order_request_duration_seconds.observe(perf_counter() - start)

@app.get('/orders/{order_id}')
async def get_order(order_id: str):
    with db_connection() as db:
        row = db.execute('SELECT * FROM orders WHERE id = ?', (order_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Compra nao encontrada')
    return dict(row)

@app.get('/metrics', include_in_schema=False)
async def metrics():
    orders_outbox_pending.set(count_pending())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get('/health', include_in_schema=False)
async def health():
    return {'status': 'ok'}
