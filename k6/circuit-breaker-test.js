import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const PAYMENT_URL = __ENV.PAYMENT_URL || 'http://localhost:8004';

const confirmedOrders = new Counter('orders_confirmed_201');
const fallbackOrders = new Counter('orders_fallback_503');
const orderLatency = new Trend('order_request_duration_ms');

export const options = {
  scenarios: {
    // 1. Carga constante de 50 pedidos/s durante 3m30s no POST /orders
    constant_orders: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '210s',
      preAllocatedVUs: 30,
      maxVUs: 100,
      exec: 'createOrder',
    },
    // 2. Injecao de falhas no Payment a meio do teste (2 minutos) e restauracao
    fault_injector: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: 1,
      maxDuration: '210s',
      exec: 'manageFaults',
    },
  },
};

export function createOrder() {
  const payload = JSON.stringify({
    customer_id: `cust-${__VU}-${__ITER}`,
    event_id: 'evt-101',
    quantity: 1,
    email: `user-${__VU}@ticketmei.pt`,
  });

  // Simula IPs distintos por utilizador virtual para cumprir o limite de 5 req/s por IP no Gateway
  const clientIp = `10.${(__VU % 250) + 1}.${(__ITER % 250) + 1}.1`;

  const res = http.post(`${BASE_URL}/orders`, payload, {
    headers: {
      'Content-Type': 'application/json',
      'X-Forwarded-For': clientIp,
    },
  });

  orderLatency.add(res.timings.duration);

  if (res.status === 201) {
    confirmedOrders.add(1);
  } else if (res.status === 503) {
    fallbackOrders.add(1);
  }

  check(res, {
    'status is 201 (Confirmed) or 503 (Fallback)': (r) => r.status === 201 || r.status === 503,
  });
}

export function manageFaults() {
  // Fase A (0s - 30s): Sistema saudavel (Circuito CLOSED)
  sleep(30);

  // Fase B (30s - 150s -> 2 minutos): Injetar degradacao (80% HTTP 500 e atraso de 10s)
  console.log('>>> INJETANDO FALHAS NO PAYMENT (2 minutos)...');
  http.post(
    `${PAYMENT_URL}/payments/configure-faults`,
    JSON.stringify({ error_rate: 0.8, latency_seconds: 10.0 }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  sleep(120);

  // Fase C (150s - 210s): Restaurar Payment e validar recuperacao autonoma (HALF-OPEN -> CLOSED)
  console.log('>>> RESTAURANDO PAYMENT NORMAL...');
  http.post(
    `${PAYMENT_URL}/payments/configure-faults`,
    JSON.stringify({ error_rate: 0.0, latency_seconds: 0.0 }),
    { headers: { 'Content-Type': 'application/json' } }
  );
}