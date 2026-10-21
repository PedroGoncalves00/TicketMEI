import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 3,
  duration: '12s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<1500'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const list = http.get('http://api-gateway:8000/events');
  check(list, {
    'GET /events devolve 200': r => r.status === 200,
    'GET /events devolve array': r => Array.isArray(r.json()),
  });
  const detail = http.get('http://api-gateway:8000/events/evt-101');
  check(detail, {
    'GET /events/evt-101 devolve 200': r => r.status === 200,
    'GET /events/evt-101 devolve o ID certo': r => r.json('id') === 'evt-101',
  });
  sleep(0.3);
}
