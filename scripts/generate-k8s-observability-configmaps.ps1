$ErrorActionPreference = "Stop"

kubectl create configmap prometheus-config `
  -n ticketmei `
  --from-file=prometheus.yml=prometheus/prometheus.yml `
  --dry-run=client -o yaml |
  Set-Content -Encoding utf8 k8s/prometheus-config.yaml

kubectl create configmap grafana-datasource `
  -n ticketmei `
  --from-file=prometheus.yml=grafana/provisioning/datasources/prometheus.yml `
  --dry-run=client -o yaml |
  Set-Content -Encoding utf8 k8s/grafana-datasource.yaml

kubectl create configmap grafana-dashboard-provider `
  -n ticketmei `
  --from-file=default.yml=grafana/provisioning/dashboards/default.yml `
  --dry-run=client -o yaml |
  Set-Content -Encoding utf8 k8s/grafana-dashboard-provider.yaml

kubectl create configmap grafana-dashboards `
  -n ticketmei `
  --from-file=dashboard1.json=grafana/dashboards/dashboard1.json `
  --from-file=dashboard2.json=grafana/dashboards/dashboard2.json `
  --dry-run=client -o yaml |
  Set-Content -Encoding utf8 k8s/grafana-dashboards.yaml

Write-Host "ConfigMaps Kubernetes gerados em k8s/."
