# Guia passo a passo — TicketMEI Fase 1 (3 pessoas)

Este documento descreve **o que cada pessoa deve fazer, a partir do zero, para executar e entregar a Fase 1**. Todos os ficheiros de implementação estão incluídos no projeto e organizados por responsabilidade.

## Passo 0 — O que é pedido

Da Fase 1 do enunciado: dois microsserviços (`API Gateway` e `Catalog`), endpoints `/events` e `/metrics`, dados em `events.json`, Docker Compose, Prometheus, Grafana e painel RPS/p95/p99/erros. O requisito RNF4 especifica validação automatizada por GitHub Actions e k6 nas fases 1/2. **Prazo indicado: 21/10/2026.** Não desenvolver Order, Notification, RabbitMQ, rate limiter, ArgoCD nem Kubernetes nesta fase.

## Passo 1 — Preparar o computador (todas as pessoas)

**Windows 10/11**: instalar **Docker Desktop** a partir de <https://www.docker.com/products/docker-desktop/>. Ativar o backend WSL2/Linux containers quando solicitado e abrir o Docker Desktop, esperando até aparecer que o motor está a correr. Instalar **Git** (<https://git-scm.com/downloads>) e, opcionalmente, **Visual Studio Code** (<https://code.visualstudio.com/>). Para executar testes Python sem Docker, instalar Python 3.12. O código dos serviços corre dentro de imagens Python 3.12, pelo que Python local é opcional.

Abrir **PowerShell** e verificar:

```powershell
docker --version
docker compose version
docker info
git --version
```

Se `docker info` indicar erro de daemon, abrir/reiniciar Docker Desktop; não continuar enquanto o motor não arrancar. Todos os comandos seguintes devem ser executados na pasta que contém `docker-compose.yml`, salvo indicação em contrário.

## Passo 2 — Preparar os materiais (todas as pessoas)

1. Descarregar e extrair **TicketMEI_Fase1_Completa.zip**. Confirmar a presença de `catalog`, `api-gateway`, `grafana`, `prometheus`, `k6` e `docker-compose.yml`.
2. O conteúdo já contém o código da Fase 1, não sendo necessário transcrever manualmente os ficheiros.
3. Abrir a pasta extraída no VS Code (File → Open Folder) para consultar os ficheiros.
4. Cada elemento deverá **rever os seus ficheiros**, executar os testes que lhe dizem respeito e ser capaz de explicar as suas decisões.

## Passo 3 — Pessoa 1: Catalog

### 3.1 — Ficheiros sob responsabilidade

- `catalog/data/events.json`: quatro eventos do ficheiro fornecido pela professora, incluindo `evt-101`.
- `catalog/main.py`: aplicação FastAPI.
- `catalog/requirements.txt`: bibliotecas necessárias.
- `catalog/Dockerfile`: imagem Docker Python 3.12.
- `tests/test_catalog.py`: testes da API e das métricas.

### 3.2 — Compreender o comportamento

1. Ao iniciar, `main.py` lê `data/events.json`.
2. `GET /events` devolve o array dos quatro eventos (`200 OK`).
3. `GET /events/evt-101` devolve o evento correspondente (`200 OK`).
4. `GET /events/nao-existe` devolve `404 Not Found`.
5. `GET /metrics` devolve o formato do Prometheus, incluindo `catalog_requests_total` com etiquetas `endpoint,http_status` e o histograma `catalog_request_duration_seconds`.
6. `GET /health` destina-se apenas ao healthcheck Docker.

### 3.3 — Testar o Catalog isoladamente com Docker

Na raiz do projeto completo:

```powershell
docker compose up -d --build catalog
docker compose ps
```

Visitar, num navegador ou via PowerShell:

```powershell
curl.exe -i http://localhost:8001/events
curl.exe -i http://localhost:8001/events/evt-101
curl.exe -i http://localhost:8001/events/nao-existe
curl.exe http://localhost:8001/metrics
```

Confirmar que a lista contém quatro objetos, o identificador do detalhe é `evt-101`, o evento inexistente devolve `404`, e o `/metrics` contém as métricas acima. Se precisar de logs:

```powershell
docker compose logs --tail=100 catalog
```

### 3.4 — Testes Python (opcional, mas recomendado)

Na raiz do projeto:

```powershell
python -m pip install -r catalog/requirements.txt httpx==0.28.1 pytest
python -m pytest -q tests/test_catalog.py
```

A pessoa 1 deve publicar no GitHub **a pasta `catalog/` e `tests/test_catalog.py`**, com um commit próprio, conforme o Passo 6.

## Passo 4 — Pessoa 2: API Gateway + GitHub Actions

### 4.1 — Ficheiros sob responsabilidade

- `api-gateway/main.py`, `requirements.txt` e `Dockerfile`.
- `tests/test_gateway.py`.
- `.github/workflows/phase1.yml`.

