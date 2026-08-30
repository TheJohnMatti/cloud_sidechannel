# Feasibility spike — findings

**Date:** 2026-08-30 · **Verdict:** 🟡→🔴 *lean negative on the current framing.*
Run: `.venv/bin/python research/feasibility/analyze.py`

## Question

Before building any collector: is there a real, *tradeable* link between cloud-capacity
tightness and hyperscaler cloud-segment revenue? Try to **kill the thesis cheaply.**

## Data used (all free, all caveated)

- **Revenue panel** — AWS $ + YoY, Azure YoY %, GCP $ + YoY, 2018Q1–2025Q3. Compiled
  from public reporting, approximate (±~2%). Growth-rate *patterns* are robust to that.
- **Capacity-constraint timeline** — hand-coded 0–3 intensity per provider per quarter
  from earnings-call commentary + press. **Partly circular** (downstream of the same
  prints) and subjective. Stands in for what a real-time probe would have shown.
- **Prices** — Yahoo Finance daily, for market-adjusted earnings-day reactions.

## Results

### 1. Direction is right, but weak

| forward 2-quarter growth acceleration | mean | median | n |
|---|---|---|---|
| cc = 0 (elastic) | **−2.4 pp** | −2.0 | 37 |
| cc = 1 (mild) | −1.5 pp | −1.8 | 16 |
| cc ≥ 2 (constrained) | **+1.1 pp** | +1.5 | 18 |

Constrained providers hold/accelerate; elastic ones decelerate. Consistent with
*"constraint = demand ahead of supply = revenue tailwind as capacity lands,"* **not**
*"constraint = lost sales."* Pearson r ≈ 0.2 (t ≈ 1.5–1.9); OLS with momentum control
gives +0.86 pp of next-quarter acceleration per constraint-point (t ≈ 1.5). Suggestive,
not significant.

### 2. …and it's absorbed by "the AI upcycle is on" — the killer

Add a single **AI-era dummy (2023Q2+)** to the regression:

| coefficient | before | after AI-era control |
|---|---|---|
| constraint code | +0.86 (t 1.5) | **−0.30 (t −0.4)** |
| AI-era dummy | — | +3.30 (t 2.6) |

The coarse capacity proxy carries **essentially no information beyond the calendar fact
that the AI boom started in 2023Q2.** That is not tradeable — the whole market knows it.

### 3. No link to the earnings-day stock reaction

`corr(constraint code, market-adjusted 1-day move) = −0.02` (n = 42).
Mean reaction when cc ≥ 2 vs cc ≤ 1: **+0.3% vs +0.3%** — identical.

Management foregrounds capacity on every call, so the **capacity narrative is already
priced.** An independent *narrative-level* read of it earns nothing.

### 4. Natural experiment — directionally supportive, n = 1

Azure was AI-capacity-constrained 2023Q2–2024Q2; AWS was not. Azure growth troughed at
26% and re-accelerated to 30–31% *while constrained*; AWS stayed at 12–13% and recovered
only later. Points the right way, but hopelessly confounded (Azure had the OpenAI
product cycle; AWS did not).

## What this rules in / out

**Ruled out:** the coarse, quarterly, *narrative-level* capacity signal as standalone
alpha. It is subsumed by public knowledge and unrelated to the print reaction.

**NOT ruled out** (the spike can't test these — the proxy isn't sharp enough):

- A **high-frequency, GPU- and region-specific, mid-quarter, quantitative** signal that
  (a) moves *before* sell-side consensus revisions, (b) pins down *which* quarter and
  *how much*, (c) discriminates between providers in the same week.
- The signal as a **capacity-intelligence product** (real-time "where is GPU capacity")
  rather than an earnings predictor.

## The test that would actually settle it

1. Pull the **Zenodo EC2 spot-price archive** (2018–2023, ~1.6 GB, free, one-time).
2. Build a weekly **spot-premium tightness index** (`spot / on-demand`, breadth,
   GPU-family sub-index) — a genuinely *self-measurable* signal, not narrative-derived.
3. Obtain **consensus-estimate revision history** for AWS/Azure/GCP (the hard gap —
   Visible Alpha, Estimize, or hand-collected dated analyst notes).
4. Test: does the spot-premium index **lead the consensus revisions**, and does it
   predict the *residual* surprise (actual − latest consensus)? That removes the
   circularity and answers the only question that matters.

## Recommended decision

| Option | What | Cost |
|---|---|---|
| **A. Sharpen the test** | Do the 4 steps above. ~1 week. Gate the whole project on step 4. | spot download + consensus data |
| B. Re-aim | Treat it as a capacity-intelligence data product, not an earnings signal | — |
| C. Shelve | Priors are now lower; revisit if a cheaper edge appears | — |

Priors after this spike: the *elegant* version of the thesis (latency → quarterly
financials) is weaker than hoped. The surviving edge, if any, is **speed and
granularity** — beating the consensus-revision clock with GPU/region resolution — not
detecting something the market can't see.
