"""Catalog: lista e detalhes de eventos, com métricas Prometheus."""
import json
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'events.json'
with DATA_FILE.open(encoding='utf-8') as f:
    EVENTS = json.load(f)

app = FastAPI(title='TicketMEI Catalog', version='1.0.0')

catalog_requests_total = Counter(
    'catalog_requests_total', 'Pedidos ao Catalog', ['endpoint', 'http_status']
)
catalog_request_duration_seconds = Histogram(
    'catalog_request_duration_seconds', 'Duracao dos pedidos ao Catalog em segundos'
)

@app.middleware('http')
async def record_metrics(request: Request, call_next):
    if not request.url.path.startswith('/events'):
        return await call_next(request)
    endpoint = '/events/{id}' if request.url.path.startswith('/events/') else '/events'
    started = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        catalog_requests_total.labels(endpoint=endpoint, http_status=str(status)).inc()
        catalog_request_duration_seconds.observe(perf_counter() - started)

@app.get('/events')
async def list_events():
    return EVENTS

@app.get('/events/{event_id}')
async def get_event(event_id: str):
    for event in EVENTS:
        if event['id'] == event_id:
            return event
    raise HTTPException(status_code=404, detail='Evento nao encontrado')

@app.get('/metrics', include_in_schema=False)
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get('/health', include_in_schema=False)
async def health():
    return {'status': 'ok'}
