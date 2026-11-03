import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi.testclient import TestClient

# Garante que a pasta tests/ está no caminho de importação do Python
tests_dir = str(Path(__file__).resolve().parent)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

# Reutiliza o módulo já carregado em test_gateway para não recriar métricas no CollectorRegistry
from test_gateway import module


def test_rate_limiter_allows_and_blocks():
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    with TestClient(module.app) as client:
        module.app.state.redis_client = mock_redis
        module.app.state.order_client = httpx.AsyncClient(
            base_url='http://order:8002',
            transport=httpx.MockTransport(lambda req: httpx.Response(202, json={'status': 'PENDING'}))
        )

        # 1. Dentro da quota de 5 req/s (ex.: 2 no zset) -> HTTP 202
        mock_pipe.execute.return_value = [None, 2, None, None]
        res1 = client.post('/orders', json={'event_id': 'evt-101', 'quantity': 2})
        assert res1.status_code == 202

        # 2. Excesso de tráfego (>= 5 req/s, ex.: 5 no zset) -> HTTP 429
        mock_pipe.execute.return_value = [None, 5, None, None]
        res2 = client.post('/orders', json={'event_id': 'evt-101', 'quantity': 2})
        assert res2.status_code == 429
        assert 'Too Many Requests' in res2.json()['detail']
        assert res2.headers['Retry-After'] == '1'
        assert res2.headers['X-RateLimit-Remaining'] == '0'