import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://api-gateway:8000';
const rateLimited = new Rate('rate_limited_requests');

export const options = {
  scenarios: {
    burst_orders: {
      executor: 'constant-arrival-rate',
      rate: 15,
      timeUnit: '1s',
      duration: '10s',
      preAllocatedVUs: 10,
      maxVUs: 30,
    },
  },
  thresholds: {
    rate_limited_requests: ['rate>0'],
  },
};

export default function () {
  const payload = JSON.stringify({
    customer_id: `rate-${__VU}-${__ITER}`,
    event_id: 'evt-101',
    quantity: 2,
    email: `rate-${__VU}-${__ITER}@example.com`,
  });

  const res = http.post(`${BASE_URL}/orders`, payload, {
    headers: { 'Content-Type': 'application/json' },
  });

  rateLimited.add(res.status === 429);

  check(res, {
    'status is 202 or 429': (r) => r.status === 202 || r.status === 429,
  });

  sleep(0.05);
}
