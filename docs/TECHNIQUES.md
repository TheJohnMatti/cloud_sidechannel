# TECHNIQUES — how we actually measure hyperscaler capacity

> Companion to [DESIGN.md](DESIGN.md). This doc covers the *sensing layer*: what we
> measure, which API does it, what it costs, and why it carries signal.
> Labelling (turning these measurements into a revenue nowcast) is in [LABELS.md](LABELS.md).

## Core principle

We are **not** stress-testing anything. Overloading an instance measures that box's
immediate neighbours at best — not a datacenter — and looks abusive. Running a large
sustained fleet is expensive and gets an account flagged.

The signal lives in **how the provider's allocator and managed services behave**, which
is observable cheaply:

```
aggregate demand ↑
  → datacenter utilization approaches the provider's managed ceiling
  → the placement/allocation service has fewer candidate hosts, searches harder,
    falls back across racks/spine, and eventually refuses
  → observable as: spot price ↑, spot placement score ↓, provisioning latency ↑,
    InsufficientInstanceCapacity rate ↑, managed-service throttle rate ↑
```

Five families of technique, ordered by how much weight they carry.

---

## Family A — Passive: the provider tells on itself

No compute launched. Poll public and account-scoped APIs; persist the series (most have
short lookback, so value accrues from *starting now*). This is roughly **half the total
signal** and runs from day one at **$0**.

### A1. EC2 spot price history — `DescribeSpotPriceHistory`

AWS sets the spot price for each `instance-type × availability-zone` pool from the
supply/demand balance for spare capacity in that pool. Thousands of pools.

- **Metric:** `spot_price / on_demand_price` per pool — a direct "how much slack"
  gauge. Level, 4-week change, and cross-pool breadth.
- **Cadence:** every 5–15 min. Lookback is ~90 days via API, so persistence is the
  whole point.
- **Caveat:** AWS smoothed spot pricing dynamics in late 2017 (removed the bid-based
  spikes). Trends still carry signal; single-tick spikes mean less than pre-2018.

### A2. Spot Placement Score — `GetSpotPlacementScores`

The highest-value passive call. You pass a **target capacity** (e.g. 100 instances or
2 000 vCPUs), a set of instance types or families, and optional region/AZ scope. AWS
returns a **score of 1–10 per region (or per AZ)** = likelihood a Spot request of that
size succeeds now without near-term interruption.

- **Technique — demand curve:** call it repeatedly at escalating target sizes
  (10 / 50 / 200 / 1 000 instances) for the same family. The size at which a region's
  score falls from 9 → 4 is a **capacity-depth reading**, not just a binary.
- **Technique — GPU sub-index:** run the same sweep for `p5`, `p4d`, `g6`, `trn` and
  weight heavily — GPU-serving capacity is the dominant revenue driver in 2026.
- **Cadence:** hourly per configuration. Rate-limited but adequate.
- **Output:** per (region, family, target_size, ts) → score. Track score decay over
  time and breadth of low scores across regions.

### A3. Capacity Blocks for ML — `DescribeCapacityBlockOfferings`

AWS sells GPU capacity as pre-reserved time-boxed blocks. The API returns available
blocks with **start dates and prices**.

- **Metric:** lead time to the nearest available `p5`/`p5e` block per region
  (next-day vs. 3 weeks out), and the price curve.
- **Cadence:** hourly. Free to query.
- **Why:** a pure, unambiguous read on AI-training capacity scarcity.

### A4. On-demand & reserved pricing feed — Price List API / bulk JSON

Price changes are rare and deliberate.

- Cut on previous-gen instances → excess capacity of that generation.
- New instance-type listing / new regional availability → supply addition.
- Savings Plan / RI rate shifts → forward-demand management.
- **Cadence:** daily diff of the full price list.

### A5. Azure explicit capacity signals

Azure is unusually transparent about constraint.

- **`az vm list-skus --location <region>` → `restrictions`**: tells you directly which
  SKUs are `NotAvailableForSubscription` in which zones. A hard constraint flag per
  (region, family, zone).
- **Spot advisor data**: eviction-rate buckets (0–5%, 5–10%, …, 20+%) and price
  history per SKU per region. Eviction rate = demand reclaiming spare capacity.
- **Quota behaviour**: default quota grants shrinking; quota-increase requests routed
  to manual review.
- **Region access**: new subscriptions blocked from selecting certain regions without
  a support ticket.

### A6. GCP signals

- Spot/preemptible pricing (monthly cadence — structural, not high-frequency).
- Dry-run `instances.insert` / describe calls surfacing
  `ZONE_RESOURCE_POOL_EXHAUSTED` per zone.
- Published regional capacity guidance where available.

### A7. Change / announcement feeds