### 4.2 — Compreender o comportamento

1. O Gateway publica `GET /events` na porta `8000`.
2. O pedido é encaminhado via HTTP síncrono para `http://catalog:8001/events`, através do DNS interno do Compose.
3. A resposta JSON do Catalog volta ao cliente mantendo o código HTTP.
4. O Gateway também publica `GET /events/{id}` para permitir consultar detalhes.
5. Se o Catalog devolver `404`, o Gateway mantém `404`. Se a ligação falhar, o Gateway devolve `502`.
6. O Gateway publica `/metrics`, incluindo `gateway_requests_total` (etiquetas `method,endpoint,http_status`) e `gateway_request_duration_seconds` (etiqueta `endpoint`).
7. No GitHub, o workflow executa testes Python, compila imagens, inicia Docker Compose, verifica endpoints e corre `k6/smoke-test.js`.

### 4.3 — Testar a integração com Catalog

Na raiz do projeto:

```powershell
docker compose up -d --build catalog api-gateway
docker compose ps
```

Testar:

```powershell
curl.exe -i http://localhost:8000/events
curl.exe -i http://localhost:8000/events/evt-101
curl.exe -i http://localhost:8000/events/nao-existe
curl.exe http://localhost:8000/metrics
```

Esperado: `200`, `200`, `404` e resposta de métricas, respetivamente. O Gateway não usa `localhost:8001` dentro do contentor: usa o nome do serviço `catalog`, resolvido por DNS interno do Docker Compose.

Para verificar falha do Catalog (apenas quando estiverem a testar, não durante os testes k6):

```powershell
docker compose stop catalog
curl.exe -i http://localhost:8000/events
docker compose start catalog
```

Esperado enquanto o Catalog está parado: `502 Bad Gateway`. Reiniciar o Catalog no fim.

### 4.4 — Testes Python

```powershell
python -m pip install -r catalog/requirements.txt -r api-gateway/requirements.txt pytest
python -m pytest -q tests/test_gateway.py
```

A pessoa 2 deve publicar no GitHub **`api-gateway/`, `tests/test_gateway.py` e `.github/workflows/phase1.yml`**, com commit próprio. O workflow deve ser integrado **depois** dos serviços e da infraestrutura, para poder validar tudo.

## Passo 5 — Pessoa 3: Docker, Prometheus, Grafana e k6

### 5.1 — Ficheiros sob responsabilidade

- `docker-compose.yml`: serviços `catalog`, `api-gateway`, `prometheus`, `grafana` e perfis opcionais `testing` (k6) e `monitoring-extra` (cAdvisor).
- `prometheus/prometheus.yml`: recolha periódica de métricas de Gateway e Catalog.
- `grafana/provisioning/datasources/prometheus.yml`: registo automático do datasource.
- `grafana/provisioning/dashboards/default.yml`: importação automática do dashboard.
- `grafana/dashboards/dashboard1.json`: dashboard adaptado ao datasource local.
- `k6/load-test.js`: teste original da professora, conservado.
- `k6/smoke-test.js`: teste rápido para a pipeline.
- `README.md`, `GUIA_COMPLETO_FASE1.md`, `pytest.ini`, `.gitignore`, `.env.example`.

### 5.2 — Testar Docker Compose

Na raiz do projeto:

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

Esperado: quatro serviços principais em execução; `catalog` e `api-gateway` devem apresentar `healthy` depois do arranque. O `k6` não é arrancado por defeito porque é um serviço de teste; o cAdvisor também é opcional para evitar problemas de mounts no Windows.

### 5.3 — Verificar o Prometheus

Abrir <http://localhost:9090/targets>. Esperado: os jobs `api-gateway` e `catalog` com estado **UP**. Se aparecer DOWN, aguardar alguns segundos e verificar logs:

```powershell
docker compose logs --tail=100 prometheus
```

Em <http://localhost:9090> escrever e executar:

```promql
up
```

Devem surgir séries com valor `1` para os dois serviços. Depois testar:

```promql
sum(rate(gateway_requests_total[1m]))
```

Sem pedidos recentes pode estar a zero; executar o smoke test do passo 5.5.

### 5.4 — Verificar o Grafana

1. Abrir <http://localhost:3000>.
2. Na instalação local inicial, entrar com utilizador `admin` e password `admin` (poderá ser pedido para alterar a password).
3. Abrir **Dashboards → TicketMEI → TicketMEI - Fase 1**.
4. Confirmar que existem os painéis: **Gateway Throughput (RPS)**, **API Gateway Latency (p95 & p99)**, **Gateway HTTP Error Rate**, CPU e memória dos processos.
5. Confirmar o datasource Prometheus: **Connections → Data sources → Prometheus**, com URL de acesso interno `http://prometheus:9090`.
6. Fazer pedidos `/events` ou executar o teste curto e aguardar até cerca de um minuto pelas taxas com janela `[1m]`.
7. Se o dashboard não aparecer, procurar erros em `docker compose logs grafana` e confirmar as pastas de provisioning.

