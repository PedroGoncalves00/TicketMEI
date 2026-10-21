# TicketMEI — Parte I / Fase 1

Projeto da unidade curricular **Sistemas Distribuídos 2026/2027 (MEI)**. Implementação da primeira fase do TicketMEI com **API Gateway, Catalog, Docker Compose, Prometheus, Grafana, testes k6 e GitHub Actions**.

> **Prazo da Fase 1 no enunciado: 21/10/2026.** Este repositório corresponde à Fase 1; as fases seguintes acrescentarão Order, Notification, RabbitMQ, Redis, Kubernetes e ArgoCD.

## Iniciar em 3 comandos

Instalar e iniciar **Docker Desktop** (com Linux containers). Abrir o terminal na pasta onde se encontra `docker-compose.yml` e executar:

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

O primeiro `docker compose up` pode demorar a descarregar imagens e instalar dependências.

**Endereços locais** (no computador que está a executar o Docker):

| Endereço | Descrição |
|---|---|
| `http://localhost:8000/events` | Eventos via API Gateway (público) |
| `http://localhost:8000/events/evt-101` | Detalhes de um evento via Gateway |
| `http://localhost:8000/metrics` | Métricas Prometheus do Gateway |
| `http://localhost:8001/events` | Catalog diretamente (para diagnóstico) |
| `http://localhost:8001/events/evt-101` | Detalhes via Catalog |
| `http://localhost:8001/metrics` | Métricas Prometheus do Catalog |
| `http://localhost:9090/targets` | Targets e estado no Prometheus |
| `http://localhost:3000` | Grafana — `admin` / `admin`, configuração local inicial |

No Grafana, abrir **Dashboards → TicketMEI → TicketMEI - Fase 1**. O datasource e o dashboard são criados **automaticamente** por provisioning. O password padrão deve ser alterado se o ambiente não for estritamente local; em ambiente de demonstração, pode-se configurar `GRAFANA_ADMIN_PASSWORD` num ficheiro `.env` não versionado.

Para produzir tráfego e popular as séries:

```powershell
docker compose --profile testing run --rm k6 run smoke-test.js
```

Esperar cerca de 1 minuto para as métricas com `rate(...[1m])` estarem estáveis. O ficheiro `k6/load-test.js`, fornecido pela professora, permanece disponível para o teste de carga longo (**5 min 30 s**, até **500 VUs**):

```powershell
docker compose --profile testing run --rm k6 run load-test.js
```

**Atenção:** o teste longo pode exigir bastantes recursos e falhar limiares de latência num portátil; não é a mesma coisa que a verificação curta da pipeline.

Para parar sem apagar dados:

```powershell
docker compose down
```

## Estrutura do projeto

```text
TicketMEI_Fase1/
├── api-gateway/
│   ├── main.py                  # Pessoa 2 — proxy e métricas
│   ├── Dockerfile
│   └── requirements.txt
├── catalog/
│   ├── main.py                  # Pessoa 1 — consultas e métricas
│   ├── data/events.json         # Ficheiro fornecido pela professora
│   ├── Dockerfile
│   └── requirements.txt
├── prometheus/prometheus.yml    # Pessoa 3
├── grafana/
│   ├── dashboards/dashboard1.json
│   └── provisioning/
│       ├── datasources/prometheus.yml
│       └── dashboards/default.yml
├── k6/
│   ├── load-test.js             # Teste original da professora
│   └── smoke-test.js            # Verificação curta da pipeline
├── tests/
│   ├── test_catalog.py          # Pessoa 1
│   └── test_gateway.py          # Pessoa 2
├── .github/workflows/phase1.yml # Pessoa 2 — validação automatizada
├── docker-compose.yml           # Pessoa 3
├── pytest.ini
├── .env.example
├── .gitignore
└── GUIA_COMPLETO_FASE1.md      # Procedimentos dos três elementos
```

## Divisão de tarefas

