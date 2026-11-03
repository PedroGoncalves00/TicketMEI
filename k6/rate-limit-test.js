import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    burst_orders: {
      executor: 'constant-arrival-rate',
      rate: 15, // 15 pedidos/s para forçar a ultrapassagem dos 5/s
      timeUnit: '1s',
      duration: '10s',
      preAllocatedVUs: 10,
    },
  },
  thresholds: {
    'http_req_failed': ['rate>0'],
  },
};

export default function () {
  const payload = JSON.stringify({
    customer_id: 1,
    event_id: 'evt-101',
    quantity: 2,
    total_amount: 170.0
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post('http://api-gateway:8000/orders', payload, params);

  check(res, {
    'status is 202 or 429': (r) => r.status === 202 || r.status === 429,
    'has 429 rate limited': (r) => r.status === 429,
  });

  sleep(0.05);
}