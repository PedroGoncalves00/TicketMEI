"""Teste de integração real: via Gateway, compra PENDING -> RabbitMQ -> Notification."""
import json
import time
import urllib.error
import urllib.request

GATEWAY = 'http://localhost:8000'
NOTIFICATION = 'http://localhost:8003'


def request(url, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type':'application/json'} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    status, events = request(f'{GATEWAY}/events')
    assert status == 200 and events, f'Eventos invalidos {status}'
    status, order = request(f'{GATEWAY}/orders', 'POST', {
        'customer_id':'ci-customer', 'event_id': events[0]['id'],
        'quantity':2, 'email':'ci@example.com',
    })
    assert status == 202 and order['status'] == 'PENDING', (status, order)
    assert float(order['total_amount']) == 2 * float(events[0]['price_eur'])
    status, details = request(f"{GATEWAY}/orders/{order['id']}")
    assert status == 200 and details['id'] == order['id']
    status, _ = request(f'{GATEWAY}/orders', 'POST', {
        'customer_id':'ci-customer','event_id': events[0]['id'],'quantity':5,'email':'ci@example.com',
    })
    assert status == 422, f'Quantidade >4 devia ser rejeitada: {status}'
    for attempt in range(60):
        status, sent = request(f"{NOTIFICATION}/notifications/{order['id']}")
        if status == 200:
            assert sent['status'] == 'SENT'
            print('OK: Order PENDING -> RabbitMQ -> Notification SENT', order['id'])
            break
        time.sleep(1)
    else:
        raise AssertionError('Notification nao enviou a confirmacao em 60 segundos')
    for port in (8000, 8001, 8002, 8003):
        with urllib.request.urlopen(f'http://localhost:{port}/metrics', timeout=5) as resp:
            assert resp.status == 200
    with urllib.request.urlopen('http://localhost:15692/metrics', timeout=5) as resp:
        assert resp.status == 200
    print('OK: metricas HTTP de quatro servicos e RabbitMQ')

if __name__ == '__main__':
    main()
