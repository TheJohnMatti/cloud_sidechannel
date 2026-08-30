# Decisions log

Newest first. Each entry: date, decision, rationale, who.

## 2026-08-30 — Project kickoff

- **Scope = hyperscaler revenue nowcast.** Target the cloud-segment revenue surprise
  of AMZN (AWS, primary), MSFT (Azure growth %), GOOGL (Google Cloud). The
  GPU-scarcity cross-asset index is deferred to Phase 4+. — John
- **Active-probe budget ceiling = < $100 / month**, enforced in code with fail-closed
  behaviour. Tier-0 (free) signals run from day one. — John
- **Repo = `~/code/cloud_sidechannel`, private on GitHub.** — John
- **Storage = DuckDB + parquet** to start; promote to ClickHouse/Timescale only if
  volume forces it. — Claude proposed, John to confirm.

## Open questions (blocking future phases)

| # | Question | Blocks | Owner |
|---|---|---|---|
| 1 | Consensus data source for revenue-surprise target (Visible Alpha / Bloomberg / hand-collected / Koyfin / Estimize) | Phase 4 | John |
| 2 | Separate AWS account for probes vs sub-account/OU | Phase 2 | John |
| 3 | Tier-1 probe region basket (proposed: us-east-1, us-west-2, eu-west-1, ap-southeast-2) | Phase 2 | John |
| 4 | Where in-region collectors run (Lambda/EventBridge vs existing GH Action vs small VM) | Phase 1 | John |
| 5 | How public is the output (private forever vs published research / data product) | Phase 6 | John |
| 6 | AWS-only until the model works, or weight Azure/GCP signals from the start | Phase 3 | John |
| 7 | Which third-party spend panels (Ramp, Vantage, …) publish a usable cloud breakout, at what freq/cost | Phase 2–3 | John |
| 8 | Satellite: free Sentinel-2 only, or budget Planet for key DC campuses | Phase 3 | John |
| 9 | Backfill effort (Wayback / transcript reconstruction) — Phase 3 task or later | Phase 3–4 | John |
| 10 | Model per-region revenue via any disclosure, or keep region as a pooled fixed effect | Phase 3 | John |

See [LABELS.md §10](LABELS.md#10-open-data-sourcing-questions) and
[TECHNIQUES.md](TECHNIQUES.md) for context on 7–10.