- AWS "What's New" RSS, Azure Updates RSS, GCP release notes — new AZ/region launches,
  "now available in region X" (supply catching up), service GA dates.
- Provider status / health RSS — used to **exclude** incident windows from analysis,
  and as a weak strain indicator (capacity pressure → more brownouts).

### A8. Service-quota grant behaviour

Programmatically request a modest quota increase; measure approval latency and whether
it is auto-approved or routed to a human. Slower / manual = constrained.

---

## Family B — Active: control-plane latency probes

The main active method. When you call `RunInstances` / ECS `RunTask` / Fargate
`RunTask`, the server-side path is:

```
API front-end
  → placement service: find a physical host with room for this shape in this AZ,
    matching tenancy / placement-group / capacity-reservation constraints
  → provision: ENI attach, EBS attach, hypervisor slot allocation
  → state: pending → running
  → (guest OS boot — not the provider's SLA, but we can time it too)
```

**The allocator's search time is the signal.** Near capacity it has fewer candidate
hosts, searches harder, falls back across failure domains, and finally returns
`InsufficientInstanceCapacity` ("ICE"). The **ICE rate across a matrix of
`type × AZ × time`** is the single best active signal; `pending`-duration is its
continuous companion.

### B1. EC2 launch-and-kill probes

- `RunInstances` on the smallest viable type (`t4g.nano`, ~$0.0042/hr, **billed
  per-second**, 60 s minimum). Timestamp `submit → pending → running` with
  millisecond precision. `TerminateInstances` immediately.
- **Cost: a fraction of a cent per probe.**
- **Matrix, not volume:** wide but shallow — a rotating basket of families
  (general / compute / memory / GPU), 2–3 AZs × 4 regions, every 1–3 hours. One tiny
  probe per cell, alive for seconds. Never a sustained fleet.

### B2. Capacity-depth probing via `MinCount`

`RunInstances` with `MinCount = MaxCount = N`. If the AZ can't satisfy `MinCount`, the
call **fails atomically and nothing is billed**.

- So *"is there room for 100 × `c7i.48xlarge` in `us-east-1a` right now?"* is a **free
  probe as long as the answer is no.**
- If the answer is **yes**, you just launched 100 large instances — so cap `N` and the
  type at what you can afford for the ~2 seconds before teardown, or keep the type
  cheap and let `N` be large.
- Escalate `N` until failure to get the same demand-curve depth reading as the Spot
  Placement Score sweep, but for on-demand.

### B3. `CreateFleet` in `instant` mode

Returns synchronously with per-pool fulfilment and detailed per-pool error reasons — a
clean multi-pool capacity snapshot in one call. Still launches what it fills, so cap
`TargetCapacity`.

### B4. Fargate task probes

Cleaner and cheaper than EC2 — no host, AWS owns all placement.

- Time `RunTask → task RUNNING`. Watch for `Capacity is unavailable` /
  `RESOURCE:FARGATE` / `Capacity provider` errors.
- A 0.25-vCPU / 0.5-GB task for 30 s ≈ **$0.0005**.

### B5. Lambda probes

- **Cold start:** publish a fresh function version (or bump a config value to force a
  new execution environment), invoke, read `Init Duration` from the invocation report.
  Cold-start latency ≈ warm-capacity availability in that region.
- **Concurrency ramp:** fire 100+ concurrent invokes; measure how fast concurrency
  scales and when `TooManyRequestsException` / reserved-concurrency throttles hit. The
  ramp slope is a capacity read.
- **Cost:** effectively free.

### B6. Control-plane primitives

EBS volume create + first-attach latency, ENI attach latency, new-VPC provisioning,
security-group propagation delay. Cheap, and they isolate the control plane from the
data plane.

### Azure / GCP equivalents

- Azure: `az vm create` smallest B-series → running → delete; watch for
  `AllocationFailed` / `ZonalAllocationFailed` / `OverconstrainedAllocationRequest`.
- Azure Container Instances: analogous to Fargate probes.
- GCP: `compute.instances.insert` `e2-micro` → running → delete; watch for
  `ZONE_RESOURCE_POOL_EXHAUSTED` / `QUOTA_EXCEEDED`.
- GCP Cloud Run: analogous to Fargate/ACI probes.

---

## Family C — Managed-service capacity probes (the 2026 signal)

The highest-value probe right now measures **inference-serving capacity** directly,
because GPU-backed managed inference is the marginal driver of cloud-revenue
*acceleration*.

- **Amazon Bedrock** (`InvokeModel` / `Converse` on a fixed short prompt) and
  **Azure OpenAI** (`chat/completions` on a fixed short prompt): measure
  **time-to-first-token**, **tokens/sec**, and above all the
  **`429` / `ThrottlingException` rate** against a constant small request across
  regions and model families.
