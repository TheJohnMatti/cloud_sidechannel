# cloud_sidechannel

**A documented negative result.** Can you nowcast hyperscaler cloud-segment revenue
(AWS / Azure / GCP) by measuring the providers' own capacity primitives — EC2 spot
prices, launch latency, capacity errors — as an ordinary paying customer?

Short answer after three rounds of testing on real data: **mostly no.** The signal
fired cleanly on exactly one capacity episode (the 2023 generative-AI crunch) and is
noisy, absent, or backwards on the other four in 2018–2025. The one predictive
relationship that survived to significance washes out against a trivial "AI-era"
control.

This repo is the full paper trail: the original design, the feasibility code, the
data, and the write-up of why it doesn't hold up.

Not investment advice. This is alternative-data research — it reads only public data
and (in the original design) one's own cloud-account API responses.

---

## Read this

- **[research/feasibility/FINDINGS.md](research/feasibility/FINDINGS.md)** — the result.
  Three rounds: coarse proxy → self-measured spot premium (n=1 episode) → multi-episode
  test (n=5). Start here.
- **[docs/DESIGN.md](docs/DESIGN.md)** — the original plan (thesis, risks, phased roadmap).
- **[docs/TECHNIQUES.md](docs/TECHNIQUES.md)** — the sensing layer: what to measure, which
  API, what it costs, why it might carry signal.
- **[docs/LABELS.md](docs/LABELS.md)** — the labelling strategy: how to turn capacity
  measurements into a nowcast without waiting years for labelled data (mixed-frequency
  dynamic factor model). Still the most reusable idea here.
- [research/feasibility/DATA_SOURCES.md](research/feasibility/DATA_SOURCES.md) — where to
  get multi-year EC2 spot-price history (scoped so you don't have to).

## The core bet, and where it broke

```
cloud demand ↑ → datacenter utilization nears the managed ceiling →
spot prices / launch latency / capacity errors move observably →
and billed segment revenue grows with the same demand
```

The middle link is real and measurable — the 2023 AI crunch is unmistakable in EC2
spot prices, and it *led* the "Azure capacity constrained" earnings narrative by about
a quarter. But:

- **n = 1.** Across five capacity inflections in 2018–2025, only 2023 produced a clean
  signal. COVID 2020 barely registered; the 2024 H1 re-acceleration moved the signal
  *the wrong way* (tightness and revenue growth decoupled); the 2024–25 broad
  constraint was a slow, noisy grind.
- **The confound.** Premium level entering a quarter predicts next-quarter growth
  acceleration (r ≈ 0.34) — but add an "AI era" dummy and it collapses. The signal adds
  little beyond "the AI upcycle is on."
- **The trade is arguably backwards.** Quarters where spot tightened, the stock
  *underperformed* into earnings (the market treats capacity tightness as a near-term
  capex/margin negative before any revenue benefit).

## Reproduce

```bash
uv venv --python 3.12 && uv pip install pandas numpy statsmodels scikit-learn matplotlib httpx pyarrow

# 1. get the spot-price archives (see DATA_SOURCES.md for URLs)
#    ISI 2018-2023 -> research/feasibility/data/raw/spot-YYYY.tar
#    Pauley 2024-2025 -> research/feasibility/data/raw/pauley/YYYY-MM.tsv.zst
# 2. build the weekly tightness index (streaming, memory-bounded)
.venv/bin/python research/feasibility/build_spot_index.py
# 3. run the tests
.venv/bin/python research/feasibility/analyze.py            # round 1: coarse proxy
.venv/bin/python research/feasibility/analyze_sharpened.py  # rounds 2-3: spot premium
.venv/bin/python research/feasibility/plot_premium.py
```

## Data attribution

- EC2 spot-price history 2018–2023: **ANT Lab / USC-ISI** (Calvin Ardi),
  DOI [10.5281/zenodo.5880792](https://doi.org/10.5281/zenodo.5880792), CC0.
- EC2 spot-price history 2024–2025: **Eric Pauley, UW–Madison**,
  DOI [10.5281/zenodo.14198917](https://doi.org/10.5281/zenodo.14198917), CC-BY-4.0.
- Prices for earnings-day reactions: Yahoo Finance.
- Cloud-segment revenue figures: company filings / press releases (compiled,
  approximate; see the CSV header).

## Status

Shelved. The `src/csc/` package tree is scaffolding from the original design and was
never built out — the feasibility result made it moot. Everything real is under
`research/feasibility/`.
