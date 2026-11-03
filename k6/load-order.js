import http from 'k6/http';
import {check, sleep} from 'k6';
export const options = {
  stages: [{duration:'20s',target:10},{duration:'30s',target:10},{duration:'10s',target:0}],
  thresholds: {http_req_failed:['rate<0.01'], http_req_duration:['p(95)<2000']},
};
export default function () {
  const body = JSON.stringify({customer_id:`c-${__VU}-${__ITER}`, event_id:'evt-102', quantity:1, email:`c${__VU}@example.com`});
  const r = http.post('http://api-gateway:8000/orders', body, {headers:{'Content-Type':'application/json'}});
  check(r, {'compra aceite': x => x.status === 202});
  sleep(1);
}