A medição da taxa de erros considera HTTP 4xx e 5xx. Para gerar erros controlados:

```powershell
curl.exe -i http://localhost:8000/events/nao-existe
```

### 5.5 — Executar k6

**Teste rápido de integração**, cerca de 12 segundos:

```powershell
docker compose --profile testing run --rm k6 run smoke-test.js
```

Esperado: verificações `GET /events` e `GET /events/evt-101` bem-sucedidas, com checks positivos e thresholds satisfeitos em condições normais.

**Teste de carga do ficheiro original** (opcional antes da entrega, pode demorar 5m30 e impor 500 VUs):

```powershell
docker compose --profile testing run --rm k6 run load-test.js
```

Este teste impõe p95 inferior a 200 ms e taxa de erro inferior a 1%; não se deve afirmar que passou sem executar e registar resultados. Pode falhar em máquinas com poucos recursos sem implicar incorreção funcional dos endpoints.

### 5.6 — cAdvisor opcional

O enunciado fornece cAdvisor nos materiais, mas os objetivos expressos para esta fase concentram-se no RPS/latência/erros de Gateway e Catalog. A implementação base usa métricas de processos para os painéis adicionais de CPU/memória. Em Linux ou quando os volumes funcionarem no Docker Desktop:

```powershell
docker compose --profile monitoring-extra up -d cadvisor
```

Abrir <http://localhost:8080>. **O Prometheus base não recolhe cAdvisor**; se a docente pedir explicitamente as métricas de contentores, adicionar `cadvisor:8080` ao `prometheus/prometheus.yml` e testar a configuração do host.

## Passo 6 — GitHub e colaboração com três pessoas

Este passo deve ser feito **com as contas GitHub reais das três pessoas**. Não é possível publicá-lo por outra pessoa sem permissão. Cada um tem de usar a sua própria conta para existirem três contribuições atribuídas corretamente.

### 6.1 — Criar o repositório (pessoa 3)

1. Entrar em <https://github.com/new>.
2. Criar o repositório público `ticketmei-fase1`, inicializando apenas com um README simples.
3. Em **Settings → Collaborators**, convidar os outros dois membros e, quando apropriado, a docente, conforme a orientação da disciplina.
4. Partilhar com a equipa a URL HTTPS, por exemplo `https://github.com/UTILIZADOR/ticketmei-fase1.git` (substituir pelo URL real).
5. Cada membro configura o nome e o email usados no Git (o email deve ser o associado à respetiva conta GitHub):

```powershell
git config --global user.name "NOME DO MEMBRO"
git config --global user.email "EMAIL_ASSOCIADO_A_CONTA_GITHUB"
```

### 6.2 — Pessoa 3 publica primeiro a infraestrutura

Criar uma pasta local vazia e clonar a URL real:

```powershell
git clone https://github.com/UTILIZADOR/ticketmei-fase1.git
cd ticketmei-fase1
git checkout -b feat/infraestrutura
```

Copiar **da pasta extraída do projeto entregue** para dentro do repositório clonado (preservando os diretórios): `docker-compose.yml`, `prometheus/`, `grafana/`, `k6/`, `README.md`, `GUIA_COMPLETO_FASE1.md`, `pytest.ini`, `.gitignore` e `.env.example`.

Depois:

```powershell
git add .
git commit -m "feat: docker compose prometheus grafana e k6"
git push -u origin feat/infraestrutura
```

No GitHub, abrir Pull Request `feat/infraestrutura` → `main` e fazer merge. **Ainda não tentar arrancar todos os serviços do repositório**: faltam os ficheiros de Catalog e Gateway.

### 6.3 — Pessoa 1 publica o Catalog

Num computador ou pasta de trabalho próprios:

```powershell
git clone https://github.com/UTILIZADOR/ticketmei-fase1.git
cd ticketmei-fase1
git checkout -b feat/catalog
```

Copiar da pasta de projeto entregue **somente** `catalog/` e `tests/test_catalog.py`. Criar a pasta `tests` no clone, se ainda não existir.

```powershell
git add catalog tests/test_catalog.py
git commit -m "feat: catalog de eventos com metricas e testes"
git push -u origin feat/catalog
```

Abrir e integrar Pull Request `feat/catalog` → `main`. Verificar na aba **Commits** que a pessoa 1 está associada ao commit.

### 6.4 — Pessoa 2 publica Gateway e workflow em último lugar

```powershell
git clone https://github.com/UTILIZADOR/ticketmei-fase1.git
cd ticketmei-fase1
git checkout -b feat/api-gateway-ci
```

