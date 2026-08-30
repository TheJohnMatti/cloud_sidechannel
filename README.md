# cloud_sidechannel

Cloud side-channel analysis: nowcast **hyperscaler cloud-segment revenue surprise**
(AWS / Azure / GCP) from the observable behaviour of their elasticity primitives —
spot prices, spot placement scores, capacity errors, and resource-launch latency —
measured as an ordinary paying customer.

This is **alternative data**, not an attack: we read only our own account's API
responses and run only our own workloads. Comparable in kind to satellite
parking-lot counts. Not investment advice.

## Status

Phase 0 — design. See **[docs/DESIGN.md](docs/DESIGN.md)** for the full plan,
thesis, risks, and phased roadmap. Decisions log: [docs/DECISIONS.md](docs/DECISIONS.md).

## The core bet

```
cloud demand ↑ → utilization nears the managed ceiling → launch latency,
capacity errors and spot prices move in observable ways → and billed
consumption (segment revenue) grows with the same demand.
```

A high-frequency panel of capacity metrics should lead the quarterly print — and
especially the surprise vs. sell-side consensus.

Biggest risk: **cold-start data**. We have zero history and the target has ~4
observations per year. The Tier-0 collector runs from day one to start the clock;
expect 6–8 quarters of pre-registered paper predictions before the model is trusted.

## Layout

```
src/csc/
  collectors/   Tier-0 pollers (spot, placement score, pricing, RSS) + Tier-1 probes
  storage/      parquet ingest + DuckDB rollups
  factors/      weekly factor construction
  nowcast/      MIDAS / DFM mixed-frequency models
scripts/        one-off backfill + ops
docs/           DESIGN.md, DECISIONS.md
```

## Dev

```bash
uv venv && uv pip install -e '.[dev,nowcast]'
.venv/bin/python -m pytest
```
