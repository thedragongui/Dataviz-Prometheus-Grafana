# Supervision exploitable en production - Prometheus + Grafana

## 1) Objectif
Ce repository fournit une stack de supervision reproductible pour une API HTTP et son environnement.

Questions couvertes:
- Service UP / DOWN
- Taux d'erreurs
- Latence p95
- Saturation CPU/RAM
- Drilldown de diagnostic (N1 -> N2)

## 2) Architecture
Composants de la stack (Docker Compose):
- `demo-api` (Flask instrumentee Prometheus)
- `prometheus`
- `alertmanager`
- `node-exporter`
- `grafana`

Fichiers principaux:
- `docker-compose.yml`
- `monitoring/prometheus/prometheus.yml`
- `monitoring/prometheus/rules/recording.yml`
- `monitoring/prometheus/rules/alerts.yml`
- `monitoring/alertmanager/alertmanager.yml`
- `monitoring/grafana/dashboards/n1-overview.json`
- `monitoring/grafana/dashboards/n2-diagnostic.json`

## 3) Demarrage / Arret
Prerequis:
- Docker + Docker Compose v2

Demarrer:
```bash
docker compose up -d --build
```

Arreter:
```bash
docker compose down
```

Arreter + supprimer volumes:
```bash
docker compose down -v
```

## 4) Acces outils
- API demo: http://localhost:8000
- Metrics API: http://localhost:8000/metrics
- Prometheus: http://localhost:9090
- Alertmanager: http://localhost:9093
- Grafana: http://localhost:3000 (`admin` / `admin`)

## 5) SLI / SLO
### SLI retenus
1. **Disponibilite applicative (success ratio)**
   - Mesure: part des requetes non-5xx
   - Indicateur: `1 - (5xx / total)`

2. **Latence p95**
   - Mesure: 95e percentile de `demo_http_request_duration_seconds`

3. **Taux d'erreurs 5xx**
   - Mesure: `5xx / total` sur fenetre 5m

### SLO
- **SLO principal:** `>= 99.5%` de succes (non-5xx) sur 24h glissantes (fenetre labo)
- Equivalence production recommandee: meme objectif sur 30 jours

### Justification rapide des seuils
- 99.5% est un compromis robuste pour un service HTTP interne/externe de criticite standard.
- Alerte 5xx a 5% sur 5m: seuil assez sensible pour detecter un incident reel sans sur-bruit.
- Memoire > 90% sur 10m: filtre les pics courts et cible une saturation durable.

## 6) PromQL (requêtes documentees)
Methodologie appliquee: `table -> validation labels/unites -> graphe`.

1. **UP**
```promql
max(up{job="demo-api",service=~"$service",instance=~"$instance",env=~"$env"})
```

2. **Trafic req/s**
```promql
sum(rate(demo_http_requests_total{service=~"$service",instance=~"$instance",env=~"$env"}[5m]))
```

3. **Taux erreurs 5xx (%)**
```promql
100 * (
  sum(rate(demo_http_requests_total{service=~"$service",instance=~"$instance",status_class="5xx",env=~"$env"}[5m]))
  /
  clamp_min(sum(rate(demo_http_requests_total{service=~"$service",instance=~"$instance",env=~"$env"}[5m])), 0.001)
)
```

4. **Latence p95 (ms)**
```promql
1000 * histogram_quantile(
  0.95,
  sum by (le) (
    rate(demo_http_request_duration_seconds_bucket{service=~"$service",instance=~"$instance",env=~"$env"}[5m])
  )
)
```

5. **Saturation CPU (%)**
```promql
100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle",instance=~"$node",env=~"$env"}[5m])))
```

6. **Saturation RAM (%)**
```promql
100 * (1 - (node_memory_MemAvailable_bytes{instance=~"$node",env=~"$env"} / node_memory_MemTotal_bytes{instance=~"$node",env=~"$env"}))
```

7. **Topk endpoints (req/s)**
```promql
topk(5, sum by (route) (rate(demo_http_requests_total{service=~"$service",instance=~"$instance",env=~"$env"}[5m])))
```

## 7) Dashboards Grafana
### Dashboard principal N1 (`API Supervision N1`)
- 9 panels (1 ecran = 1 message)
- Variables: `service`, `instance`, `node`, `env`
- KPIs: UP, erreur 5xx, p95, req/s
- Sante infra: CPU/RAM
- Top endpoints
- Drilldown: lien vers `API Diagnostic N2`

### Dashboard N2 (`API Diagnostic N2`)
- Vue d'analyse incident
- Repartition trafic par classes HTTP
- Top endpoints en trafic
- Top endpoints en taux 5xx
- Top latences p95 par endpoint
- SLI succes 24h

## 8) Alerting actionnable
Règles dans `monitoring/prometheus/rules/alerts.yml`:

1. `ApiHigh5xxErrorRate` (symptome metier)
- Condition: 5xx > 5% sur 5m
- Severity: `critical`
- Annotation: message, quoi faire, lien dashboard N2, runbook

2. `HostMemoryPressure` (saturation)
- Condition: RAM utilisee > 90% sur 10m
- Severity: `warning`
- Annotation: action de diagnostic capacitaire

3. `TargetDown` (qualite de collecte)
- Condition: `up == 0` pendant 2m
- Severity: `critical`
- Annotation: checks service/scrape/reseau

## 9) Simulation d'incident (demo restitution)
### Charge nominale
```bash
# Bash
while true; do curl -s "http://localhost:8000/api/items" > /dev/null; done
```

### Incident erreurs 5xx
```bash
# Bash
while true; do curl -s "http://localhost:8000/api/flaky?failure_rate=0.9" > /dev/null; done
```

### Incident latence
```bash
# Bash
while true; do curl -s "http://localhost:8000/api/items?delay_ms=900&failure_rate=0.0" > /dev/null; done
```

### Equivalent PowerShell
```powershell
while ($true) { Invoke-WebRequest -UseBasicParsing "http://localhost:8000/api/flaky?failure_rate=0.9" | Out-Null }
```

## 10) Conseils de restitution (8 minutes)
- 3 min: contexte, architecture, choix SLI/SLO
- 3 min: demo N1 (etat global) -> N2 (diagnostic)
- 2 min: incident simule + parcours d'analyse + alerte associee