| Pessoa | Área | Ficheiros a assumir e validar |
|---|---|---|
| **1 — Catalog** | Dados, API, estados HTTP, métricas, testes | `catalog/`, `tests/test_catalog.py` |
| **2 — Gateway e CI** | Proxy HTTP, tratamento de falhas, métricas, testes, Actions | `api-gateway/`, `tests/test_gateway.py`, `.github/workflows/phase1.yml` |
| **3 — DevOps/observabilidade** | Docker, Prometheus, Grafana, k6, integração, guia | `docker-compose.yml`, `prometheus/`, `grafana/`, `k6/`, `README.md`, `GUIA_COMPLETO_FASE1.md`, `pytest.ini`, `.gitignore`, `.env.example` |

Para as contribuições aparecerem no GitHub, **cada pessoa deve criar a sua branch, compreender e validar os seus ficheiros, fazer os seus commits e abrir o respetivo Pull Request**. Consultar o guia completo.

## Exemplos de testes

PowerShell no Windows:

```powershell
curl.exe -i http://localhost:8000/events
curl.exe -i http://localhost:8000/events/evt-101
curl.exe -i http://localhost:8000/events/nao-existe
curl.exe http://localhost:8000/metrics
curl.exe http://localhost:8001/metrics
```

Resultados esperados: HTTP `200` para os dois primeiros, HTTP `404` para evento inexistente, resposta Prometheus nos endpoints `/metrics`. No Prometheus, em `/targets`, os jobs `api-gateway` e `catalog` devem aparecer **UP**.

Consulta útil no Prometheus (RPS):

```promql
sum(rate(gateway_requests_total[1m]))
```

Latência p95:

```promql
histogram_quantile(0.95, sum(rate(gateway_request_duration_seconds_bucket[1m])) by (le))
```

Latência p99: substituir `0.95` por `0.99`. Taxa de erro 4xx+5xx, em percentagem:

```promql
100 * (sum(rate(gateway_requests_total{http_status=~"[45].."}[1m])) or vector(0)) / clamp_min(sum(rate(gateway_requests_total[1m])), 0.000001)
```

## Testes automáticos Python

Para correr fora do Docker, com Python 3.12 ou compatível instalado:

```powershell
python -m pip install -r catalog/requirements.txt -r api-gateway/requirements.txt pytest
python -m pytest -q tests
```

No GitHub, `.github/workflows/phase1.yml` executa os testes Python, valida Docker Compose, inicia os serviços, verifica `/events` e `/metrics` e corre o smoke test do k6. O GitHub Actions apenas ficará verde quando **todas as partes estiverem reunidas no repositório**.

## Notas técnicas

- O `Catalog` lê `catalog/data/events.json`, sem partilhar armazenamento com outros serviços.
- A comunicação entre Gateway e Catalog é **HTTP síncrona**; o cliente não precisa de contactar diretamente o Catalog.
- O Gateway reencaminha também `/events/{id}`, como extensão útil ao mínimo explícito da Fase 1.
- A API expõe `/health` para healthchecks dos contentores, sem contabilizar essas consultas como tráfego de eventos.
- As métricas usam nomes/labels exigidos no enunciado; o dashboard mostra RPS, p95, p99 e erros.
- Os painéis adicionais de CPU e memória utilizam métricas do **processo Python**, evitando depender de mounts especiais do cAdvisor em Windows.
- O cAdvisor fornecido como exemplo na infraestrutura original existe como **perfil opcional** em Compose (`--profile monitoring-extra`), mas **não é recolhido pelo Prometheus na configuração base**. É opcional nesta implementação e não é necessário para os três painéis exigidos.
- Credenciais localmente exemplificativas (`admin` / `admin`) **não devem ser utilizadas em produção**.

## Registo de utilização de IA (obrigatório segundo o enunciado)

Foi utilizado **ChatGPT (OpenAI)** para auxiliar a organização do trabalho, a preparação de código inicial dos serviços API Gateway e Catalog, os testes automatizados, os ficheiros de infraestrutura, o dashboard de monitorização e este guia. Os membros do grupo devem rever, executar e validar todas as contribuições antes de as entregar. Os ficheiros de eventos e o teste de carga original foram fornecidos pela professora e reaproveitados. O enunciado identifica o Google Gemini como ferramenta usada na preparação dos materiais iniciais.
