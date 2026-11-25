
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';

// --------------------------------------------------
// CONFIGURATION
// --------------------------------------------------

const BASE_URL = __ENV.PAYMENT_URL || 'http://payment:8004';

const successCounter = new Counter('payment_success_201');
const idempotentCounter = new Counter('payment_idempotent_200');
const failureCounter = new Counter('payment_failure_500');
const validationCounter = new Counter('payment_validation_422');
const conflictCounter = new Counter('payment_conflict_409');

const paymentLatency = new Trend('payment_request_duration_ms');

export const options = {
  scenarios: {
    payment_tests: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: 1,
      maxDuration: '180s',
    },
  },

  thresholds: {
    payment_request_duration_ms: ['p(95)<2000'],
    checks: ['rate>0.90'],
  },
};

// --------------------------------------------------
// HELPERS
// --------------------------------------------------

function uniqueOrderId() {
  return `order-${__VU}-${__ITER}-${Date.now()}-${Math.random()}`;
}

function payload(orderId = uniqueOrderId(), amount = 170) {
  return JSON.stringify({
    order_id: orderId,
    amount: amount,
  });
}

const headers = {
  'Content-Type': 'application/json',
};

function configureFaults(errorRate, latency = 0) {
  const response = http.post(
    `${BASE_URL}/payments/configure-faults`,
    JSON.stringify({
      error_rate: errorRate,
      latency_seconds: latency,
    }),
    { headers }
  );

  check(response, {
    'Configure faults returns 200': (r) => r.status === 200,
  });

  return response;
}

function payment(orderId, amount = 170) {
  const response = http.post(
    `${BASE_URL}/payments`,
    payload(orderId, amount),
    { headers }
  );

  paymentLatency.add(response.timings.duration);

  return response;
}

// --------------------------------------------------
// TEST 1: SUCCESS AND PERSISTENCE
// --------------------------------------------------

function testSuccessAndPersistence() {
  console.log('TEST 1: Success and persistence');

  configureFaults(0, 0);

  const orderId = uniqueOrderId();
  const response = payment(orderId);

  const body = response.json();

  const passed = check(response, {
    'Payment returns HTTP 201': (r) => r.status === 201,
    'Payment status is SUCCESS': () => body.status === 'SUCCESS',
    'Correct order_id': () => body.order_id === orderId,
    'Correct amount': () => body.amount === 170,
    'Payment ID exists': () => !!body.id,
    'processed_at exists': () => !!body.processed_at,
  });

  if (response.status === 201) {
    successCounter.add(1);
  }

  check(response, {
    'Success and persistence checks passed': () => passed,
  });

  sleep(1);
}

// --------------------------------------------------
// TEST 2: FAULT AND RECOVERY
// --------------------------------------------------

function testFaultAndRecovery() {
  console.log('TEST 2: Fault injection and recovery');

  const orderId = uniqueOrderId();

  configureFaults(100);

  const failed = payment(orderId);

  check(failed, {
    'Fault injection returns HTTP 500': (r) => r.status === 500,
    'Payment status is FAILED': (r) => {
      return r.json().status === 'FAILED';
    },
  });

  if (failed.status === 500) {
    failureCounter.add(1);
  }

  configureFaults(0);

  const recovered = payment(orderId);

  check(recovered, {
    'Payment recovers with HTTP 201': (r) => r.status === 201,
    'Recovered payment is SUCCESS': (r) => {
      return r.json().status === 'SUCCESS';
    },
  });

  sleep(1);
}

// --------------------------------------------------
// TEST 3: PERCENTAGE AND VALIDATION
// --------------------------------------------------

