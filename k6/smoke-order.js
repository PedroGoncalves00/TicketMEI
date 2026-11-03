import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 2,
  iterations: 8,
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const payload = JSON.stringify({
    customer_id: `cliente-vu${__VU}-it${__ITER}`,
    event_id: 'evt-101',
    quantity: 2,
    email: `teste${__VU}-${__ITER}@example.com`,
  });
  const res = http.post('http://api-gateway:8000/orders', payload,
                        {headers: {'Content-Type': 'application/json'}});
  check(res, {'POST /orders responde 202': r => r.status === 202,
              'Compra fica PENDING': r => r.status === 202 && r.json('status') === 'PENDING'});
  if (res.status === 202) {
    const id = res.json('id');
    const detail = http.get(`http://api-gateway:8000/orders/${id}`);
    check(detail, {'GET /orders/{id} responde 200': r => r.status === 200,
                   'Identificador confere': r => r.status === 200 && r.json('id') === id});
  }
  sleep(0.2);
}
