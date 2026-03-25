# Runbook

## ApiHigh5xxErrorRate
Symptome: le taux de reponses 5xx depasse 5% sur 5 minutes.

Actions:
1. Ouvrir le dashboard N2 et identifier les routes dominantes en erreur.
2. Verifier si l'augmentation vient d'un endpoint unique ou global.
3. Correlation deployment: verifier dernier release/feature flag.
4. Si regression confirmee: rollback ou desactivation ciblée.
5. Verifier retour a la normale sur les panels `Erreur 5xx (%)` et `SLI succes 24h`.

## HostMemoryPressure
Symptome: memoire utilisee > 90% pendant 10 minutes.

Actions:
1. Identifier le container/processus principal consommateur.
2. Verifier fuite memoire (croissance monotone).
3. Ajuster limite memoire ou scaler horizontalement.
4. Planifier action durable (profilage, cache policy, tuning runtime).

## TargetDown
Symptome: une target n'est plus scrapee (`up == 0`) depuis 2 minutes.

Actions:
1. Verifier l'etat du container (`docker compose ps`).
2. Tester endpoint local (`/metrics` ou port exporter).
3. Verifier connectivite reseau entre Prometheus et target.
4. Verifier configuration `prometheus.yml` (target/port/job).
5. Confirmer le retour de `up=1`.
