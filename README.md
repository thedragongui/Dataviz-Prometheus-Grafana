# Supervision exploitable en production — Prometheus + Grafana (+ Loki)

## 1) Objectif

Ce dépôt fournit une stack de supervision **reproductible** (Docker Compose) pour une API HTTP et son hôte, avec **alerting** et **corrélation logs** (bonus).

Questions couvertes :

- Le service est-il **UP** ?
- Quel est le **taux d’erreur** (4xx/5xx) ?
- Quelle est la **latence p95** ?
- Y a-t-il de la **saturation** (CPU / RAM / disque) ?
- Lors d’un pic : **métriques ↔ logs** (Loki)

## 2) Architecture

| Service | Rôle |
|--------|------|
| `demo-api` | API Flask + métriques Prometheus + logs JSON (fichier partagé) |
| `prometheus` | Collecte et règles (recording + alertes) |
| `alertmanager` | Routage / groupement des alertes |
| `node-exporter` | Métriques machine (montages `/proc`, `/sys`, `/` hôte) |
| `grafana` | Dashboards N1/N2 + datasources Prometheus / Alertmanager / Loki |
| `loki` | Stockage de logs |
| `promtail` | Envoi des lignes de `access.jsonl` vers Loki |

Fichiers utiles :

- `docker-compose.yml`
- `monitoring/prometheus/prometheus.yml`
- `monitoring/prometheus/rules/recording.yml`, `alerts.yml`
- `monitoring/alertmanager/alertmanager.yml`
- `monitoring/loki/loki-config.yaml`, `monitoring/promtail/promtail.yml`
- `monitoring/grafana/dashboards/n1-overview.json`, `n2-diagnostic.json`
- `docs/runbook.md`

## 3) Démarrage / arrêt

**Prérequis** : Docker + Docker Compose v2

**Démarrer** :

```bash
docker compose up -d --build
```

**Arrêter** :

```bash
docker compose down
```

**Arrêter et supprimer les volumes** (Prometheus / Grafana / Loki / logs) :

```bash
docker compose down -v
```

## 4) Accès

| Outil | URL | Identifiants |
|-------|-----|----------------|
| API | http://localhost:8000 | — |
| Métriques | http://localhost:8000/metrics | — |
| Prometheus | http://localhost:9090 | — |
| Alertmanager | http://localhost:9093 | — |
| Grafana | http://localhost:3000 | `admin` / `admin` |
| Loki (API) | http://localhost:3100 | — |

## 5) SLI / SLO

### SLI

1. **Disponibilité applicative (succès non-5xx)**  
   Mesure : part des requêtes sans réponse 5xx sur une fenêtre glissante.

2. **Latence p95**  
   Mesure : 95e percentile de `demo_http_request_duration_seconds` (histogramme).

3. **Complément — taux d’erreurs 5xx**  
   Mesure : `5xx / total` sur 5 minutes (aligné avec l’alerte métier).

### SLO

- **Objectif** : **≥ 99,5 %** de succès (non-5xx) sur **24 h** glissantes (fenêtre adaptée au labo ; en production on viserait souvent **30 jours** pour le même objectif).

### Justification des seuils

- **99,5 %** : compromis courant pour un service HTTP de criticité « standard » (tolère une courte dégradation sans masquer un incident prolongé).
- **Alerte 5xx > 5 % sur 5 min** : symptôme métier fort, avec `for: 5m` pour limiter le bruit sur des pics très brefs.
- **Mémoire > 90 % pendant 10 min** : saturation **durable** (évite d’alerter sur un pic transitoire).
- **Target down 2 min** : indique un problème de disponibilité ou de collecte, pas un simple glitch réseau.

## 6) PromQL — requêtes documentées

Méthode : **table → validation labels / unités → graphe** ; fenêtres **5m** pour les `rate()` ; `clamp_min(..., 0.001)` pour éviter division par zéro sur trafic faible.

Les variables Grafana `$service`, `$instance`, `$node`, `$env` filtrent les séries.

1. **UP**

```promql
max(up{job="demo-api",service=~"$service",instance=~"$instance",env=~"$env"})
```

2. **Trafic (req/s)**

