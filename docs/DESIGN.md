# cloud_sidechannel — DESIGN

> Nowcast hyperscaler **cloud-segment revenue surprise** from the observable behaviour of
> AWS / Azure / GCP elasticity primitives, measured as an ordinary paying customer.

Status: **Phase 0 (design)**. This doc is the decision record. John drives decisions;
open questions are collected in [Decisions](#decisions--open-questions) and in
`docs/DECISIONS.md`.

---

## 1. Thesis

**Signal chain**

```
aggregate cloud demand ↑
   → datacenter utilization rises toward the provider's managed ceiling
   → provisioning / elasticity primitives degrade in observable ways
        (launch latency ↑, InsufficientInstanceCapacity ↑, spot price ↑,
         spot placement score ↓, GPU capacity unavailable)
   → billed consumption (cloud-segment revenue) grows with that same demand
```

If the middle of that chain is measurable at useful frequency and resolution, a
high-frequency panel of capacity metrics should **lead** the quarterly revenue print
and, more usefully, the **surprise vs. sell-side consensus**.

**This is alternative data, not an attack.** We are a paying customer running our own
workloads and reading our own API responses. Comparable in kind to satellite
parking-lot counts or credit-card panels. No MNPI. Not investment advice.

### Tradeable targets

| Ticker | Segment line | Target variable | Notes |
|---|---|---|---|
| **AMZN** | "AWS" net sales | YoY growth surprise vs consensus | Clean single line. Large share of AMZN operating income. Stock reacts hard to AWS beat/miss. **Primary.** |
| **MSFT** | Azure (inside "Intelligent Cloud") | Azure revenue-growth-% surprise | No clean Azure $ disclosed — only a growth %. Management gives cc growth guidance and "capacity constrained" color. |
| **GOOGL** | "Google Cloud" | Revenue + operating-income surprise | Clean segment since 2021. Smaller, faster-growing. |

Chosen scope (2026-08-30): **Hyperscaler revenue nowcast**, all three names, AWS primary.
GPU-scarcity cross-asset index is a Phase 4+ extension, not the initial target.

### Why it might *not* work — confounds to design against

1. **Capacity is actively managed.** Providers target a utilization band and add
   capacity continuously. Signal may be smoothed away except under genuine stress.
   → Mitigation: treat "constrained / not constrained" as a first-class **binary/ordinal**
   signal per (region, service, week); don't over-rely on continuous latency deltas.
2. **Revenue ≠ instantaneous utilization.** Billed consumption and provisioning
   pressure are different derivatives of demand. → Mitigation: MIDAS/DFM models that
   learn the lead/lag; include level *and* change features.
3. **Supply shocks mimic demand shocks.** A GPU shortage produces the same latency
   signal with a different revenue implication (scarcity → pricing power, so partly a
   feature). → Mitigation: separate compute families; track on-demand price changes and
   new-capacity announcements as supply-side controls.
4. **Attribution gap.** "Utilization trending up" → "revenue beats consensus by X" is a
   *second* model with its own error. → Mitigation: predict direction first, magnitude
   second; report calibrated intervals.
5. **Provider-side noise.** A/B experiments, control-plane deploys, regional events.
   → Mitigation: measurement hygiene (§4), robust aggregation, multi-region redundancy.
6. **ToS / account risk.** Rapid create/destroy capacity probing is an abusive API
   pattern even for a paying account. → Mitigation: cost + rate governor as a
   first-class component (§6); conservative schedules; never probe faster than a
   plausible bursty customer.

### Prior art to review in Phase 0

- CloudHarmony / Cloudlook historical cloud-performance datasets
- Academic: EC2 co-residency & performance-variability papers ("Hey, You, Get Off of My
  Cloud"; "A Measurement Study of Server Utilization…"); spot-price modelling papers
- Netflix / Gvisor / cloud-perf engineering blogs on launch latency
- Semianalysis, Datadog "State of…" reports, cloud-cost tooling vendors (Vantage,
  CloudZero) for GPU-scarcity ground truth
- Sell-side "AWS tracker" notes (what proxies do analysts already use?)

---

## 2. Signal sources — tiered by cost

Budget ceiling for active probing: **< $100 / month** (decision 2026-08-30).
Tier 0 is free and runs from day one to **start the historical clock**.

### Tier 0 — free, zero infra, start collecting immediately

| Source | Cadence | What it tells us |
|---|---|---|
| EC2 **spot price history** (`describe-spot-price-history`) | 5–15 min | Demand pressure per instance-type × AZ. ~90d API lookback → must persist now. |
| **Spot Placement Score** (`get-spot-placement-scores`) | hourly | AWS's own 1–10 capacity score for a target capacity, per region. Free, high-signal. |
| On-demand **price list** (Pricing API / bulk JSON) | daily | Price changes, new instance types, deprecations = supply-side events. |
| **RSS / "What's New"** feeds (AWS, Azure Updates, GCP release notes) | hourly | New region/AZ/service launches; capacity-block announcements. |
| **Azure region restrictions** (portal data / `az` quota APIs on our sub) | daily | Which regions/families Azure won't let new subs into = hard constraint flag. |
| Provider **status pages / health RSS** | 5 min | Exclude incident windows from analysis. |
| GCP zone capacity via cheap `describe`/dry-run calls | hourly | `ZONE_RESOURCE_POOL_EXHAUSTED` patterns. |

### Tier 1 — cheap active probes (fits < $100/mo)

Footprint kept minimal: ARM / t-class / smallest sizes, sub-minute lifetimes,
aggressive teardown, a handful of regions.

| Probe | Method | Metric | Est. cost |
|---|---|---|---|
| **Fargate / ECS task launch** | `RunTask` → poll to `RUNNING` → stop | provision latency, `Capacity*` errors | ~$0 (per-second, tiny task) |
| **Lambda cold start** | invoke fresh version, measure init | cold-start ms, concurrency ramp slope | cents |
| **EC2 on-demand launch** | `RunInstances` smallest type → `running` → terminate | launch latency, `InsufficientInstanceCapacity` rate | a few $/mo at low cadence |
| **EBS / ENI attach** | attach to a probe instance, time it | control-plane latency | negligible |

Target: a few regions (us-east-1, us-west-2, eu-west-1, ap-southeast-2), a rotating
subset of instance families, every 1–3 hours. Exact schedule tuned to the budget.

### Tier 2 — GPU capacity probing (deferred; likely > $100/mo)

p4/p5 / capacity-block availability checks, Azure ND-series allocation failures.
Highest signal value, but real cost. Revisit after Tier 0/1 prove out, or find a
free-ish check (e.g. capacity-block *offering* queries without launching).

### Multi-cloud

AWS first (best APIs, primary target). Azure and GCP collectors added in Phase 2 once
the AWS pipeline is proven. Same data model.

---

## 3. Data model

The observation cube:

```
key:    (provider, region, az, service, resource_class, ts)
value:  { provision_latency_ms, error_code, error_rate, spot_price_usd,
          placement_score, price_usd, availability_bool, sample_n }
```

- `resource_class` = normalized family/size (e.g. `ec2:m7i.large`, `fargate:0.25vcpu`,
  `lambda:512mb`, `ec2:p5.48xlarge`).
- Raw observations → append-only parquet partitioned by `provider/dt`.
- Rollups: hourly → daily → **weekly panel** of engineered factors (§5).
- Store: **DuckDB + parquet** locally to start (zero ops, great for panel analytics).
  Promote to ClickHouse/Timescale only if volume demands.

---

## 4. Measurement hygiene

Latency has many additive components; we must separate them.

- **Baseline subtraction:** every probe cycle also measures a no-op control-plane call
  (`DescribeРegions` etc.) to net out API/network RTT from the collector's location.
- **Collector placement:** run probes *in-region* (EventBridge-scheduled Lambda per
  region) so measured latency is control-plane + data-plane, not WAN.
- **Clocks:** NTP-synced hosts; record both client-observed and, where available,
  service-reported timestamps.
- **Decomposition logged per probe:** `api_rtt`, `accepted→provisioning`,
  `provisioning→ready`, `ready→usable`.
- **Exclusions:** drop samples overlapping provider incident windows (status RSS) and
  our own collector errors.
- **Redundancy:** ≥2 independent collector identities per region where feasible;
  disagreement is itself a data point.
- **Calendar controls:** hour-of-day, day-of-week, month-end, region-local holidays,
  known AWS event windows (re:Invent, Prime Day) as model regressors.

---

## 5. Factor construction & nowcast model

### Weekly factors (per provider, some also per region)

- Spot premium: `spot / on_demand`, level and 4-week change, cap-weighted across
  families.
- Placement-score index: mean and share-below-threshold.
- Capacity-error rate: `InsufficientInstanceCapacity` / attempts, EWMA.
- Launch-latency z-score vs trailing 12-week seasonal baseline.
- GPU sub-index (when Tier 2 exists): p5/ND availability, capacity-block lead time.
- Supply controls: count of new-capacity announcements, on-demand price cuts.
- Breadth: fraction of (region × family) cells flagged constrained.

Reduce the region×family panel with PCA / a small dynamic factor model → 2–4 latent
"cloud tightness" factors per provider.

### Target & alignment

- Target: segment revenue **YoY growth**, and **surprise** = actual − consensus
  (consensus source TBD — Visible Alpha / Bloomberg / hand-collected from sell-side
  notes; see decisions).
- Mixed frequency: weekly factors → quarterly target. Use **MIDAS regression** and a
  **bridge/DFM** with ragged-edge handling (the Fed-nowcasting toolkit). `statsmodels`
  has DFM; MIDAS via `statsmodels` sandbox or a small custom implementation.
- Ragged edge: produce a nowcast that updates every week within the quarter as data
  arrives, and a final pre-print estimate.

### The cold-start problem (biggest risk)

We have **zero history** and the target has ~4 obs/year.

- **Start Tier 0 now** — every week of delay is a permanently lost observation.
- **Backfill** what exists: spot-price archives (3rd-party), CloudHarmony-era datasets,
  dated earnings-call "capacity constrained" quotes as weak labels, Datadog/Semianalysis
  time series.
- **Bridge via public monthly proxies** where possible.
- **Pre-register** each quarter: a timestamped, hashed prediction (direction + interval
  for each of AWS/Azure/GCP surprise) committed to the repo before the print. Score it.
- Expect **6–8 quarters** before the model is trustworthy. Until then: paper only.

### Evaluation

- Primary: directional hit-rate on surprise sign, and CRPS of the interval forecast.
- Benchmark against: naive (last quarter's surprise), consensus-is-right (zero
  surprise), and a simple spot-premium-only model.
- Economic: hypothetical event-study P&L holding a straddle / directional position into
  each print, after costs. Reported, not traded, until the track record exists.

---

## 6. Systems architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Collectors (per region)                                      │
│   • Tier-0 pollers: spot price, placement score, pricing,     │
│     RSS, status  ── run on schedule (EventBridge → Lambda)    │
│   • Tier-1 probes: Fargate/Lambda/EC2 launch timers           │
│         │                                                     │
│         ▼  raw events (JSON)                                  │
│  Ingest → append-only parquet  (S3 or local)                  │
│         │                                                     │
│         ▼                                                     │
│  DuckDB rollup jobs  →  hourly / daily / weekly panels        │
│         │                                                     │
│         ▼                                                     │
│  Factor builder (Python)  →  weekly factor table              │
│         │                                                     │
│         ▼                                                     │
│  Nowcast model (MIDAS / DFM)  →  quarterly prediction + CI    │
│         │                                                     │
│         ▼                                                     │
│  Dashboards (Grafana / static HTML)  +  pre-registered log    │
└──────────────────────────────────────────────────────────────┘
```

### Cost & rate governor — first-class component

- Hard monthly budget (`< $100`) enforced in code: `budget_state.json` tracks
  spend-to-date (from Cost Explorer + a local estimate); probes check remaining budget
  before launching and **fail closed**.
- Per-service rate caps; jittered schedules; global kill switch (`STOP` file / SSM
  parameter).
- Every probe has a **guaranteed teardown** path (finally-block + a sweeper Lambda that
  terminates anything tagged `csc:probe` older than N minutes).
- AWS Budgets alert + anomaly detection as backstop.
- Tag everything `project=csc`. Separate AWS account (or at least separate OU) so blast
  radius and billing are clean.

### Deployment

- Local Mac: dev, backfill, model, dashboards.
- AWS: only the in-region collectors (cheap, scheduled). IaC via a single CDK/Terraform
  stack per region.
- Secrets: least-privilege IAM role per collector; no long-lived keys in repo.
- Env: **uv + `.venv`**, `.venv/bin/python -m ...` (house convention).

---

## 7. Phased plan

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0 — Feasibility** | This doc + prior-art review + consensus-data source picked + target definitions locked | We can name the exact number we're predicting and where truth comes from |
| **1 — Tier-0 collector** | Spot / placement-score / pricing / RSS pollers → parquet → DuckDB; running on schedule; basic dashboard | ≥2 weeks of clean multi-region data landing daily; **clock started** |
| **2 — Tier-1 probes + governor** | Fargate/Lambda/EC2 launch timers in situ; cost governor enforcing budget; Azure + GCP Tier-0 | 4 weeks of probe data; spend < $100/mo verified; zero orphaned resources |
| **3 — Data platform** | Weekly factor table; PCA/DFM tightness factors; anomaly detection; region heatmaps | Factors reproduce known 2023–25 capacity crunches from backfilled data |
| **4 — Nowcast model** | MIDAS + DFM vs backfilled history; weekly-updating nowcast; pre-registration workflow | First pre-registered prediction committed before an earnings print |
| **5 — Validation** | 6–8 quarters of scored, pre-registered predictions; event-study P&L report | Directional hit-rate and CRPS beat all benchmarks out-of-sample |
| **6 — Act** | Trade it, or package the capacity-intelligence data feed | Track record supports risk capital, or a buyer exists |

Rough calendar: Phase 1 in ~2 weeks of build; Phases 2–4 over ~2 months; Phase 5 is
inherently ~2 years of wall-clock (that's the cold-start tax).

---

## 8. Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11, uv/`.venv` | house convention |
| Cloud SDK | boto3; azure-mgmt-*; google-cloud-compute | native APIs |
| Storage | DuckDB + parquet (→ ClickHouse if needed) | zero-ops columnar analytics |
| Scheduling | EventBridge → Lambda (in-cloud); cron/launchd (local) | cheap, in-region |
| IaC | Terraform or CDK, one stack per region | reproducible teardown |
| Modelling | statsmodels (DFM), scikit-learn, custom MIDAS | mixed-frequency nowcasting |
| Dashboards | Grafana or static HTML report | fast |
| Governor | custom Python + AWS Budgets | budget is a hard constraint |

---

## 9. Legal / ethical posture

- We use only our own account's API responses and our own workloads. No probing of
  third-party systems, no security scanning, no ToS-grey co-tenancy inference.
- Respect API rate limits; stay within the behaviour envelope of a normal bursty
  customer.
- Output is a market view derived from public-by-construction observations. Not MNPI.
- Nothing here is investment advice; any trading is the operator's own decision and
  risk.

---

## Decisions & open questions

Locked:
- **2026-08-30** Scope = hyperscaler revenue nowcast (AWS/Azure/GCP), AWS primary; GPU
  index deferred to Phase 4+.
- **2026-08-30** Active-probe budget ceiling = **< $100/month**, enforced in code.
- **2026-08-30** Repo = `~/code/cloud_sidechannel`, **private**.
- **2026-08-30** Storage starts as DuckDB + parquet.

Open (need John):
1. **Consensus data source** for the revenue surprise target — Visible Alpha?
   Bloomberg? hand-collected sell-side? free-ish (Koyfin / Zacks / estimize)? This
   gates Phase 4.
2. **Separate AWS account** for `csc` probes, or a sub-account/OU under the existing
   one? (Strongly prefer isolated for billing + blast radius.)
3. **Region set** for Tier-1 probes — the 4 proposed (use1, usw2, euw1, apse2) or a
   different basket?
4. **Where do the in-region collectors run** — pure AWS Lambda/EventBridge, or piggyback
   on the existing auto_sniper GH Action / a small VM?
5. **How public** is this project's output — private forever, or eventually a published
   research writeup / data product?
6. Do we want a **GCP/Azure-as-signal** weighting from the start, or AWS-only until the
   model works?
