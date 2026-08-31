"""
Parse EC2 spot-price archives -> a weekly capacity-tightness index.

Two source formats, both handled:

  ISI / ANT lab  (data/raw/spot-YYYY.tar)   -- 2018-2023
      one .xz per region per day; each is an AWS `describe-spot-price-history`
      text dump:  SPOTINSTANCEPRICE <price> <ts> <instance_type> <product> <az>

  Pauley         (data/raw/pauley/YYYY-MM.tsv.zst)  -- 2024-2025
      ZStandard-compressed TSV, one row per price change:
      <az_global_id> \t <instance_type> \t <OS> \t <price> \t <iso_ts>
      (CC-BY-4.0, Eric Pauley / UW-Madison, DOI 10.5281/zenodo.14198917)

Output:
  data/spot_daily.parquet         date,region,az,instance_type,family,price,od_proxy,premium,source
  data/spot_weekly_index.parquet  week,scope,mean_premium,p90_premium,breadth_gt60,n_pools,n_obs

Method:
  * Linux/UNIX only (drop Windows/SUSE/RHEL -- licence-driven noise).
  * One price per (region, az, instance_type) per day = the latest that day.
  * On-demand proxy = 99.5th pctile of each instance type's own spot price over
    2022+ (AWS caps spot at on-demand; recent window avoids stale-high anchoring
    from pre-2020 on-demand cuts). Fallback to all-time for types absent post-2022.
  * premium = spot / od_proxy in (0,1]. Higher = tighter pool.
  * Weekly index: mean / p90 premium, breadth (share > 0.60), by all / gpu / cpu / region.

Limitation: Pauley is event-driven, so a pool with no price change in a given week
is absent that week (no cross-week fill). Active pools change often; sleepy pools
carry little signal. n_pools column exposes coverage.
"""
from __future__ import annotations
import tarfile, lzma, re, sys, glob, subprocess
import numpy as np
import pandas as pd

from az_regions import azid_to_region

HERE = __file__.rsplit("/", 1)[0]
RAW = f"{HERE}/data/raw"
OUT = f"{HERE}/data"

FNAME_RE = re.compile(r"data\.([a-z0-9-]+)\.(\d{4}-\d{2}-\d{2})T")
LINUX = {"Linux/UNIX", "Linux/UNIX (Amazon VPC)"}
GPU_FAMILIES = {"p2", "p3", "p3dn", "p4", "p4d", "p4de", "p5", "p5e", "p5en", "p6",
                "g2", "g3", "g3s", "g4dn", "g4ad", "g5", "g5g", "g6", "g6e", "gr6"}


def family(instance_type: str) -> str:
    return instance_type.split(".", 1)[0]


# --------------------------------------------------------------------------- #
def parse_tar(path: str) -> pd.DataFrame:
    """ISI format. One row per (date, region, az, instance_type) = latest that day."""
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
                k = (az, itype)
                prev = latest.get(k)
                if prev is None or ts > prev[0]:
                    latest[k] = (ts, float(price))
            for (az, itype), (ts, price) in latest.items():
                recs.append((date, region, az, itype, family(itype), price))
    return pd.DataFrame(recs, columns=["date", "region", "az", "instance_type", "family", "price"])


def parse_pauley(path: str) -> pd.DataFrame:
    """Pauley format. Stream `zstd -dc`, keep Linux/UNIX, latest price per pool per day."""
    proc = subprocess.Popen(["zstd", "-dc", path], stdout=subprocess.PIPE, bufsize=1 << 20)
    latest: dict[tuple[str, str, str], float] = {}  # (date, az_id, itype) -> price  (last wins; file is chronological)
    assert proc.stdout is not None
    for bline in proc.stdout:
        p = bline.split(b"\t")
        if len(p) != 5:
            continue
        az_id, itype, os_, price, ts = p
        if os_ != b"Linux/UNIX":
            continue
        date = ts[:10].decode()
        latest[(date, az_id.decode(), itype.decode())] = float(price)
    proc.wait()
    recs = []
    for (date, az_id, itype), price in latest.items():
        recs.append((date, azid_to_region(az_id), az_id, itype, family(itype), price))
    return pd.DataFrame(recs, columns=["date", "region", "az", "instance_type", "family", "price"])


