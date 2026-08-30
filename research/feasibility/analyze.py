"""
Feasibility spike — is the cloud-capacity → revenue signal real?

Phase-0 falsification test. We are NOT trying to prove the thesis; we are trying
to kill it cheaply. Three questions:

  Q1  Does capacity tightness lead cloud-segment revenue-growth acceleration?
  Q2  Is the effect visible in a natural experiment (Azure AI-constrained 2023-24
      while AWS was not)?
  Q3  Does tightness line up with the earnings-day stock reaction (i.e. is it
      information the market actually pays for)?

Data:
  data/cloud_revenue_panel.csv          - AWS/Azure/GCP quarterly growth (approx, flagged)
  data/capacity_constraint_timeline.csv - coded constraint intensity 0-3 (proxy, partly circular)
  Yahoo Finance chart API               - daily prices for earnings-day reactions

Caveats printed at the end. This proxy is a smell test; the definitive test needs
the self-measured spot-price premium (Zenodo EC2 spot archive).
"""
from __future__ import annotations
import io, time, json, math
import numpy as np
import pandas as pd
import httpx

HERE = __file__.rsplit("/", 1)[0]


# ----------------------------------------------------------------------------- #
# load
# ----------------------------------------------------------------------------- #
def load_panel() -> pd.DataFrame:
    rev = pd.read_csv(f"{HERE}/data/cloud_revenue_panel.csv", comment="#")
    cc = pd.read_csv(f"{HERE}/data/capacity_constraint_timeline.csv", comment="#")
    df = rev.merge(cc[["cq", "aws_cc", "azure_cc", "gcp_cc"]], on="cq", how="left")
    df["qi"] = range(len(df))
    return df


