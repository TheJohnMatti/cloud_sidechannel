"""
Sharpened feasibility test — the QUANTITATIVE, self-measured spot-premium signal.

The coarse hand-coded constraint proxy died when we controlled for "AI-era on"
(FINDINGS.md). This re-runs the tests with a signal we actually measured ourselves
from the EC2 spot archive, and asks the questions that matter:

  T1  Does the GPU spot premium LEAD the capacity-constraint narrative?
      (i.e. would our probe have flagged it weeks before the earnings call did)
  T2  Does quarter-start / mid-quarter premium predict that quarter's revenue-growth
      acceleration -- AND does it SURVIVE the AI-era dummy that killed the proxy?
  T3  Does premium predict the earnings-day market-adjusted reaction (surprise proxy)?
  T4  Does premium move ahead of the pre-earnings stock drift (consensus-revision proxy)?

Inputs:
  data/spot_weekly_index.parquet        (from build_spot_index.py)
  data/cloud_revenue_panel.csv
  data/capacity_constraint_timeline.csv
  Yahoo Finance daily prices (cached)
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd

HERE = __file__.rsplit("/", 1)[0]
from analyze import fetch_prices, EARNINGS_DATES, PROV_TICKER  # reuse


def qkey(ts: pd.Timestamp) -> str:
    return f"{ts.year}Q{(ts.month - 1) // 3 + 1}"


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wk = pd.read_parquet(f"{HERE}/data/spot_weekly_index.parquet")
    wk["week"] = pd.to_datetime(wk["week"])
    rev = pd.read_csv(f"{HERE}/data/cloud_revenue_panel.csv", comment="#")
    cc = pd.read_csv(f"{HERE}/data/capacity_constraint_timeline.csv", comment="#")
    return wk, rev, cc


def quarterize(wk: pd.DataFrame, scope: str) -> pd.DataFrame:
    """Per calendar quarter: premium as-of quarter start (first 2 wks), mid-quarter
    (wks 5-8), and full-quarter mean."""
    s = wk[wk.scope == scope].sort_values("week").copy()
    s["cq"] = s["week"].map(qkey)
    rows = []
    for cq, g in s.groupby("cq"):
        g = g.sort_values("week")
        rows.append(dict(
            cq=cq,
            prem_qstart=g["mean_premium"].head(2).mean(),
            prem_mid=g["mean_premium"].iloc[4:8].mean() if len(g) >= 6 else np.nan,
            prem_qmean=g["mean_premium"].mean(),
            breadth_qmean=g["breadth_gt60"].mean(),
            p90_qmean=g["p90_premium"].mean(),
        ))
    q = pd.DataFrame(rows)
    for c in ["prem_qstart", "prem_mid", "prem_qmean", "breadth_qmean", "p90_qmean"]:
        q[f"{c}_yoy"] = q[c] - q[c].shift(4)
        q[f"{c}_qoq"] = q[c] - q[c].shift(1)
    return q


def corr_t(a: pd.Series, b: pd.Series) -> tuple[float, float, int]:
    m = pd.concat([a, b], axis=1).dropna()
    n = len(m)
    if n < 8:
        return (np.nan, np.nan, n)
    r = m.iloc[:, 0].corr(m.iloc[:, 1])
    t = r * math.sqrt((n - 2) / max(1e-9, 1 - r * r))
    return (r, t, n)


# --------------------------------------------------------------------------- #
# Known cloud-capacity inflections. `expect` = which way tightness "should" move.
EPISODES = [
    ("2020 COVID cloud surge",      "2020-01-01", "2020-07-01", "up",
     "MSFT throttled free trials Mar-Apr 2020; demand spike then normalised"),
    ("2022-23 optimization trough",  "2022-07-01", "2023-02-01", "down",
     "macro-driven demand softness; AWS growth 33%->16%; no capacity issue"),
    ("2023 AI round 1 (Azure/OpenAI)","2023-02-01", "2023-08-01", "up",
     "GPT-4; enterprise LLM demand; 'Azure AI capacity constrained' by Jul-2023 call"),
    ("2024 H1 re-acceleration",       "2023-11-01", "2024-06-01", "up",
     "digestion ends; AWS re-accelerates 13%->19%"),
    ("2024H2-25 broad constraint",    "2024-06-01", "2025-06-01", "up",
     "AWS + GCP join; MSFT 'short power and space' (Q4-24); all three constrained"),
]


def episode_table(wk: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("EPISODES  did the self-measured premium move at each known inflection?")
    print("=" * 78)
    a = wk[wk.scope == "all"].sort_values("week").set_index("week")["mean_premium"]
    g = wk[wk.scope == "gpu"].sort_values("week").set_index("week")["mean_premium"]
    b = wk[wk.scope == "all"].sort_values("week").set_index("week")["breadth_gt60"]
    print(f"\n  {'episode':<32}{'window':<20}{'exp':<5}{'Δall':>7}{'Δgpu':>7}{'Δbreadth':>9}")
    for name, lo, hi, expect, _ in EPISODES:
        lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
        pre = slice(lo - pd.Timedelta(weeks=6), lo + pd.Timedelta(weeks=2))
        post = slice(hi - pd.Timedelta(weeks=8), hi)
        if a.loc[pre].empty or a.loc[post].empty:
            print(f"  {name:<32}{lo.date()}..{hi.date()}  [no data]")
            continue
        da = a.loc[post].mean() - a.loc[pre].mean()
        dg = g.loc[post].mean() - g.loc[pre].mean()
        db = b.loc[post].mean() - b.loc[pre].mean()
        hit = "OK" if (da > 0.02) == (expect == "up") else "MISS" if abs(da) > 0.02 else "flat"
        print(f"  {name:<32}{lo.date()}..{hi.date()}  {expect:<5}{da:>+7.3f}{dg:>+7.3f}{db:>+9.3f}  {hit}")
    print("\n  Δ = (mean over last 8wk of window) − (mean over 6wk before window start).")
    print("  'exp' up = tightness should rise. Signal is credible only if it hits the")
    print("  UP episodes AND stays flat on the 'down' (optimization) one.")


# --------------------------------------------------------------------------- #
def t1_lead_narrative(wk: pd.DataFrame, cc: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("T1  Does the GPU spot premium LEAD the capacity-constraint narrative?")
    print("=" * 78)
    gpu = wk[wk.scope == "gpu"].sort_values("week").set_index("week")["mean_premium"]
    allp = wk[wk.scope == "all"].sort_values("week").set_index("week")["mean_premium"]
    gpu_m = gpu.resample("MS").mean()
    all_m = allp.resample("MS").mean()
    print("\n  GPU-family & all-family mean spot premium, monthly (higher = tighter).")
    print("  2022 onward:")
    print("  month       gpu    all   | vs narrative")
    narr = {r["cq"]: r["azure_cc"] for _, r in cc.iterrows()}
    for mo in gpu_m.index:
        if mo < pd.Timestamp("2022-01-01"):
            continue
        g_, a_ = gpu_m.get(mo, np.nan), all_m.get(mo, np.nan)
        if pd.isna(g_) or pd.isna(a_):
            continue
        cq = qkey(mo)
        note = ""
        if mo.month in (1, 4, 7, 10):
            note = f"  <- {cq} earnings season; azure constraint code={narr.get(cq, '?')}"
        bar = "#" * int(round(a_ * 50))
        print(f"  {mo.date()}  {g_:.3f}  {a_:.3f}  |{bar}{note}")

    # first sustained GPU-premium rise vs first azure_cc>=2 quarter
    first_cc2 = cc.loc[cc.azure_cc >= 2, "cq"].iloc[0] if (cc.azure_cc >= 2).any() else None
    print(f"\n  First quarter with azure_cc >= 2 (explicit AI capacity constraint): {first_cc2}")
    print("  -> compare to when GPU premium first stepped up above. If the premium moved")
    print("     one or more quarters earlier, the side-channel leads the narrative.")


def t2_growth_accel(q: pd.DataFrame, rev: pd.DataFrame, cc: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("T2  Premium -> revenue-growth acceleration, and does it beat the AI-era dummy?")
    print("=" * 78)
    d = rev.merge(cc[["cq", "aws_cc", "azure_cc", "gcp_cc"]], on="cq").merge(q, on="cq", how="left")
    d["aws_accel"] = d["aws_yoy"].diff()
    d["azure_accel"] = d["azure_yoy"].diff()
    d["gcp_accel"] = d["gcp_yoy"].diff()
    d["aws_accel_f1"] = d["aws_accel"].shift(-1)
    d["azure_accel_f1"] = d["azure_accel"].shift(-1)
    d["gcp_accel_f1"] = d["gcp_accel"].shift(-1)
    d["qi"] = range(len(d))
    ai0 = d.index[d.cq == "2023Q2"][0]
    d["ai_era"] = (d["qi"] >= ai0).astype(float)

    print("\n  Pooled provider-quarter (AWS/Azure/GCP). Premium features are provider-")
    print("  agnostic (whole-market tightness); accel is per provider.\n")
    L = []
    for prov in ["aws", "azure", "gcp"]:
        t = d[["cq", "qi", "ai_era", f"{prov}_accel", f"{prov}_accel_f1",
               "prem_qstart", "prem_qmean_yoy", "breadth_qmean", "p90_qmean_yoy"]].copy()
        t.columns = ["cq", "qi", "ai_era", "accel", "accel_f1",
                     "prem_qstart", "prem_yoy", "breadth", "p90_yoy"]
        t["provider"] = prov
        L.append(t)
    P = pd.concat(L, ignore_index=True)

    print(f"  {'feature -> target':<46}{'r':>7}{'t':>7}{'n':>5}")
    for lbl, a, b in [
        ("prem_qstart(t)   -> accel(t)    contemp", "prem_qstart", "accel"),
        ("prem_qstart(t)   -> accel(t+1)  1Q lead", "prem_qstart", "accel_f1"),
        ("prem_qmean_yoy(t) -> accel(t)   contemp", "prem_yoy", "accel"),
        ("prem_qmean_yoy(t) -> accel(t+1) 1Q lead", "prem_yoy", "accel_f1"),
        ("breadth(t)       -> accel(t+1)  1Q lead", "breadth", "accel_f1"),
        ("p90_yoy(t)       -> accel(t+1)  1Q lead", "p90_yoy", "accel_f1"),
    ]:
        r, tt, n = corr_t(P[a], P[b])
        print(f"  {lbl:<46}{r:>7.2f}{tt:>7.1f}{n:>5d}")

    # the decisive regression: does premium survive the AI-era control?
    reg = P.dropna(subset=["accel_f1", "prem_yoy", "accel", "ai_era"]).copy()
    if len(reg) >= 15:
        for controls, name in [
            (["accel"], "momentum only"),
            (["accel", "ai_era"], "momentum + AI-era dummy"),
        ]:
            X = pd.get_dummies(reg["provider"], prefix="p", drop_first=True).astype(float)
            X["prem_yoy"] = reg["prem_yoy"].values
            for c in controls:
                X[c] = reg[c].values
            X["const"] = 1.0
            Xm = X.values.astype(float)
            y = reg["accel_f1"].values.astype(float)
            b, *_ = np.linalg.lstsq(Xm, y, rcond=None)
            res = y - Xm @ b
            n, k = Xm.shape
            s2 = float(res @ res) / (n - k)
            se = np.sqrt(np.diag(s2 * np.linalg.inv(Xm.T @ Xm)))
            r2 = 1 - float(res @ res) / float(((y - y.mean()) ** 2).sum())
            i = list(X.columns).index("prem_yoy")
            print(f"\n  accel(t+1) ~ prem_qmean_yoy + {name} + provider FE   (n={n}, R2={r2:.2f})")
            print(f"     prem_yoy coef = {b[i]:+.2f}  (per 1.0 of premium-YoY)   t = {b[i]/se[i]:+.1f}")


def t3_earnings_reaction(q: pd.DataFrame, cc: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("T3  Premium -> earnings-day market-adjusted reaction (surprise proxy)")
    print("=" * 78)
    try:
        spy = fetch_prices("SPY").set_index("date")["close"]
        px = {t: fetch_prices(t).set_index("date")["close"] for t in ["AMZN", "MSFT", "GOOGL"]}
    except Exception as e:
        print(f"  [skipped: {e!r}]")
        return

    def react(series, d):
        d = pd.Timestamp(d)
        aft = series.index[series.index >= d]
        bef = series.index[series.index < d]
        if len(aft) == 0 or len(bef) == 0:
            return np.nan
        d1, d0 = aft[0], bef[-1]
        if d1 not in spy.index or d0 not in spy.index:
            return np.nan
        return (series[d1] / series[d0] - 1) - (spy[d1] / spy[d0] - 1)

    rows = []
    for prov, tk in PROV_TICKER.items():
        for cq, dt in EARNINGS_DATES[tk].items():
            qq = q[q.cq == cq]
            if qq.empty:
                continue
            rows.append(dict(provider=prov, cq=cq,
                             prem_qmean=float(qq["prem_qmean"].iloc[0]),
                             prem_qstart=float(qq["prem_qstart"].iloc[0]),
                             prem_yoy=float(qq["prem_qmean_yoy"].iloc[0]) if pd.notna(qq["prem_qmean_yoy"].iloc[0]) else np.nan,
                             reaction=react(px[tk], dt)))
    R = pd.DataFrame(rows).dropna(subset=["reaction"])
    for a in ["prem_qmean", "prem_qstart", "prem_yoy"]:
        r, t, n = corr_t(R[a], R["reaction"])
        print(f"  corr({a:<12}, reaction) = {r:+.2f}  t={t:+.1f}  n={n}")
    print("\n  (positive = higher whole-market tightness that quarter went with a better")
    print("   cloud print reaction. weak/zero = the market already knew.)")


def t4_preearnings_drift(q: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("T4  Does premium move AHEAD of the pre-earnings stock drift (revision proxy)?")
    print("=" * 78)
    try:
        spy = fetch_prices("SPY").set_index("date")["close"]
        px = {t: fetch_prices(t).set_index("date")["close"] for t in ["AMZN", "MSFT", "GOOGL"]}
    except Exception as e:
        print(f"  [skipped: {e!r}]"); return

    def drift(series, d, days=20):
        d = pd.Timestamp(d)
        bef = series.index[series.index < d]
        if len(bef) < days + 1:
            return np.nan
        d1, d0 = bef[-1], bef[-days - 1]
        if d1 not in spy.index or d0 not in spy.index:
            return np.nan
        return (series[d1] / series[d0] - 1) - (spy[d1] / spy[d0] - 1)

    rows = []
    for prov, tk in PROV_TICKER.items():
        for cq, dt in EARNINGS_DATES[tk].items():
            qq = q[q.cq == cq]
            if qq.empty:
                continue
            rows.append(dict(provider=prov, cq=cq,
                             prem_qoq=float(qq["prem_qmean_qoq"].iloc[0]) if pd.notna(qq["prem_qmean_qoq"].iloc[0]) else np.nan,
                             prem_yoy=float(qq["prem_qmean_yoy"].iloc[0]) if pd.notna(qq["prem_qmean_yoy"].iloc[0]) else np.nan,
                             pre_drift=drift(px[tk], dt)))
    R = pd.DataFrame(rows).dropna(subset=["pre_drift"])
    for a in ["prem_qoq", "prem_yoy"]:
        r, t, n = corr_t(R[a], R["pre_drift"])
        print(f"  corr({a:<9}, 20d pre-earnings drift) = {r:+.2f}  t={t:+.1f}  n={n}")
    print("\n  If premium change correlates with the drift, the market is already moving on")
    print("  the same info -> our edge is only whatever LEAD time the probe buys.")


if __name__ == "__main__":
    wk, rev, cc = load()
    print(f"weekly index: {wk.week.min().date()}..{wk.week.max().date()}  "
          f"scopes={sorted(wk.scope.unique())[:6]}...")
    q = quarterize(wk, "all")
    qg = quarterize(wk, "gpu").add_suffix("_gpu").rename(columns={"cq_gpu": "cq"})
    q = q.merge(qg, on="cq", how="left")
    print(q[["cq", "prem_qstart", "prem_qmean", "prem_qmean_yoy", "prem_qstart_gpu", "prem_qmean_gpu"]].to_string(index=False))
    episode_table(wk)
    t1_lead_narrative(wk, cc)
    t2_growth_accel(q, rev, cc)
    t3_earnings_reaction(q, cc)
    t4_preearnings_drift(q)