- Secondary, lower value: `s3:PutObject` latency for a fixed object; DynamoDB
  on-demand-mode scale-up behaviour; CloudFront cache-fill latency; Kinesis /
  SQS throughput ramp.
- **Cost:** cents per hour.

This may end up the single most predictive feature in the whole system.

---

## Family D — Data-plane contention (secondary, noisy, keep small)

The classic micro-architectural side-channel literature. Conceptually the "more
creative" tier; practically **high noise, low provider-attributability** (one host is
not a datacenter), and it edges toward looking like benchmarking-to-attack. Treat as an
**experimental secondary factor — roughly 10 % of model weight**, not the core.

- **`%steal`** on a running probe instance — hypervisor cycles given to co-tenants;
  rises when the physical host is oversubscribed. Aggregate across many instances over
  time within one AZ.
- **Fixed micro-benchmarks** on fresh instances — STREAM (memory bandwidth), an
  LLC cache-thrash loop, a fixed dense matmul. Performance *variance* vs. a rolling
  baseline = host contention.
- **Network fabric** — `iperf3` / ping jitter between your own instances in different
  AZs and to S3, under varying time-of-day load.
- **EBS cold-block first-read latency** — cold blocks are hydrated from the S3 backing
  store, which is contended under aggregate load.
- **Co-residency detection** (does the provider place my new instance near my existing
  one → tighter packing → fuller datacenter): largely **closed** on Nitro / modern
  Azure/GCP hypervisors. Historical interest only.

---

## Family E — Indirect

- **Third-party degradation:** monitor public API latency of a basket of well-known
  consumer/SaaS apps each known to run predominantly on one provider; aggregate
  slowdown not explained by their own traffic ≈ provider strain. (Overlaps with the
  infrastructure-footprint labels in [LABELS.md](LABELS.md).)
- **New-region seeding:** when a provider opens a region, *which* instance types land
  first and how quickly reflects where they have hardware slack.
- **IP-space / BGP / certificate-transparency growth:** covered as label sources in
  [LABELS.md](LABELS.md) §Tier 3 — they double as infrastructure-expansion features
  here.

---

## Measurement hygiene

Latency is a sum of components; we must separate them.

- **Baseline subtraction:** every probe cycle also issues a no-op control call
  (`DescribeRegions`, etc.) to net out API + network RTT from the collector's vantage.
- **In-region collectors:** run probes from EventBridge-scheduled Lambda *in the target
  region* so measured latency is control-plane + data-plane, not WAN.
- **Clocks:** NTP-synced hosts; record both client-observed timestamps and any
  service-reported timestamps.
- **Decomposition logged per probe:** `api_rtt`, `accepted → provisioning`,
  `provisioning → ready`, `ready → usable`.
- **Exclusions:** drop samples overlapping provider incident windows (status RSS) and
  our own collector errors / throttles.
- **Redundancy:** ≥ 2 independent collector identities per region where feasible;
  disagreement between them is itself a datapoint.
- **Calendar controls:** hour-of-day, day-of-week, month-end, region-local holidays,
  and known provider event windows (re:Invent, Prime Day, Ignite) as model regressors.

---

## Cost model (fits the < $100 / month ceiling)

| Probe | Unit cost | Cadence | Monthly est. |
|---|---|---|---|
| Spot / placement-score / pricing / RSS polling | $0 | continuous | **$0** |
| EC2 launch-and-kill (`t4g.nano`, 60 s) | ~$0.0001 | 40 cells × hourly | ~$3 |
| Fargate task probes | ~$0.0005 | 20 cells × hourly | ~$7 |
| Lambda cold-start + concurrency | ~$0 | hourly | ~$1 |
| Bedrock / Azure OpenAI throttle probes | ~$0.002 | every 10 min | ~$9 |
| GPU launch probes (`p*`, `MinCount` trick, mostly ICE) | ~$0 on ICE | 6×/day | ~$5–30 |
| Cross-region data transfer + CloudWatch logs | — | — | ~$10 |
| **Total** | | | **~$35–60** |

Enforced by the fail-closed cost governor (DESIGN.md §6): probes check remaining budget
before every launch and refuse if the projection would breach the ceiling.

---

## What we are explicitly NOT doing

- **Not** spawning large or sustained fleets — probes are tiny, brief, and
  rate-governed to stay inside the behaviour envelope of one bursty customer.
- **Not** overloading any instance — it measures that box's neighbours at best and
  looks abusive.
- **Not** spamming control planes — jittered schedules, per-service rate caps, global
  kill switch.
- **Not** probing third-party systems, doing security scans, or attempting co-tenant
  inference.

All measurement uses our own account's API responses and our own workloads. See
DESIGN.md §9 for the full legal/ethical posture.