function testPercentageAndValidation() {
  console.log('TEST 3: Percentage and validation');

  let response = configureFaults(80);

  check(response, {
    '80 is interpreted as 0.8': (r) => {
      return r.json().error_rate === 0.8;
    },
  });

  response = configureFaults(0.5);

  check(response, {
    '0.5 remains 0.5': (r) => {
      return r.json().error_rate === 0.5;
    },
  });

  const invalidConfigurations = [
    { error_rate: -1, latency_seconds: 0 },
    { error_rate: 101, latency_seconds: 0 },
    { error_rate: 0, latency_seconds: -1 },
  ];

  invalidConfigurations.forEach((data) => {
    const res = http.post(
      `${BASE_URL}/payments/configure-faults`,
      JSON.stringify(data),
      { headers }
    );

    check(res, {
      'Invalid fault configuration returns 422': (r) => r.status === 422,
    });

    if (res.status === 422) {
      validationCounter.add(1);
    }
  });

  const invalidPayments = [
    { order_id: '', amount: 1 },
    { order_id: 'x', amount: -1 },
  ];

  invalidPayments.forEach((data) => {
    const res = http.post(
      `${BASE_URL}/payments`,
      JSON.stringify(data),
      { headers }
    );

    check(res, {
      'Invalid payment returns 422': (r) => r.status === 422,
    });

    if (res.status === 422) {
      validationCounter.add(1);
    }
  });

  configureFaults(0);
  sleep(1);
}

// --------------------------------------------------
// TEST 4: LATENCY
// --------------------------------------------------

function testLatency() {
  console.log('TEST 4: Payment latency');

  configureFaults(0, 0.12);

  const start = Date.now();

  const response = payment(uniqueOrderId());

  const elapsed = Date.now() - start;

  check(response, {
    'Payment returns HTTP 201': (r) => r.status === 201,
    'Latency is at least 110ms': () => elapsed >= 110,
  });

  configureFaults(0, 0);
  sleep(1);
}

// --------------------------------------------------
// TEST 5: IDEMPOTENCY
// --------------------------------------------------

function testIdempotency() {
  console.log('TEST 5: Idempotency');

  const orderId = uniqueOrderId();

  configureFaults(0);

  const first = payment(orderId);

  configureFaults(1);

  const second = payment(orderId);

  check(first, {
    'First request returns 201': (r) => r.status === 201,
  });

  check(second, {
    'Duplicate request returns 200': (r) => r.status === 200,
    'Duplicate returns same payment': (r) => {
      return JSON.stringify(r.json()) === JSON.stringify(first.json());
    },
  });

  if (second.status === 200) {
    idempotentCounter.add(1);
  }

  const conflict = http.post(
    `${BASE_URL}/payments`,
    payload(orderId, 180),
    { headers }
  );

  check(conflict, {
    'Different amount returns HTTP 409': (r) => r.status === 409,
  });

  if (conflict.status === 409) {
    conflictCounter.add(1);
  }

  configureFaults(0);
  sleep(1);
}

// --------------------------------------------------
// TEST 6: HEALTH AND METRICS
// --------------------------------------------------

function testHealthAndMetrics() {
  console.log('TEST 6: Health and metrics');

  const health = http.get(`${BASE_URL}/health`);

  check(health, {
    'Health returns HTTP 200': (r) => r.status === 200,
    'Health status is ok': (r) => r.json().status === 'ok',
  });

  configureFaults(0);

  const success = payment(uniqueOrderId());

  configureFaults(1);

  const failure = payment(uniqueOrderId());

  check(success, {
    'Metrics success request returns 201': (r) => r.status === 201,
  });

  check(failure, {
    'Metrics failure request returns 500': (r) => r.status === 500,
  });

  const metrics = http.get(`${BASE_URL}/metrics`);

  check(metrics, {
    'Metrics endpoint returns 200': (r) => r.status === 200,

    'HTTP 201 counter exists': (r) => {
      return r.body.includes('payment_requests_total{http_status="201"}');
    },

    'HTTP 500 counter exists': (r) => {
      return r.body.includes('payment_requests_total{http_status="500"}');
    },

    'Processing duration histogram bucket exists': (r) => {
      return r.body.includes('payment_processing_duration_seconds_bucket');
    },

    'Processing duration histogram count exists': (r) => {
      return r.body.includes('payment_processing_duration_seconds_count');
    },
  });

  configureFaults(0);
}

// --------------------------------------------------
// MAIN EXECUTION
// --------------------------------------------------

export default function () {
  console.log('====================================');
  console.log('STARTING PAYMENT INTEGRATION TESTS');
  console.log('====================================');

  testSuccessAndPersistence();
  testFaultAndRecovery();
  testPercentageAndValidation();
  testLatency();
  testIdempotency();
  testHealthAndMetrics();

  console.log('====================================');
  console.log('PAYMENT TESTS FINISHED');
  console.log('====================================');
}
