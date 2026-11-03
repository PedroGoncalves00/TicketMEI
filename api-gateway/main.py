"""TicketMEI Gateway — proxy HTTP, Rate Limiter com Redis e métricas Prometheus."""
import os
import time
from contextlib import asynccontextmanager
from time import perf_counter

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import JSONResponse, Response

CATALOG_URL = os.getenv('CATALOG_URL', 'http://catalog:8001')
ORDER_URL = os.getenv('ORDER_URL', 'http://order:8002')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')

RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', '5'))
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '1'))  # Janela de 1 segundo

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(base_url=CATALOG_URL, timeout=5.0) as catalog_client:
        async with httpx.AsyncClient(base_url=ORDER_URL, timeout=5.0) as order_client:
            redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
            app.state.catalog_client = catalog_client
            app.state.order_client = order_client
            app.state.redis_client = redis_client
            try:
                yield
            finally:
                await redis_client.aclose()

app = FastAPI(title='TicketMEI API Gateway', version='3.0.0', lifespan=lifespan)

gateway_requests_total = Counter(
    'gateway_requests_total',
    'Pedidos ao API Gateway',
    ['method', 'endpoint', 'http_status']
)
gateway_request_duration_seconds = Histogram(
    'gateway_request_duration_seconds',
    'Duracao dos pedidos ao API Gateway em segundos',
    ['endpoint']
)
gateway_rate_limited_total = Counter(
    'gateway_rate_limited_total',
    'Pedidos bloqueados pelo Rate Limiter (HTTP 429)',
    ['endpoint']
)

async def check_rate_limit(redis_conn: redis.Redis, client_ip: str) -> tuple[bool, int, int]:
    """Janela deslizante com sorted sets (ZSET) no Redis."""
    now = time.time()
    clear_before = now - RATE_LIMIT_WINDOW
    key = f"rate_limit:{client_ip}"

    try:
        pipe = redis_conn.pipeline()
        pipe.zremrangebyscore(key, 0, clear_before)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, RATE_LIMIT_WINDOW + 1)
        results = await pipe.execute()

        current_count = results[1]
        if current_count >= RATE_LIMIT_REQUESTS:
            await redis_conn.zrem(key, str(now))
            return False, 0, 1
        
        remaining = max(0, RATE_LIMIT_REQUESTS - (current_count + 1))
        return True, remaining, 0
    except Exception:
        # Modo Fail-Open em caso de falha temporária do Redis para não bloquear o tráfego legítimo
        return True, RATE_LIMIT_REQUESTS, 0

@app.middleware('http')
async def record_metrics(request: Request, call_next):
    path = request.url.path
    if not (path.startswith('/events') or path.startswith('/orders')):
        return await call_next(request)
    
    endpoint = '/events/{id}' if path.startswith('/events/') else ('/events' if path == '/events' else ('/orders/{id}' if path.startswith('/orders/') else '/orders'))
    start, status = perf_counter(), 500

    # Rate Limiting obrigatório no POST /orders por IP de cliente
    if request.method == 'POST' and path == '/orders':
        client_ip = request.headers.get('x-forwarded-for', request.client.host if request.client else 'unknown').split(',')[0].strip()
        allowed, remaining, retry_after = await check_rate_limit(request.app.state.redis_client, client_ip)
        
        if not allowed:
            status = 429
            gateway_requests_total.labels(method='POST', endpoint='/orders', http_status='429').inc()
            gateway_rate_limited_total.labels(endpoint='/orders').inc()
            gateway_request_duration_seconds.labels(endpoint='/orders').observe(perf_counter() - start)
            
            return JSONResponse(
                status_code=429,
                content={'detail': 'Too Many Requests: Rate limit of 5 req/s exceeded'},
                headers={
                    'Retry-After': str(retry_after),
                    'X-RateLimit-Limit': str(RATE_LIMIT_REQUESTS),
                    'X-RateLimit-Remaining': '0',
                    'X-RateLimit-Reset': str(int(time.time() + retry_after))
                }
            )

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
    return {'status': 'ok'}