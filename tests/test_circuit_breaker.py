import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from order.circuit_breaker import CircuitBreakerOpenError, PaymentCircuitBreaker


def test_circuit_breaker_success_keeps_closed():
    async def _run():
        cb = PaymentCircuitBreaker()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'status': 'SUCCESS'}

        with patch('httpx.AsyncClient.post', new=AsyncMock(return_value=mock_resp)) as mock_post:
            res = await cb.call_payment('http://payment:8004', {'order_id': 'ord-1', 'amount': 85.0})
            assert res == {'status': 'SUCCESS'}
            assert cb.state == PaymentCircuitBreaker.CLOSED
            assert cb.failure_count == 0
            assert mock_post.call_count == 1

    asyncio.run(_run())


def test_circuit_breaker_opens_on_500_and_fails_fast():
    async def _run():
        cb = PaymentCircuitBreaker()
        cb.failure_threshold = 3
        cb.max_retries = 1
        cb.base_backoff = 0.01
        cb.recovery_timeout = 0.3

        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500

        with patch('httpx.AsyncClient.post', new=AsyncMock(return_value=mock_resp_500)) as mock_post:
            # 1. Primeira chamada: 1 tentativa inicial + 1 retry = 2 falhas (ainda CLOSED)
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call_payment('http://payment:8004', {'order_id': 'ord-2', 'amount': 50.0})
            assert cb.state == PaymentCircuitBreaker.CLOSED
            assert cb.failure_count == 2
            assert mock_post.call_count == 2

            # 2. Segunda chamada: atinge a 3a falha e abre o circuito (OPEN = 1) imediatamente sem retry extra
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call_payment('http://payment:8004', {'order_id': 'ord-3', 'amount': 50.0})
            assert cb.state == PaymentCircuitBreaker.OPEN
            assert mock_post.call_count == 3

            # 3. Terceira chamada com circuito OPEN: fail-fast (nao efetua pedido HTTP)
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call_payment('http://payment:8004', {'order_id': 'ord-4', 'amount': 50.0})
            assert mock_post.call_count == 3

    asyncio.run(_run())


def test_circuit_breaker_opens_on_timeout_and_recovers():
    async def _run():
        cb = PaymentCircuitBreaker()
        cb.failure_threshold = 2
        cb.max_retries = 1
        cb.base_backoff = 0.01
        cb.recovery_timeout = 0.15

        # Simular lentidao/timeout acima do limite configurado
        with patch(
            'httpx.AsyncClient.post',
            new=AsyncMock(side_effect=httpx.TimeoutException('Request timed out')),
        ):
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call_payment('http://payment:8004', {'order_id': 'ord-5', 'amount': 120.0})
            assert cb.state == PaymentCircuitBreaker.OPEN

        # Aguardar janela de recuperacao -> transita para HALF-OPEN e fecha (CLOSED) no sucesso
        await asyncio.sleep(0.2)
        mock_resp_200 = MagicMock()
        mock_resp_200.status_code = 200
        mock_resp_200.json.return_value = {'status': 'SUCCESS'}

        with patch('httpx.AsyncClient.post', new=AsyncMock(return_value=mock_resp_200)):
            res = await cb.call_payment('http://payment:8004', {'order_id': 'ord-6', 'amount': 120.0})
            assert res['status'] == 'SUCCESS'
            assert cb.state == PaymentCircuitBreaker.CLOSED
            assert cb.failure_count == 0

    asyncio.run(_run())


def test_circuit_breaker_half_open_failure_reopens():
    async def _run():
        cb = PaymentCircuitBreaker()
        cb.failure_threshold = 1
        cb.max_retries = 0
        cb.recovery_timeout = 0.1

        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500

        with patch('httpx.AsyncClient.post', new=AsyncMock(return_value=mock_resp_500)):
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call_payment('http://payment:8004', {'order_id': 'ord-7', 'amount': 40.0})
            assert cb.state == PaymentCircuitBreaker.OPEN

            await asyncio.sleep(0.15)

            # Sonda em HALF-OPEN falha -> volta imediatamente a OPEN
            with pytest.raises(CircuitBreakerOpenError):
                await cb.call_payment('http://payment:8004', {'order_id': 'ord-8', 'amount': 40.0})
            assert cb.state == PaymentCircuitBreaker.OPEN

    asyncio.run(_run())