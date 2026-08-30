# LABELS — turning capacity measurements into a revenue nowcast

> Companion to [DESIGN.md](DESIGN.md) and [TECHNIQUES.md](TECHNIQUES.md).
> This is the crux of the system. The sensing layer is an engineering problem;
> **the labelling strategy is what makes the project tractable in months instead of years.**

---

## 1. The reframe: don't regress on revenue

The naive framing — *features = capacity probes, label = quarterly cloud-segment
revenue* — gives you **~4 labelled points per year per provider**. Any model with more
than a handful of parameters overfits immediately, and you cannot validate out-of-sample
for years. This is the project's central risk.

The fix is to change what the label *is*.

**Model "cloud demand / capacity tightness" as an unobserved monthly (or weekly) latent
state.** Many indicators load onto it — our probes, spot prices, upstream supplier
revenue, network traffic, infrastructure-footprint growth, and (infrequently) reported
revenue. A **mixed-frequency dynamic factor model (DFM)** estimated by the Kalman filter
handles this natively:

- The latent factor `f_t` evolves as a smooth state process (e.g. AR(1)/AR(2)).
- Each indicator `y_i` is `y_{i,t} = λ_i · f_t + (controls) + ε_{i,t}`, observed at its
  own frequency, with a "ragged edge" (different indicators arrive with different lags).
- Quarterly revenue is **just one more indicator** — an infrequent one — loading on the
  same factor.

The consequence: the factor is pinned down by the *dense* indicators. Reported revenue
only has to identify **one loading coefficient `λ_revenue`** (plus a scale). Eight
quarters is enough for that, because everything else in the model is already identified
by data you can collect at high frequency starting now.

**Prediction target for trading** = the surprise:
`surprise = actual_segment_growth − consensus_estimate`, produced as a distribution that
updates every week within the quarter as new high-frequency data arrives.

This is the same machinery central banks use to nowcast GDP from dozens of
higher-frequency series (Giannone–Reichlin–Small; the "ragged edge" literature; MIDAS
regression as the single-equation cousin).

---

## 2. Four tiers of label / indicator

| Tier | What | Frequency | Available |
|---|---|---|---|
| 1 | Internal / self-supervised targets | daily–weekly | **now** |
| 2 | Monthly public data upstream of / parallel to cloud demand | monthly | **now** |
| 3 | Continuous infrastructure-footprint signals | daily | **now** |
| 4 | Quarterly leading indicators + backfilled history | quarterly | now (history) / ongoing |

---

## 3. Tier 1 — Internal / self-supervised (thousands of points, immediately)

These need **no external labels** and de-risk ~80 % of the project — the sensing layer,
factor structure, seasonality, anomaly detection, measurement hygiene.

| Self-supervised target | What it validates |
|---|---|
| **Predict next week's tightness from this week's** (per region × family) | Factor dynamics, seasonality model, that the probes are internally consistent. |
| **Predict spot-price / spot-premium moves from launch-latency + ICE probes** | That the *active* probes lead a continuous market-priced measure of the same capacity state. If they do, the probes work — with zero revenue data. |
| **Predict discrete `InsufficientInstanceCapacity` events from leading latency creep** | Turns rare events into a dense classification problem; calibrates the early-warning value of `pending`-duration. |
| **Cross-region / cross-family coherence** | ~75 region-units × dozens of families → the tightness *dynamics* get ~100× the data of the 3 provider-level series. Region and family enter as fixed effects; the demand-response relationship is pooled. |
| **Predict provider supply-response** (see Tier 3 events) from prior tightness | The tightness → capex-relief lag, estimated from dozens of events per quarter. |

Deliverable by end of Phase 1: a validated weekly "cloud tightness factor" per provider,
with known seasonality and confidence bands — **before any revenue label is attached.**

---

## 4. Tier 2 — Monthly public data (the granular usage metrics)

Higher-frequency data that moves with cloud demand exists — mostly in the **supply
chain** and in **third-party billing panels**.

### 4a. Server-ODM monthly revenue — the best granular label

Taiwan law requires listed companies to report **monthly revenue by the 10th of the
following month.** The companies that physically build hyperscaler servers:

