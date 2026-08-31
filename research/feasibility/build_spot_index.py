"""
Parse the Zenodo EC2 spot-price archive -> a weekly capacity-tightness index.

Input : research/feasibility/data/raw/spot-YYYY.tar   (one .xz per region per day;
        each .xz is an AWS `describe-spot-price-history` text dump:
        SPOTINSTANCEPRICE <price> <ts> <instance_type> <product> <az>)
Output: research/feasibility/data/spot_daily.parquet   (date,region,az,instance_type,family,price,od_proxy,premium)
        research/feasibility/data/spot_weekly_index.parquet  (week,region,family,* aggregates)

Method:
  * Linux/UNIX only (drop Windows/SUSE — noisier, licence-driven).
  * Per daily snapshot file, take the LATEST price per (az, instance_type) => one
    obs per pool per day. This collapses the archive's built-in history redundancy.
  * On-demand proxy = 99.5th percentile of a pool's own spot price over the whole
    sample. Post-2017 AWS caps spot at on-demand, so max-spot ≈ on-demand. Gives a
    self-contained denominator with no external price feed.
  * premium = spot / od_proxy  in (0, 1].  Higher = tighter pool.
  * Weekly index per (region, family): mean premium, breadth (share of pools with
    premium > 0.6), p90 premium, n_pools.
"""
from __future__ import annotations
import tarfile, lzma, io, re, sys, glob
from collections import defaultdict
import numpy as np
import pandas as pd

HERE = __file__.rsplit("/", 1)[0]
RAW = f"{HERE}/data/raw"
OUT = f"{HERE}/data"

FNAME_RE = re.compile(r"data\.([a-z0-9-]+)\.(\d{4}-\d{2}-\d{2})T")
LINUX = ("Linux/UNIX", "Linux/UNIX (Amazon VPC)")

GPU_FAMILIES = {"p2", "p3", "p4", "p4d", "p4de", "p5", "p5e", "g2", "g3", "g4dn", "g5", "g5g", "g6", "gr6"}


def family(instance_type: str) -> str:
    return instance_type.split(".", 1)[0]


def parse_tar(path: str) -> pd.DataFrame:
    """One row per (date, region, az, instance_type): the latest price in that day's snapshot."""
    recs = []
    with tarfile.open(path, "r") as tar:
        for m in tar:
            if not m.name.endswith(".xz"):
                continue
            fm = FNAME_RE.search(m.name)
            if not fm:
                continue
            region, date = fm.group(1), fm.group(2)
            f = tar.extractfile(m)
            if f is None:
                continue
            try:
                raw = lzma.decompress(f.read())
            except lzma.LZMAError:
                continue
            latest: dict[tuple[str, str], tuple[str, float]] = {}
            for line in raw.decode("utf-8", "replace").splitlines():
                p = line.split("\t")
                if len(p) != 6 or p[0] != "SPOTINSTANCEPRICE":
                    continue
                _, price, ts, itype, product, az = p
                if product not in LINUX:
                    continue
                key = (az, itype)
                prev = latest.get(key)
                if prev is None or ts > prev[0]:
                    latest[key] = (ts, float(price))
            for (az, itype), (ts, price) in latest.items():
                recs.append((date, region, az, itype, family(itype), price))
    df = pd.DataFrame(recs, columns=["date", "region", "az", "instance_type", "family", "price"])
    return df


def build() -> None:
    tars = sorted(glob.glob(f"{RAW}/spot-*.tar"))
    if not tars:
        sys.exit(f"no tars in {RAW}")
    print(f"parsing {len(tars)} archives: {[t.rsplit('/',1)[1] for t in tars]}")
    parts = []
    for t in tars:
        d = parse_tar(t)
        print(f"  {t.rsplit('/',1)[1]:24s} {len(d):>9,} pool-days  "
              f"{d.date.min()}..{d.date.max()}  regions={d.region.nunique()}")
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(["date", "region", "az", "instance_type"])

    # on-demand proxy per instance_type (region-invariant approx; good enough)
    od = df.groupby("instance_type")["price"].quantile(0.995).rename("od_proxy")
    df = df.join(od, on="instance_type")
    df["premium"] = (df["price"] / df["od_proxy"]).clip(upper=1.0)
    df = df[df["od_proxy"] > 0]

    df.to_parquet(f"{OUT}/spot_daily.parquet", index=False)
    print(f"\nwrote spot_daily.parquet  {len(df):,} rows  "
          f"{df.date.min().date()}..{df.date.max().date()}")

    # ---- weekly index -------------------------------------------------------
    df["week"] = df["date"].dt.to_period("W-SUN").dt.start_time
    df["is_gpu"] = df["family"].isin(GPU_FAMILIES)

    def agg(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "mean_premium": g["premium"].mean(),
            "p90_premium": g["premium"].quantile(0.90),
            "breadth_gt60": (g["premium"] > 0.60).mean(),
            "n_pools": g["instance_type"].nunique(),
            "n_obs": len(g),
        })

    wk_all = df.groupby("week").apply(agg, include_groups=False).reset_index()
    wk_all["scope"] = "all"
    wk_gpu = df[df.is_gpu].groupby("week").apply(agg, include_groups=False).reset_index()
    wk_gpu["scope"] = "gpu"
    wk_cpu = df[~df.is_gpu].groupby("week").apply(agg, include_groups=False).reset_index()
    wk_cpu["scope"] = "cpu"
    wk_reg = (df.groupby(["week", "region"]).apply(agg, include_groups=False)
              .reset_index())
    wk_reg["scope"] = "region:" + wk_reg["region"]
    wk_reg = wk_reg.drop(columns="region")

    weekly = pd.concat([wk_all, wk_gpu, wk_cpu, wk_reg], ignore_index=True)
    weekly.to_parquet(f"{OUT}/spot_weekly_index.parquet", index=False)
    print(f"wrote spot_weekly_index.parquet  {len(weekly):,} rows  "
          f"scopes={weekly.scope.nunique()}")

    # quick console peek
    piv = (wk_all.set_index("week")["mean_premium"].resample("QS").mean())
    g = wk_gpu.set_index("week")["mean_premium"].resample("QS").mean()
    print("\n  quarter   all-mean-premium   gpu-mean-premium")
    for q in piv.index:
        gv = g.get(q, np.nan)
        print(f"  {q.date()}     {piv[q]:.3f}            {gv:.3f}")


if __name__ == "__main__":
    build()