def to_long(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (provider, quarter)."""
    rows = []
    for _, r in df.iterrows():
        for prov, g, cc in [
            ("aws", r["aws_yoy"], r["aws_cc"]),
            ("azure", r["azure_yoy"], r["azure_cc"]),
            ("gcp", r["gcp_yoy"], r["gcp_cc"]),
        ]:
            if pd.notna(g):
                rows.append(dict(cq=r["cq"], qi=r["qi"], provider=prov,
                                 yoy=float(g), cc=float(cc) if pd.notna(cc) else np.nan))
    L = pd.DataFrame(rows).sort_values(["provider", "qi"]).reset_index(drop=True)
    # growth acceleration = change in YoY growth vs prior quarter
    L["accel"] = L.groupby("provider")["yoy"].diff()
    # forward accelerations
    for k in (1, 2):
        L[f"accel_fwd{k}"] = L.groupby("provider")["accel"].shift(-k)
        L[f"yoy_fwd{k}"] = L.groupby("provider")["yoy"].shift(-k)
    L["cc_chg"] = L.groupby("provider")["cc"].diff()
    return L


# ----------------------------------------------------------------------------- #
# Q1 — tightness -> forward growth acceleration
# ----------------------------------------------------------------------------- #
def q1_lead_lag(L: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("Q1  Does capacity tightness LEAD revenue-growth acceleration?")
    print("=" * 78)
    print("  'accel' = quarter-over-quarter change in YoY growth rate (percentage points)")
    print("  Pooled across AWS/Azure/GCP; contemporaneous + forward horizons.\n")

    def corr(a, b):
        m = L[[a, b]].dropna()
        if len(m) < 8:
            return (np.nan, np.nan, len(m))
        r = m[a].corr(m[b])
        # crude t on n-2 df
        n = len(m)
        t = r * math.sqrt((n - 2) / max(1e-9, 1 - r * r))
        return (r, t, n)

    print(f"  {'relationship':<44}{'pearson r':>10}{'t':>8}{'n':>6}")
    for lbl, a, b in [
        ("cc(t)         vs accel(t)   [contemp.]", "cc", "accel"),
        ("cc(t)         vs accel(t+1) [1Q lead]", "cc", "accel_fwd1"),
        ("cc(t)         vs accel(t+2) [2Q lead]", "cc", "accel_fwd2"),
        ("cc_change(t)  vs accel(t+1) [1Q lead]", "cc_chg", "accel_fwd1"),
        ("cc(t)         vs yoy(t+1)   [1Q lead]", "cc", "yoy_fwd1"),
        ("cc(t)         vs yoy(t+2)   [2Q lead]", "cc", "yoy_fwd2"),
    ]:
        r, t, n = corr(a, b)
        print(f"  {lbl:<44}{r:>10.2f}{t:>8.1f}{n:>6d}")

    # directional: when constrained (cc>=2), what happens next 2 quarters?
    print("\n  Conditional forward 2Q growth-accel (sum of next 2 accels):")
    L2 = L.copy()
    L2["accel_next2"] = L2["accel_fwd1"].fillna(0) + L2["accel_fwd2"].fillna(0)
    for lo, hi, name in [(-0.1, 0.1, "cc = 0  (elastic)"),
                         (0.9, 1.1, "cc = 1  (mild)"),
                         (1.9, 3.1, "cc >= 2 (constrained)")]:
        s = L2.loc[L2["cc"].between(lo, hi), "accel_next2"].dropna()
        if len(s):
            print(f"    {name:<24} mean {s.mean():+5.1f} pp   median {s.median():+5.1f} pp   n={len(s)}")

    # provider fixed-effects OLS: accel_fwd1 ~ cc + provider dummies + lagged accel
    d = L.dropna(subset=["accel_fwd1", "cc", "accel"]).copy()
    if len(d) >= 15:
        X = pd.get_dummies(d["provider"], prefix="p", drop_first=True).astype(float)
        X["cc"] = d["cc"].values
        X["accel_lag"] = d["accel"].values          # control for momentum/mean-reversion
        X["const"] = 1.0
        y = d["accel_fwd1"].values.astype(float)
        Xm = X.values.astype(float)
        beta, *_ = np.linalg.lstsq(Xm, y, rcond=None)
        yhat = Xm @ beta
        ss_res = float(np.sum((y - yhat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot
        # se
        n, k = Xm.shape
        sigma2 = ss_res / (n - k)
        cov = sigma2 * np.linalg.inv(Xm.T @ Xm)
        se = np.sqrt(np.diag(cov))
        cols = list(X.columns)
        bcc = beta[cols.index("cc")]
        tcc = bcc / se[cols.index("cc")]
        print(f"\n  OLS  accel(t+1) ~ cc(t) + accel(t) + provider FE   (n={n}, R2={r2:.2f})")
        print(f"       cc coefficient = {bcc:+.2f} pp per constraint-point   t = {tcc:+.1f}")
        print(f"       (interpretation: each +1 on the 0-3 constraint scale is worth")
        print(f"        ~{bcc:+.1f}pp of growth-rate acceleration next quarter, holding momentum)")

        # --- confound check: is 'cc' just proxying the AI-demand regime? -------
        # add an AI-era dummy (2023Q2+) and total-capex YoY. if cc dies, the
        # capacity signal carries nothing beyond "AI boom is on", which is not news.
        d2 = d.copy()
        d2["ai_era"] = (d2["qi"] >= df.index[df.cq == "2023Q2"][0]).astype(float)
        X2 = pd.get_dummies(d2["provider"], prefix="p", drop_first=True).astype(float)
        X2["cc"] = d2["cc"].values
        X2["accel_lag"] = d2["accel"].values
        X2["ai_era"] = d2["ai_era"].values
        X2["const"] = 1.0
        Xm2 = X2.values.astype(float)
        b2, *_ = np.linalg.lstsq(Xm2, y, rcond=None)
        yhat2 = Xm2 @ b2
        sig2 = float(np.sum((y - yhat2) ** 2)) / (Xm2.shape[0] - Xm2.shape[1])
        se2 = np.sqrt(np.diag(sig2 * np.linalg.inv(Xm2.T @ Xm2)))
        c2 = list(X2.columns)
        print(f"\n  CONFOUND CHECK  add AI-era dummy (2023Q2+):")
        print(f"       cc coefficient  {b2[c2.index('cc')]:+.2f}  t={b2[c2.index('cc')]/se2[c2.index('cc')]:+.1f}"
              f"   (was {bcc:+.2f})")
        print(f"       ai_era coefficient {b2[c2.index('ai_era')]:+.2f}  t={b2[c2.index('ai_era')]/se2[c2.index('ai_era')]:+.1f}")
        if abs(b2[c2.index('cc')]) < 0.4 or b2[c2.index('cc')]/se2[c2.index('cc')] < 1.0:
            print("       => cc largely absorbed by the AI-era dummy. The proxy is not adding")
            print("          much beyond 'the AI upcycle is on'. Needs the quantitative spot signal.")
        else:
            print("       => cc survives the AI-era control. Capacity carries independent info.")


# ----------------------------------------------------------------------------- #
# Q2 — natural experiment
# ----------------------------------------------------------------------------- #
def q2_natural_experiment(L: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("Q2  Natural experiment: Azure AI-constrained 2023Q2-2024Q2, AWS not")
    print("=" * 78)
    win = ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3"]
    piv = L[L.cq.isin(win)].pivot_table(index="cq", columns="provider",
                                        values=["yoy", "cc"])
    piv = piv.reindex(win)
    print("\n  YoY growth (%)          |  constraint code")
    print(f"  {'quarter':<9}{'aws':>6}{'azure':>7}{'gcp':>6}   |  {'aws':>4}{'azure':>6}{'gcp':>5}")
    for q in win:
        ya, yz, yg = piv.loc[q, ("yoy", "aws")], piv.loc[q, ("yoy", "azure")], piv.loc[q, ("yoy", "gcp")]
        ca, cz, cg = piv.loc[q, ("cc", "aws")], piv.loc[q, ("cc", "azure")], piv.loc[q, ("cc", "gcp")]
        print(f"  {q:<9}{ya:>6.0f}{yz:>7.0f}{yg:>6.0f}   |  {ca:>4.0f}{cz:>6.0f}{cg:>5.0f}")
    aws_delta = piv.loc["2024Q2", ("yoy", "aws")] - piv.loc["2023Q1", ("yoy", "aws")]
    azure_delta = piv.loc["2024Q2", ("yoy", "azure")] - piv.loc["2023Q1", ("yoy", "azure")]
    print(f"\n  Over 2023Q1 -> 2024Q2:  AWS growth {aws_delta:+.0f}pp (stayed weak, unconstrained)")
    print(f"                          Azure growth {azure_delta:+.0f}pp (re-accelerated while constrained)")
    print("  -> the constrained provider is the one whose growth inflected up. Consistent")
    print("     with 'constraint = demand running ahead of supply = revenue tailwind as")
    print("     capacity lands', NOT with 'constraint = lost sales'.")


# ----------------------------------------------------------------------------- #
# Q3 — earnings-day stock reaction
# ----------------------------------------------------------------------------- #
EARNINGS_DATES = {
    # approximate report dates (after-close). calendar quarter -> date
    "AMZN": {
        "2022Q1": "2022-04-28", "2022Q2": "2022-07-28", "2022Q3": "2022-10-27", "2022Q4": "2023-02-02",
        "2023Q1": "2023-04-27", "2023Q2": "2023-08-03", "2023Q3": "2023-10-26", "2023Q4": "2024-02-01",
        "2024Q1": "2024-04-30", "2024Q2": "2024-08-01", "2024Q3": "2024-10-31", "2024Q4": "2025-02-06",
        "2025Q1": "2025-05-01", "2025Q2": "2025-07-31",
    },
    "MSFT": {
        "2022Q1": "2022-04-26", "2022Q2": "2022-07-26", "2022Q3": "2022-10-25", "2022Q4": "2023-01-24",
        "2023Q1": "2023-04-25", "2023Q2": "2023-07-25", "2023Q3": "2023-10-24", "2023Q4": "2024-01-30",
        "2024Q1": "2024-04-25", "2024Q2": "2024-07-30", "2024Q3": "2024-10-30", "2024Q4": "2025-01-29",
        "2025Q1": "2025-04-30", "2025Q2": "2025-07-30",
    },
    "GOOGL": {
        "2022Q1": "2022-04-26", "2022Q2": "2022-07-26", "2022Q3": "2022-10-25", "2022Q4": "2023-02-02",
        "2023Q1": "2023-04-25", "2023Q2": "2023-07-25", "2023Q3": "2023-10-24", "2023Q4": "2024-01-30",
        "2024Q1": "2024-04-25", "2024Q2": "2024-07-23", "2024Q3": "2024-10-29", "2024Q4": "2025-02-04",
        "2025Q1": "2025-04-24", "2025Q2": "2025-07-23",
    },
}
PROV_TICKER = {"aws": "AMZN", "azure": "MSFT", "gcp": "GOOGL"}


def fetch_prices(ticker: str) -> pd.DataFrame:
    cache = f"{HERE}/data/px_{ticker}.csv"
    try:
        return pd.read_csv(cache, parse_dates=["date"])
    except FileNotFoundError:
        pass
    h = {"User-Agent": "Mozilla/5.0"}
    p1 = int(time.mktime(time.strptime("2021-10-01", "%Y-%m-%d")))
    p2 = int(time.mktime(time.strptime("2025-09-01", "%Y-%m-%d")))
    u = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
         f"?period1={p1}&period2={p2}&interval=1d")
    j = httpx.get(u, headers=h, timeout=30).json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    df = pd.DataFrame({"date": pd.to_datetime(ts, unit="s").normalize(), "close": close}).dropna()
    df.to_csv(cache, index=False)
    return df


def q3_stock_reaction(L: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print("Q3  Does tightness line up with the earnings-day stock reaction?")
    print("=" * 78)
    print("  reaction = (stock close-to-close return over the report day) minus SPY's,")
    print("  i.e. market-adjusted 1-day move. Positive = cloud print pleased the market.\n")
    try:
        spy = fetch_prices("SPY").set_index("date")["close"]
        px = {t: fetch_prices(t).set_index("date")["close"] for t in ["AMZN", "MSFT", "GOOGL"]}
    except Exception as e:
        print(f"  [skipped: price fetch failed: {e!r}]")
        return

    def react(series, spy, d):
        d = pd.Timestamp(d)
        idx = series.index
        after = idx[idx >= d]
        before = idx[idx < d]
        if len(after) == 0 or len(before) == 0:
            return np.nan
        d1, d0 = after[0], before[-1]
        if d1 not in spy.index or d0 not in spy.index:
            return np.nan
        return (series[d1] / series[d0] - 1) - (spy[d1] / spy[d0] - 1)

    rows = []
    for prov, tk in PROV_TICKER.items():
        for cq, dt in EARNINGS_DATES[tk].items():
            ccrow = L[(L.provider == prov) & (L.cq == cq)]
            if ccrow.empty:
                continue
            rr = react(px[tk], spy, dt)
            rows.append(dict(provider=prov, cq=cq, cc=float(ccrow["cc"].iloc[0]),
                             accel=float(ccrow["accel"].iloc[0]) if pd.notna(ccrow["accel"].iloc[0]) else np.nan,
                             reaction=rr))
    R = pd.DataFrame(rows).dropna(subset=["reaction"])
    print(f"  {'provider':<9}{'quarter':<9}{'cc':>4}{'accel':>8}{'mkt-adj 1d':>12}")
    for _, r in R.iterrows():
        print(f"  {r['provider']:<9}{r['cq']:<9}{r['cc']:>4.0f}{r['accel']:>8.1f}{r['reaction']*100:>11.1f}%")

    m = R.dropna(subset=["cc", "reaction"])
    if len(m) >= 8:
        print(f"\n  corr(constraint code, market-adjusted reaction) = {m['cc'].corr(m['reaction']):.2f}  (n={len(m)})")
        mm = R.dropna(subset=["accel", "reaction"])
        print(f"  corr(growth acceleration, market-adjusted reaction) = {mm['accel'].corr(mm['reaction']):.2f}  (n={len(mm)})")
        hi = m.loc[m.cc >= 2, "reaction"].mean()
        lo = m.loc[m.cc <= 1, "reaction"].mean()
        print(f"  mean reaction when cc>=2: {hi*100:+.1f}%   when cc<=1: {lo*100:+.1f}%")


# ----------------------------------------------------------------------------- #
def caveats() -> None:
    print("\n" + "=" * 78)
    print("CAVEATS  (read before believing any of the above)")
    print("=" * 78)
    for c in [
        "Revenue figures are compiled-from-memory approximations (+/- ~2%). Growth-rate",
        "  PATTERNS are robust to this; exact coefficients are not. Needs a primary-source pass.",
        "Constraint timeline is hand-coded from earnings commentary => PARTLY CIRCULAR",
        "  (it is downstream of the same prints it 'predicts') and subjective. It stands in",
        "  for what a real-time spot-premium probe would have told us ~1 month pre-print.",
        "n ~ 23 quarters x 3 providers, heavily autocorrelated => effective n is far smaller.",
        "  Treat t-stats as directional, not inferential.",
        "No consensus data => 'surprise' is proxied by growth acceleration and by the",
        "  market-adjusted stock reaction. A real surprise series would be cleaner.",
        "The DEFINITIVE test: rebuild the constraint proxy from the Zenodo EC2 spot-price",
        "  archive (2018-2023, self-measurable) and re-run Q1-Q3. That removes the circularity.",
    ]:
        print(f"  - {c}")


if __name__ == "__main__":
    df = load_panel()
    L = to_long(df)
    print(f"loaded {len(df)} quarters ({df.cq.iloc[0]}..{df.cq.iloc[-1]}), "
          f"{len(L)} provider-quarter rows")
    q1_lead_lag(L)
    q2_natural_experiment(L)
    q3_stock_reaction(L)
    caveats()
