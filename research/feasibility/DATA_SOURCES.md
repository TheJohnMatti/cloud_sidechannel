# Spot / capacity data sources — 2024-2025 scoping

Goal: extend the tightness index past end-2023 (where our ISI archive stops) so the
feasibility test covers **≥3 regime episodes** instead of 1.

Researched 2026-08-30. TL;DR: **the Pauley Zenodo dataset solves it, free, monthly
coverage through Feb 2026, no gaps.** Three good secondary sources; two dead ends.

---

## ✅ PRIMARY — Pauley "AWS Spot Price History" (Zenodo)

| | |
|---|---|
| Concept DOI | **10.5281/zenodo.14198917** (always resolves to newest version) |
| Current version | `2026-02`, record id 18821638, published 2026-03-01 |
| Coverage | **2022 → Feb 2026**, monthly files, **no missing months** (verified) |
| Format | `YYYY-MM.tsv.zst` — ZStandard-compressed TSV, 5 cols: `az_global_id \t instance_type \t OS \t price \t timestamp` |
| AZ field | **global AZ IDs** (`use1-az1`) not per-account names — *better*: stable identifiers |
| Size | 4.38 GB all; **~3.3 GB for 2024-01…2025-12** (24 files, 83–200 MB each) |
| Density | ~13M rows/month (event-driven: a row per price change), vs ISI's daily snapshots — richer |
| License | CC-BY-4.0 (attribution required) |
| Collector | `github.com/ericpauley/aws-spot-price-history` (Eric Pauley, UW-Madison). Go-based, monthly GitHub Action. **Action broke ~Mar 2026** → nothing past Feb 2026, irrelevant to us. |
| Independence | **Different collector from our ISI archive.** They overlap on 2022-2023 → free cross-validation of both datasets. |

**Verified working:** downloaded `2024-06.tsv.zst` (89 MB), `zstd -dc` streams fine,
13.0M rows, format exactly as documented. `zstd` CLI present at `/opt/homebrew/bin/zstd`.

**Integration cost:** ~1 day. Need a small format adapter in `build_spot_index.py`:
tsv+zstd instead of tar+xz, AZ-ID→region map (`use1-az1` → `us-east-1`), same
downstream aggregation. On-demand proxy method is unchanged.

**This alone gets us to n=3.**

---

## Secondary sources (cross-checks / multi-cloud / later)

### AWS Spot Instance Advisor JSON — via Wayback Machine  (free, independent proxy)

- URL: `https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json`
- Contains, per `instance_type × region × OS`: **interruption-frequency rating** (0-4 =
  <5%, 5-10%, 10-15%, 15-20%, >20%) and **savings %** vs on-demand.
- Wayback snapshots ≈ monthly: 2023-03, 2023-06, then **2024-09 → 2026-06** steadily
  (a gap in 2024 H1 — unfortunate, but the AWS/GCP constraint episode is mostly 2024 H2+).
- A tightness proxy **not based on price** — good robustness check on the spot-premium
  signal. Scrape via the CDX API, ~2 hours.

### SpotLake (ddps-lab) — the multi-cloud option  (request access)

- `spotlake.ddps.cloud`, `github.com/ddps-lab/spotlake`, **actively maintained** (commits Aug 2026).
- Covers **AWS + GCP + Azure**: spot price, **interrupt frequency**, and **Spot Placement
  Score** (AWS's own 1-10 capacity index — *not available historically anywhere else*).
- Data since ~2021. IISWC 2022 + WWW 2023/2024 papers.
- Demo web query is rate-limited (20k points, 1-month range) — fine for targeted pulls,
  not bulk. **Full dataset = email the lab for S3 access permission** (researcher-friendly).
- Worth requesting in parallel: unlocks Azure/GCP tightness and the placement-score
  signal for the real build, even if it doesn't arrive in time for the n=3 test.

### CloudPrice.net — commercial fallback

- **Advanced $9.95/mo**: "Spot Price History > 3 months" + REST API, AWS+Azure+GCP.
  Unclear if the API returns bulk history or only per-instance chart series.
- **Batch Export $100/mo/cloud**: daily CSV snapshots; history "back to Jan 2024 for
  AWS, mid-2022 for Azure" (on request).
- Only needed if Pauley has quality problems. The $9.95 tier is a cheap sanity check.

---

## ❌ Dead ends

| Source | Why not |
|---|---|
| **ISI/ANT archive** (our original 2018-2023 source) | Latest version (20250310, Mar 2025) still stops at **2023**. No 2024+ planned. |
| **AWS `describe-spot-price-history` API directly** | Hard **90-day** limit. Cannot backfill 2024-2025. (Still the right tool for *forward* Tier-0 collection.) |
| **Azure Retail Prices API / Resource Graph** | 90-day price history, 28-day eviction history. Same wall. |
| **Kaggle spot datasets** | All stale (2017). |

---

## Recommended plan

1. **Now — integrate Pauley 2024-2025** (24 files, 3.3 GB). Extend `build_spot_index.py`
   with the tsv/zstd/az-id adapter, rebuild the weekly index 2018→2025.
2. **Re-run `analyze_sharpened.py` with the episodes now available:**
   - 2020 H1 — COVID cloud surge (spot barely moved → a *false-negative* test)
   - 2023 Q2 — AI round 1, Azure/OpenAI (the strong signal we found)
   - 2024 H1 — digestion ending, AWS re-accelerating 13→17→19% (an *up* inflection)
   - 2024 H2–2025 — AWS + GCP join the constrained club; Azure "short power and space"
   That's 3-4 testable inflections, both directions — a real out-of-sample set.
3. **Parallel — email SpotLake** for full-dataset access (placement scores + Azure/GCP).
4. **Cheap add — scrape the Wayback spot-advisor JSON** as a price-independent
   interruption-rate cross-check.
5. Skip CloudPrice unless Pauley disappoints.
