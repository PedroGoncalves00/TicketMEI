"""TicketMEI Gateway — proxy HTTP para Catalog e Order; métricas Prometheus."""
import os
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import JSONResponse, Response

CATALOG_URL = os.getenv('CATALOG_URL', 'http://catalog:8001')
ORDER_URL = os.getenv('ORDER_URL', 'http://order:8002')

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(base_url=CATALOG_URL, timeout=5.0) as catalog_client:
        async with httpx.AsyncClient(base_url=ORDER_URL, timeout=5.0) as order_client:
            app.state.catalog_client = catalog_client
            app.state.order_client = order_client
            yield

app = FastAPI(title='TicketMEI API Gateway', version='2.0.0', lifespan=lifespan)

gateway_requests_total = Counter('gateway_requests_total', 'Pedidos ao API Gateway',
                                  ['method', 'endpoint', 'http_status'])
gateway_request_duration_seconds = Histogram('gateway_request_duration_seconds',
                                             'Duracao dos pedidos ao API Gateway em segundos', ['endpoint'])

@app.middleware('http')
async def record_metrics(request: Request, call_next):
    path = request.url.path
    if not (path.startswith('/events') or path.startswith('/orders')):
        return await call_next(request)
    if path.startswith('/events'):
        endpoint = '/events/{id}' if path.startswith('/events/') else '/events'
    else:
        endpoint = '/orders/{id}' if path.startswith('/orders/') else '/orders'
    start, status = perf_counter(), 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        gateway_requests_total.labels(method=request.method, endpoint=endpoint, http_status=str(status)).inc()
        gateway_request_duration_seconds.labels(endpoint=endpoint).observe(perf_counter() - start)

async def proxy(request: Request, service: str, path: str, method: str = 'GET'):
    client = request.app.state.catalog_client if service == 'catalog' else request.app.state.order_client
    try:
        if method == 'POST':
            upstream = await client.post(path, content=await request.body(), headers={'content-type': 'application/json'})
        else:
            upstream = await client.get(path)
        return JSONResponse(status_code=upstream.status_code, content=upstream.json())
    except (httpx.RequestError, ValueError):
        raise HTTPException(status_code=502, detail=f'{service} indisponivel ou resposta invalida')

@app.get('/events')
async def events(request: Request):
    return await proxy(request, 'catalog', '/events')

@app.get('/events/{event_id}')
async def event_details(event_id: str, request: Request):
    return await proxy(request, 'catalog', f'/events/{event_id}')

@app.post('/orders')
async def create_order(request: Request):
    return await proxy(request, 'order', '/orders', method='POST')

@app.get('/orders/{order_id}')
async def order_details(order_id: str, request: Request):
    return await proxy(request, 'order', f'/orders/{order_id}')

@app.get('/metrics', include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get('/health', include_in_schema=False)
async def health():
    return {'status':'ok'}
