"""TicketMEI Payment — simulated payments, SQLite and configurable faults."""
import asyncio
import os
import random
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator

DB_PATH = Path(os.getenv('PAYMENT_DB_PATH', '/data/payment.db'))
payment_requests_total = Counter(
    'payment_requests_total', 'Pedidos de pagamento por codigo HTTP', ['http_status']
)
payment_processing_duration_seconds = Histogram(
    'payment_processing_duration_seconds', 'Duracao do processamento de pagamento em segundos'
)
# Expose zero-valued series before the first payment.
for code in ('200', '201', '409', '422', '500'):
    payment_requests_total.labels(http_status=code)


class PaymentInput(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)

    @field_validator('order_id')
    @classmethod
    def non_blank(cls, value: str):
        if not value.strip():
            raise ValueError('order_id obrigatorio')
        return value.strip()


class FaultConfig(BaseModel):
    error_rate: float = Field(ge=0, le=100, allow_inf_nan=False)
    latency_seconds: float = Field(ge=0, allow_inf_nan=False)

    @field_validator('error_rate')
    @classmethod
    def normalize_rate(cls, value: float):
        # 0..1 = probability; values above 1 = percentage.
        return value / 100 if value > 1 else value


def db_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with closing(db_connection()) as db, db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('''CREATE TABLE IF NOT EXISTS Payment (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('SUCCESS', 'FAILED')),
            processed_at TEXT NOT NULL
        )''')
        db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS payment_success_order
            ON Payment(order_id) WHERE status = 'SUCCESS' ''')


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.faults = FaultConfig(error_rate=0, latency_seconds=0)
    yield


app = FastAPI(title='TicketMEI Payment', version='1.0.0', lifespan=lifespan)


@app.middleware('http')
async def record_metrics(request: Request, call_next):
    if request.method != 'POST' or request.url.path != '/payments':
        return await call_next(request)
    start, status = perf_counter(), 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        payment_requests_total.labels(http_status=str(status)).inc()
        payment_processing_duration_seconds.observe(perf_counter() - start)


def serialize_payment(row):
    result = dict(row)
    result['amount'] = float(result['amount'])
    return result


def previous_success(db, order_id):
    return db.execute(
        "SELECT * FROM Payment WHERE order_id = ? AND status = 'SUCCESS'", (order_id,)
    ).fetchone()


def replay_response(row, amount):
    if Decimal(row['amount']) != amount:
        return JSONResponse(status_code=409, content={'error': 'Order already paid with different amount'})
    return JSONResponse(status_code=200, content=serialize_payment(row))


@app.post('/payments', status_code=201)
async def create_payment(payload: PaymentInput, request: Request):
    amount = payload.amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    # A successful retry must not simulate another charge for the same order.
    with closing(db_connection()) as db:
        existing = previous_success(db, payload.order_id)
    if existing is not None:
        return replay_response(existing, amount)

    # Snapshot fault settings at request start. Async delay does not block health or configuration.
    faults = request.app.state.faults
    if faults.latency_seconds:
        await asyncio.sleep(faults.latency_seconds)
    failed = random.random() < faults.error_rate
    record = {
        'id': str(uuid4()),
        'order_id': payload.order_id,
        'amount': str(amount),
        'status': 'FAILED' if failed else 'SUCCESS',
        'processed_at': datetime.now(timezone.utc).isoformat(),
    }
    # The transaction serializes the final check and insert, including concurrent retries.
    with closing(db_connection()) as db, db:
        db.execute('BEGIN IMMEDIATE')
        existing = previous_success(db, payload.order_id)
        if existing is not None:
            return replay_response(existing, amount)
        db.execute('''INSERT INTO Payment (id, order_id, amount, status, processed_at)
            VALUES (:id, :order_id, :amount, :status, :processed_at)''', record)

    return JSONResponse(status_code=500 if failed else 201, content=serialize_payment(record))


@app.post('/payments/configure-faults')
async def configure_faults(config: FaultConfig, request: Request):
    request.app.state.faults = config
    return config.model_dump()


@app.get('/health', include_in_schema=False)
async def health():
    return {'status': 'ok'}


@app.get('/metrics', include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