| Company | Ticker | Relevance |
|---|---|---|
| **Wiwynn** | 2299.TW | **~100 % hyperscaler datacenter** (Microsoft, Meta, AWS). The purest monthly hyperscaler-capex tracker that exists. |
| Quanta | 2382.TW | Large cloud/AI server segment (also laptops — need segment split from quarterly). |
| Wistron / Wiwynn parent | 3231.TW | Cloud + AI servers. |
| Hon Hai (Foxconn) | 2317.TW | AI-server ramp; huge and noisy. |
| Gigabyte | 2376.TW | AI/HPC servers. |
| Super Micro | SMCI (US) | Quarterly, but frequently pre-announces. |

**Usage:** MoM and YoY growth of Wiwynn (and a Quanta/Wistron cloud composite) enter
the DFM as monthly indicators loading on the tightness factor with a **lead** — capex
spend precedes the revenue it generates by 1–2 quarters, and *follows* the demand
tightness that triggered it. The model learns the lead/lag.

### 4b. Upstream silicon — monthly

| Source | Cadence | Link |
|---|---|---|
| **TSMC monthly revenue** | ~10th of month | HPC/datacenter now > 50 % of mix. |
| SK Hynix / Samsung / Micron HBM commentary | quarterly + conference | HBM is the GPU-supply bottleneck. |
| NVIDIA datacenter revenue | quarterly | Huge tell, but quarterly — Tier 4. |

### 4c. Third-party cloud-spend panels — demand side

| Source | Cadence | Notes |
|---|---|---|
| **Ramp / Brex business-spending indices** | monthly | FinOps/expense platforms sitting on real customer AWS/Azure/GCP invoice data. Check what cloud breakout is public. |
| **Vantage Cloud Cost Report** | ~quarterly | EDP discount trends, instance-type popularity, provider mix shifts. |
| CloudZero / Finout / Cloudability commentary | ad hoc | Directional. |
| **Datadog "State of…" reports** | semi-annual | Container/ARM/serverless/GPU adoption — structural priors, not timing. |

### 4d. Network traffic — continuous

| Source | Notes |
|---|---|
| **Cloudflare Radar** (free API) | Traffic volume/trends by ASN. AWS = AS16509 / AS14618; Microsoft = AS8075; Google = AS15169. Aggregate traffic ≈ aggregate activity. |
| Internet-exchange public stats (DE-CIX, AMS-IX, LINX), PeeringDB changes | Cloud-ASN port capacity and peering growth. |

### 4e. Sell-side estimate revisions

Visible Alpha / Estimize / consensus-tracking: the **timestamped drift** of the AWS/Azure
growth consensus is itself a label for "what the market learned this month," useful for
training the *surprise* model and for benchmarking (is our nowcast ahead of consensus
revisions?).

---

## 5. Tier 3 — Continuous infrastructure-footprint signals (free, daily)

These measure the provider's **physical build-out**, which lags demand. Tightness now +
slow footprint growth ⇒ demand outrunning supply ⇒ revenue beat (and pricing power).

| Signal | Source | What it shows |
|---|---|---|
| **AWS `ip-ranges.json`** | published by AWS, frequent updates | Allocated IPv4/IPv6 space per region/service. Net additions = infrastructure expansion. Already tracked by infra watchers; easy to diff daily. |
| **Azure / GCP published IP ranges** | provider JSON/XML | Same idea for the other two. |
| **BGP prefix announcements** from cloud ASNs | RIPE RIS, RouteViews, bgp.tools | New prefixes / new points-of-presence coming online. |
| **Certificate Transparency logs** | crt.sh, Google/Cloudflare CT | New region subdomains and service endpoints appear in CT logs — sometimes *before* official launch. |
| **Satellite imagery of known DC campuses** | Sentinel-2 (free), Planet (paid) | Construction progress at Loudoun County (us-east-1), Council Bluffs, The Dalles, Hillsboro, Dublin, Boydton. The literal "parking-lot count" analogue. Monthly. |
| **Grid / utility data** | Dominion Energy & PJM (N. Virginia), ERCOT (Texas), local IOU filings | Data-center load growth by region; interconnection queue. |
| **Building permits & DC-industry trackers** | Loudoun/Prince William County records; DC Byte, Baxtel, datacenterHawk | Forward capex pipeline, 6–18 months ahead. |
| **Hyperscaler capex guidance** | quarterly earnings + 8-K | Quarterly (Tier 4), but the single most-watched number — our nowcast should be checked against it. |

---

## 6. Tier 4 — Quarterly, but leading or backfillable

### 6a. Leading quarterly disclosures

- **Microsoft Commercial RPO** (remaining performance obligations) and **commercial
  bookings growth** — contracted future revenue, leads recognized Azure revenue.
