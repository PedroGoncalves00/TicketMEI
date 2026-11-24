import asyncio
import os
import random
import time
import httpx
from prometheus_client import Counter, Gauge

# Métricas obrigatórias definidas no enunciado (Parte II - Fase 1)
CB_STATE = Gauge(
    "circuit_breaker_state",
    "Estado do Circuit Breaker (0=Closed, 1=Open, 2=Half-Open)",
)
CB_FALLBACKS_TOTAL = Counter(
    "circuit_breaker_fallbacks_total",
    "Total de execucoes de fallback quando o circuito esta aberto ou falha",
)
PAYMENT_CLIENT_REQUESTS_TOTAL = Counter(
    "payment_client_requests_total",
    "Total de pedidos HTTP efetivamente enviados ao servico Payment",
    ["status"],
)

# Inicializar o estado como CLOSED (0)
CB_STATE.set(0)


class CircuitBreakerOpenError(Exception):
    """Excecao lancada imediatamente (fail-fast) quando o circuito esta OPEN."""
    pass


class PaymentCircuitBreaker:
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2

    def __init__(self):
        self.failure_threshold = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
        self.recovery_timeout = float(os.getenv("CB_RECOVERY_TIMEOUT", "15.0"))
        self.request_timeout = float(os.getenv("CB_REQUEST_TIMEOUT", "2.0"))
        self.max_retries = int(os.getenv("CB_MAX_RETRIES", "2"))
        self.base_backoff = float(os.getenv("CB_BASE_BACKOFF", "0.1"))

        self.state = self.CLOSED
        self.failure_count = 0
        self.opened_at = 0.0
        self._lock = asyncio.Lock()

    def _set_state(self, new_state: int):
        self.state = new_state
        CB_STATE.set(new_state)

    async def call_payment(self, payment_url: str, payload: dict) -> dict:
        async with self._lock:
            if self.state == self.OPEN:
                # Verifica se ja passou o tempo de recuperacao para testar HALF-OPEN
                if (time.monotonic() - self.opened_at) >= self.recovery_timeout:
                    self._set_state(self.HALF_OPEN)
                else:
                    # Fail-fast: nao faz pedido HTTP nem incrementa payment_client_requests_total
                    CB_FALLBACKS_TOTAL.inc()
                    raise CircuitBreakerOpenError("Circuit breaker is OPEN")

        # Em HALF-OPEN faz apenas 1 tentativa de sonda (sem retries)
        attempts = 1 if self.state == self.HALF_OPEN else (1 + self.max_retries)

        for attempt in range(attempts):
            # Se outra corrotina abriu o circuito entretanto, aborta retries de imediato
            if self.state == self.OPEN:
                CB_FALLBACKS_TOTAL.inc()
                raise CircuitBreakerOpenError("Circuit breaker opened during retries")

            try:
                async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                    response = await client.post(f"{payment_url}/payments", json=payload)

                if 200 <= response.status_code < 300:
                    PAYMENT_CLIENT_REQUESTS_TOTAL.labels(status="2xx").inc()
                    async with self._lock:
                        self.failure_count = 0
                        if self.state != self.CLOSED:
                            self._set_state(self.CLOSED)
                    return response.json()
                else:
                    PAYMENT_CLIENT_REQUESTS_TOTAL.labels(status="500").inc()
                    await self._record_failure()

            except httpx.TimeoutException:
                PAYMENT_CLIENT_REQUESTS_TOTAL.labels(status="timeout").inc()
                await self._record_failure()

            except httpx.RequestError:
                PAYMENT_CLIENT_REQUESTS_TOTAL.labels(status="500").inc()
                await self._record_failure()

            # Se abriu apos registar a falha, suspende os retries imediatamente
            if self.state == self.OPEN:
                CB_FALLBACKS_TOTAL.inc()
                raise CircuitBreakerOpenError("Circuit breaker tripped to OPEN")

            # Retry com exponential backoff + jitter antes da proxima tentativa
            if attempt < attempts - 1:
                jitter = random.uniform(0, self.base_backoff * (2 ** attempt))
                await asyncio.sleep(self.base_backoff + jitter)

        CB_FALLBACKS_TOTAL.inc()
        raise CircuitBreakerOpenError("Payment failed after retries")

    async def _record_failure(self):
        async with self._lock:
            if self.state == self.HALF_OPEN:
                # Falha na sonda devolve imediatamente o circuito a OPEN
                self.opened_at = time.monotonic()
                self._set_state(self.OPEN)
                return

            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self.opened_at = time.monotonic()
                self._set_state(self.OPEN)