# --------------------------------------------------------------------------- #
def build() -> None:
    parts = []
    for t in sorted(glob.glob(f"{RAW}/spot-*.tar")):
        d = parse_tar(t)
        d["source"] = "isi"
        print(f"  {t.rsplit('/',1)[1]:22s} {len(d):>10,} pool-days  {d.date.min()}..{d.date.max()}  regions={d.region.nunique()}")
        parts.append(d)
    for t in sorted(glob.glob(f"{RAW}/pauley/*.tsv.zst")):
        d = parse_pauley(t)
        d["source"] = "pauley"
        print(f"  {t.rsplit('/',1)[1]:22s} {len(d):>10,} pool-days  {d.date.min()}..{d.date.max()}  regions={d.region.nunique()}")
        parts.append(d)
    if not parts:
        sys.exit(f"no inputs in {RAW}")

    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    # ISI + Pauley overlap on 2022-2023; prefer ISI there (its daily-snapshot method
    # is what the round-1 results used). Pauley owns 2024+.
    df = df.sort_values("source")  # isi < pauley alphabetically -> isi kept by keep='first'
    df = df.drop_duplicates(["date", "region", "az", "instance_type"], keep="first")

    # on-demand proxy: recent-window 99.5th pctile, fallback all-time
    recent = df[df.date >= "2022-01-01"]
    od = recent.groupby("instance_type")["price"].quantile(0.995)
    od_all = df.groupby("instance_type")["price"].quantile(0.995)
    od = od.reindex(od_all.index).fillna(od_all).rename("od_proxy")
    df = df.join(od, on="instance_type")
    df = df[df["od_proxy"] > 0].copy()
    df["premium"] = (df["price"] / df["od_proxy"]).clip(upper=1.0)

    df.to_parquet(f"{OUT}/spot_daily.parquet", index=False)
    print(f"\nwrote spot_daily.parquet  {len(df):,} rows  {df.date.min().date()}..{df.date.max().date()}"
          f"  (isi={int((df.source=='isi').sum()):,}  pauley={int((df.source=='pauley').sum()):,})")

    # ---- weekly index -----------------------------------------------------
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

    frames = []
    for name, sub in [("all", df), ("gpu", df[df.is_gpu]), ("cpu", df[~df.is_gpu])]:
        w = sub.groupby("week").apply(agg, include_groups=False).reset_index()
        w["scope"] = name
        frames.append(w)
    wr = df.groupby(["week", "region"]).apply(agg, include_groups=False).reset_index()
    wr["scope"] = "region:" + wr["region"]
    frames.append(wr.drop(columns="region"))

    weekly = pd.concat(frames, ignore_index=True)
    weekly.to_parquet(f"{OUT}/spot_weekly_index.parquet", index=False)
    print(f"wrote spot_weekly_index.parquet  {len(weekly):,} rows  scopes={weekly.scope.nunique()}"
          f"  weeks {weekly.week.min().date()}..{weekly.week.max().date()}")

    # console peek
    wa = weekly[weekly.scope == "all"].set_index("week")["mean_premium"].resample("QS").mean()
    wg = weekly[weekly.scope == "gpu"].set_index("week")["mean_premium"].resample("QS").mean()
    wb = weekly[weekly.scope == "all"].set_index("week")["breadth_gt60"].resample("QS").mean()
    print("\n  quarter      all    gpu    breadth")
    for q in wa.index:
        print(f"  {q.date()}  {wa[q]:.3f}  {wg.get(q, np.nan):.3f}   {wb.get(q, np.nan):.3f}")


if __name__ == "__main__":
    build()