- **Amazon "AWS backlog"** — disclosed in the 10-Q, same idea.
- **Google Cloud backlog** — disclosed by Alphabet.
- These are quarterly but *forward-looking*, so they sit closer to our signal's horizon
  than trailing revenue does. Use as an intermediate label.

### 6b. Historical reconstruction for training

You cannot backfill the probes. You **can** backfill the *overlapping* features and
train the tightness → revenue mapping on ~30–40 historical quarters:

| Backfillable feature | Source | History |
|---|---|---|
| Spot price series | AWS Data Exchange; 3rd-party archives (some kept full history) | 2015→ |
| Cloud performance benchmarks | CloudHarmony / Cloudlook archives | ~2012–2019 |
| Azure SKU-restriction snapshots | Wayback Machine on Azure docs & status pages | ~2016→ |
| "Capacity constrained" quotes, sometimes region-specific | earnings-call transcripts (dated) | 2016→ |
| Server-ODM & TSMC monthly revenue | company IR sites | 10+ years |
| Cloud-ASN traffic | Cloudflare Radar history; academic IXP datasets | few years |
| Capex, RPO, backlog | 10-Q/10-K history | full |

Train on backfilled features only; run forward with the full probe set. The DFM's
loadings for probe-only features are then identified during the live period, anchored by
the backfill-identified factor.

---

## 7. Fusing the tiers — weak supervision

Two compatible ways to combine noisy indicators into a dense training target:

1. **The DFM latent factor itself** is already a principled fusion — every indicator
   loads on `f_t`, the Kalman filter produces `E[f_t | all data so far]` at weekly
   frequency, and that filtered factor is the "synthetic label."
2. **Snorkel-style label model** as a robustness check: treat each indicator's
   direction (Wiwynn MoM sign, spot-premium change sign, IP-range growth deceleration,
   Radar traffic trend, sell-side revision sign) as a noisy labelling function; a
   generative label model estimates each one's accuracy and correlation and emits a
   probabilistic monthly "cloud demand up/down/flat" label. Agreement with the DFM
   factor is a sanity check.

The **final step** — synthetic monthly demand index → reported quarterly revenue
surprise — is a deliberately tiny model (1–3 parameters: a loading and a scale, maybe a
provider-specific intercept), fit on the handful of real quarters and **re-fit after
every print**. Keeping this layer minimal is what prevents overfitting to 8 points.

---

## 8. Evaluation & discipline

- **Pre-registration:** before each earnings print, commit a timestamped, hashed
  prediction file to the repo — direction + interval for AWS / Azure / GCP surprise,
  plus the driving factors. No post-hoc edits.
- **Metrics:** directional hit-rate on surprise sign; CRPS of the interval forecast;
  lead time vs. consensus revisions.
- **Benchmarks the model must beat out-of-sample:**
  - naive (last quarter's surprise carried forward),
  - consensus-is-right (zero surprise),
  - spot-premium-only single-factor model,
  - Wiwynn-MoM-only model.
- **Economic check:** hypothetical event-study P&L (directional or straddle into the
  print) after costs — reported, never traded, until the track record exists.

---

## 9. Timeline impact

| Milestone | Naive (revenue-only label) | Tiered labelling |
|---|---|---|
| Validated sensing layer + tightness factor | ~1 year | **~6–8 weeks** (Tier 1) |
| Usable monthly demand signal | ~2 years | **~3 months** (Tier 1 + Tier 2) |
| Revenue-surprise calibrated | ~2 years | **~1 year** (backfill + ~4 live quarters) |
| Trusted, pre-registered track record | ~3 years | ~2 years |

The multi-year horizon only applies to *final calibration confidence*, not to having a
usable, improving signal.

---

## 10. Open data-sourcing questions

Tracked in [DECISIONS.md](DECISIONS.md):

1. **Consensus source** for the surprise target — Visible Alpha / Bloomberg /
   hand-collected sell-side / Koyfin / Estimize? Gates the Tier-4 calibration.
2. Which **third-party spend panels** (Ramp, Vantage, …) publish a usable cloud
   breakout, and at what frequency / cost?
3. **Satellite:** free Sentinel-2 only, or budget for Planet on a few key campuses?
4. How much **backfill effort** is worth it — is the Wayback/transcript reconstruction
   a Phase-3 task or a "nice to have later"?
5. Do we model **per-region** revenue via any disclosure, or keep region purely as a
   pooled fixed effect?
