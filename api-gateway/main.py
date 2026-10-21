"""API Gateway: expõe a API pública e faz proxy síncrono para Catalog."""
import os
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import JSONResponse, Response

CATALOG_URL = os.getenv('CATALOG_URL', 'http://catalog:8001')

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(base_url=CATALOG_URL, timeout=5.0) as client:
        app.state.catalog_client = client
        yield

app = FastAPI(title='TicketMEI API Gateway', version='1.0.0', lifespan=lifespan)

gateway_requests_total = Counter(
    'gateway_requests_total', 'Pedidos ao API Gateway',
    ['method', 'endpoint', 'http_status']
)
gateway_request_duration_seconds = Histogram(
    'gateway_request_duration_seconds',
    'Duracao dos pedidos ao API Gateway em segundos', ['endpoint']
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
        gateway_requests_total.labels(
            method=request.method, endpoint=endpoint, http_status=str(status)
        ).inc()
        gateway_request_duration_seconds.labels(endpoint=endpoint).observe(
            perf_counter() - started
        )

async def call_catalog(request: Request, path: str):
    try:
        upstream = await request.app.state.catalog_client.get(path)
        return JSONResponse(status_code=upstream.status_code, content=upstream.json())
    except (httpx.RequestError, ValueError):
        raise HTTPException(status_code=502, detail='Catalog indisponivel ou resposta invalida')

@app.get('/events')
async def events(request: Request):
    return await call_catalog(request, '/events')

@app.get('/events/{event_id}')
async def event_details(event_id: str, request: Request):
    return await call_catalog(request, f'/events/{event_id}')

@app.get('/metrics', include_in_schema=False)
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get('/health', include_in_schema=False)
async def health():
    return {'status': 'ok'}