```promql
sum(rate(demo_http_requests_total{service=~"$service",instance=~"$instance",env=~"$env"}[5m]))
```

3. **Erreurs 5xx (%)**

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

7. **Top endpoints (req/s)**

```promql
topk(5, sum by (route) (rate(demo_http_requests_total{service=~"$service",instance=~"$instance",env=~"$env"}[5m])))
```

8. **Saturation disque — espace libre (%)** *(complément)*

```promql
100 * (
  1 - (
    node_filesystem_avail_bytes{instance=~"$node",env=~"$env",fstype!="tmpfs",mountpoint="/"}
    /
    node_filesystem_size_bytes{instance=~"$node",env=~"$env",fstype!="tmpfs",mountpoint="/"}
  )
)
```

Les **recording rules** dans `recording.yml` préagrègent certains ratios (succès, latence p95, CPU) pour des requêtes plus légères si vous les réutilisez dans d’autres dashboards.

## 7) LogQL (bonus Loki) — corrélation pic erreurs / latence

Les logs applicatifs sont des **lignes JSON** dans `/var/log/app/access.jsonl`, étiquetées `job=demo-api`, `env=lab`.

1. **Filtrer les réponses erreur serveur** (après un pic 5xx sur Grafana) :

```logql
{job="demo-api"} | json | status >= 500
```

2. **Filtrer les requêtes lentes** (après un pic de latence p95) :

```logql
{job="demo-api"} | json | latency_ms > 500
```

Dans **Grafana → Explore → Loki**, ouvrir la datasource Loki et coller ces requêtes en les alignant sur la **même plage horaire** que le dashboard N1/N2.

## 8) Dashboards Grafana

### N1 — `API Supervision N1` (`/d/n1overview/...`)

- **6–10 panneaux** : UP, % 5xx, p95, req/s, séries trafic / erreurs, CPU+RAM, top routes, top latences p95 par route.
- **Variables** : `service`, `instance` (API), `node` (node_exporter), `env`.
- **Drilldown** :
  - lien vers le dashboard **N2 Diagnostic** (variables conservées) ;
  - lien vers **Explore Loki** (requête préremplie sur `{job="demo-api"}`).

### N2 — `API Diagnostic N2` (`/d/n2diagnostic/...`)

- Répartition par classe HTTP, top endpoints, tables top trafic / top 5xx, SLI succès 24h, requêtes en cours, débit par méthode+route.
- **Panneau Logs** : flux Loki avec `| json` pour corréler avec les pics vus en Prometheus.

## 9) Alerting actionnable

Fichier : `monitoring/prometheus/rules/alerts.yml`

| Alerte | Type | Contenu actionnable |
|--------|------|----------------------|
| `ApiHigh5xxErrorRate` | Symptôme métier | `summary`, `message`, `what_to_do`, lien dashboard N2, lien `docs/runbook.md` |
| `HostMemoryPressure` | Saturation | Mémoire hôte > 90 % **10 min** ; lien N1 + runbook |
| `TargetDown` | Qualité de collecte | `up == 0` **2 min** sur cibles critiques ; lien N1 + runbook |

**Alertmanager** : `monitoring/alertmanager/alertmanager.yml` — routage minimal (`receiver: default`), groupement par `alertname`, `service`, `severity`, `env`.

## 10) Simulation d’incident

**Charge nominale** :

```bash
while true; do curl -s "http://localhost:8000/api/items" > /dev/null; done
```

**Incident erreurs 5xx** :

```bash
while true; do curl -s "http://localhost:8000/api/flaky?failure_rate=0.9" > /dev/null; done
```

**Incident latence** :

```bash
while true; do curl -s "http://localhost:8000/api/items?delay_ms=900&failure_rate=0.0" > /dev/null; done
```

**Diagnostic** : N1 (état global) → N2 (routes / SLI) → Explore Loki (requêtes ci-dessus) + **Alertmanager** si l’alerte a été déclenchée.

## 11) Structure du dépôt

```
app/                    # API + Dockerfile
docs/runbook.md         # Procédures incident
monitoring/
  alertmanager/
  grafana/              # provisioning + JSON dashboards
  loki/
  promtail/
  prometheus/
docker-compose.yml
```