Copiar da pasta de projeto entregue **somente** `api-gateway/`, `tests/test_gateway.py` e `.github/workflows/phase1.yml`, preservando a estrutura:

```powershell
git add api-gateway tests/test_gateway.py .github/workflows/phase1.yml
git commit -m "feat: gateway metricas e pipeline github actions"
git push -u origin feat/api-gateway-ci
```

Abrir Pull Request `feat/api-gateway-ci` → `main` e integrar. Desta vez o workflow de CI pode executar corretamente porque os serviços e a infraestrutura já foram publicados. Na aba **Actions**, verificar os jobs `unit-tests` e `docker-and-k6`. Se algum falhar, abrir os logs, corrigir na branch e submeter novo commit; não declarar conclusão enquanto não estiver verde.

> **Nota:** esta ordem simplifica a integração. Se preferirem trabalhar em paralelo, cada pessoa cria uma branch e a equipa resolve eventuais conflitos antes do merge final.

## Passo 7 — Validação final conjunta (todos)

Depois dos três Pull Requests, cada pessoa pode confirmar o projeto completo numa cópia atualizada:

```powershell
git checkout main
git pull origin main
docker compose config
docker compose up -d --build
docker compose ps
```

Abrir e registar os resultados:

1. <http://localhost:8000/events> — deve devolver os quatro eventos.
2. <http://localhost:8000/events/evt-101> — deve devolver o detalhe.
3. <http://localhost:8000/events/nao-existe> — deve devolver `404`.
4. <http://localhost:8000/metrics> — deve conter `gateway_requests_total` e o histograma.
5. <http://localhost:8001/metrics> — deve conter `catalog_requests_total` e o histograma.
6. <http://localhost:9090/targets> — `api-gateway` e `catalog` em **UP**.
7. <http://localhost:3000> — dashboard Grafana visível e povoado após gerar tráfego.
8. `docker compose --profile testing run --rm k6 run smoke-test.js` — thresholds/checks de sucesso.
9. GitHub → **Actions** — workflow final verde.
10. GitHub → **Commits / Pull requests** — contribuições identificáveis de três pessoas.

É aconselhável guardar **capturas de ecrã** desses resultados para a demonstração, embora o enunciado da Fase 1 exija principalmente o repositório e o ambiente local funcional.

## Passo 8 — Entrega

O enunciado pede **repositório público no GitHub**, partilhado entre elementos e docente, com pasta por serviço, `prometheus.yml`, `docker-compose.yml`, implementação local no Docker Desktop e métricas no Prometheus/Grafana. Partilhar com a professora o URL **real** do repositório. Confirmar que o README declara a utilização de IA e a distribuição do trabalho. Para a demonstração posterior, confirmar que os três sabem mostrar a sua componente e interpretar o dashboard.

## Passo 9 — Quando algo corre mal

**Erro ao executar `docker` ou conexão ao engine:** abrir Docker Desktop, verificar WSL2 e selecionar Linux containers.

**Porta já ocupada (`8000`, `8001`, `3000`, `9090`):** parar o programa que está a usar essa porta ou alterar o lado esquerdo do mapeamento no `docker-compose.yml` (e corrigir os URLs públicos de teste, se aplicável).

**API Gateway devolve `502`:** confirmar se `catalog` está healthy: `docker compose ps` e `docker compose logs catalog`; o destino interno é `http://catalog:8001`, não `localhost:8001`.

**Prometheus apresenta DOWN:** confirmar as URLs dos exporters e a rede Docker, depois consultar `docker compose logs prometheus`.

**Dashboard está vazio:** gerar pedidos, esperar pela janela de 1 minuto, verificar targets UP e a variável uid de datasource fixada como `prometheus`.

**Password Grafana não corresponde:** o volume `grafana_data` mantém credenciais da primeira execução. Não apagar volumes sem perceber que perde os dados locais; usar o mecanismo de reset de password Grafana ou escolher um ambiente limpo.

**Testes k6 falham sob 500 VUs:** o teste original é pesado. Executar primeiro o `smoke-test.js`, verificar recursos do sistema, estado de containers e métricas. Reportar resultados reais sem os ocultar.

**GitHub Actions falha:** abrir a execução para descobrir o job e o comando que falhou; verificar primeiro se as três contribuições já foram integradas no `main`.

## Estado da verificação inicial

O código foi preparado com base no enunciado e nos materiais da professora. Num ambiente Python local, foram executados **5 testes automatizados com sucesso** e foi testada a comunicação real Gateway → Catalog com HTTP `200`, `404` e endpoints de métricas HTTP `200`. **A execução em Docker Desktop, Prometheus/Grafana e GitHub Actions requer validação no computador/repositório do grupo**, pois essas plataformas não foram executadas no ambiente de preparação.
