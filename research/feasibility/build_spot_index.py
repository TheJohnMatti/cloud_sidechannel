"""
Parse EC2 spot-price archives -> a weekly capacity-tightness index.

Two source formats:
  ISI / ANT lab (data/raw/spot-YYYY.tar)          -- 2018-2023, daily snapshots
  Pauley        (data/raw/pauley/YYYY-MM.tsv.zst)  -- 2024-2025, per-price-change
                (CC-BY-4.0, Eric Pauley / UW-Madison, DOI 10.5281/zenodo.14198917)

Output:
  data/_parsed/*.parquet          per-file cache: date,region,az,instance_type,family,price
  data/spot_weekly_index.parquet  week,scope,mean_premium,p90_premium,breadth_gt60,n_pools,n_obs

Memory-bounded: per-file parses are cached, then the od-proxy pass and the weekly
aggregation pass each STREAM the cached parquets one at a time (never concatenated).

Method:
  * Linux/UNIX only.
  * One price per (region, az, instance_type) per day = latest that day.
  * On-demand proxy per instance type = median over 2022+ months of that month's
    max observed spot price (AWS caps spot at on-demand; median-of-maxes is robust
    to a single anomalous month). Fallback: all-time max.
  * premium = spot / od_proxy in (0,1]. Higher = tighter.
  * Weekly index by scope: all / gpu / cpu / region:<r>.
"""
from __future__ import annotations
import os, tarfile, lzma, re, sys, glob, subprocess
import numpy as np
import pandas as pd

from az_regions import azid_to_region

HERE = __file__.rsplit("/", 1)[0]
RAW = f"{HERE}/data/raw"
OUT = f"{HERE}/data"
PARSED = f"{OUT}/_parsed"

FNAME_RE = re.compile(r"data\.([a-z0-9-]+)\.(\d{4}-\d{2}-\d{2})T")
LINUX = {"Linux/UNIX", "Linux/UNIX (Amazon VPC)"}
GPU_FAMILIES = {"p2", "p3", "p3dn", "p4", "p4d", "p4de", "p5", "p5e", "p5en", "p6",
                "g2", "g3", "g3s", "g4dn", "g4ad", "g5", "g5g", "g6", "g6e", "gr6"}
NBINS = 200  # premium histogram resolution for percentiles


def family(it: str) -> str:
    return it.split(".", 1)[0]


# --------------------------------------------------------------------------- #
def parse_tar(path: str) -> pd.DataFrame:
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
    """Stream `zstd -dc`; last Linux/UNIX price per (day, az, instance_type)."""
    proc = subprocess.Popen(["zstd", "-dc", path], stdout=subprocess.PIPE, bufsize=1 << 20)
    latest: dict[tuple[str, str, str], float] = {}
    assert proc.stdout is not None
    for bline in proc.stdout:
        p = bline.split(b"\t")
        if len(p) != 5 or p[2] != b"Linux/UNIX":
            continue
        az_id, itype, _os, price, ts = p
        latest[(ts[:10].decode(), az_id.decode(), itype.decode())] = float(price)
    proc.wait()
    recs = [(d, azid_to_region(az), az, it, family(it), pr)
            for (d, az, it), pr in latest.items()]
    return pd.DataFrame(recs, columns=["date", "region", "az", "instance_type", "family", "price"])


def cache_path(tag: str, src: str, parser) -> str:
    st = os.stat(src)
    os.makedirs(PARSED, exist_ok=True)
    cp = f"{PARSED}/{tag}.{int(st.st_mtime)}.{st.st_size}.parquet"
    if not os.path.exists(cp):
        parser(src).to_parquet(cp, index=False)
    return cp


# --------------------------------------------------------------------------- #
def build() -> None:
    inputs = []  # (cache_parquet_path, source)
    for t in sorted(glob.glob(f"{RAW}/spot-*.tar")):
        inputs.append((cache_path(t.rsplit("/", 1)[1], t, parse_tar), "isi"))
    for t in sorted(glob.glob(f"{RAW}/pauley/*.tsv.zst")):
        inputs.append((cache_path("pauley-" + t.rsplit("/", 1)[1], t, parse_pauley), "pauley"))
    if not inputs:
        sys.exit(f"no inputs under {RAW}")
    print(f"{len(inputs)} source files")

    # ---- pass 1: on-demand proxy (streaming) ------------------------------
    monthly_max: dict[str, list[float]] = {}
    alltime_max: dict[str, float] = {}
    for cp, _src in inputs:
        d = pd.read_parquet(cp, columns=["date", "instance_type", "price"])
        if not len(d):
            continue
        mx = d.groupby("instance_type")["price"].max()
        recent = str(d["date"].iloc[0])[:7] >= "2022-01"
        for it, v in mx.items():
            alltime_max[it] = max(alltime_max.get(it, 0.0), float(v))
            if recent:
                monthly_max.setdefault(it, []).append(float(v))
    od_proxy = {it: float(np.median(v)) for it, v in monthly_max.items() if v}
    for it, v in alltime_max.items():
        od_proxy.setdefault(it, v)
    print(f"on-demand proxy for {len(od_proxy)} instance types "
          f"({sum(1 for it in monthly_max if monthly_max[it])} from 2022+ median-of-maxes)")

    # ---- pass 2: weekly aggregation (streaming accumulators) -------------
    # acc[scope][week] = [n_obs, sum_prem, n_gt60, hist(NBINS), set(instance_type)]
    from collections import defaultdict
    acc: dict[str, dict[pd.Timestamp, list]] = defaultdict(lambda: defaultdict(
        lambda: [0, 0.0, 0, np.zeros(NBINS, dtype=np.int64), set()]))

    for cp, src in inputs:
        d = pd.read_parquet(cp)
        d["date"] = pd.to_datetime(d["date"])
        d = d.drop_duplicates(["date", "region", "az", "instance_type"], keep="last")
        d["odp"] = d["instance_type"].map(od_proxy)
        d = d[d["odp"] > 0]
        d["premium"] = np.minimum(d["price"].to_numpy() / d["odp"].to_numpy(), 1.0)
        d["week"] = d["date"].dt.to_period("W-SUN").dt.start_time
        d["is_gpu"] = d["family"].isin(GPU_FAMILIES)
        d["bin"] = np.clip((d["premium"] * NBINS).astype(int), 0, NBINS - 1)

        def feed(scope: str, sub: pd.DataFrame) -> None:
            for wk, g in sub.groupby("week"):
                a = acc[scope][wk]
                a[0] += len(g)
                a[1] += float(g["premium"].sum())
                a[2] += int((g["premium"] > 0.60).sum())
                np.add.at(a[3], g["bin"].to_numpy(), 1)
                a[4].update(g["instance_type"].unique())

        feed("all", d)
        feed("gpu", d[d.is_gpu])
        feed("cpu", d[~d.is_gpu])
        for reg, sub in d.groupby("region"):
            feed(f"region:{reg}", sub)
        print(f"  {src:6s} {cp.rsplit('/',1)[1][:34]:34s} {len(d):>9,} rows  "
              f"{d.date.min().date()}..{d.date.max().date()}")

    # ---- emit ----------------------------------------------------------
    rows = []
    for scope, weeks in acc.items():
        for wk, (n, s, g60, hist, pools) in weeks.items():
            if n == 0:
                continue
            c = np.cumsum(hist)
            p90 = int(np.searchsorted(c, 0.90 * n)) / NBINS
            p50 = int(np.searchsorted(c, 0.50 * n)) / NBINS
            rows.append(dict(week=wk, scope=scope, mean_premium=s / n,
                             p50_premium=p50, p90_premium=p90,
                             breadth_gt60=g60 / n, n_pools=len(pools), n_obs=n))
    weekly = pd.DataFrame(rows).sort_values(["scope", "week"])
    weekly.to_parquet(f"{OUT}/spot_weekly_index.parquet", index=False)
    print(f"\nwrote spot_weekly_index.parquet  {len(weekly):,} rows  "
          f"{weekly.week.min().date()}..{weekly.week.max().date()}  scopes={weekly.scope.nunique()}")

    wa = weekly[weekly.scope == "all"].set_index("week")["mean_premium"].resample("QS").mean()
    wg = weekly[weekly.scope == "gpu"].set_index("week")["mean_premium"].resample("QS").mean()
    wb = weekly[weekly.scope == "all"].set_index("week")["breadth_gt60"].resample("QS").mean()
    print("\n  quarter      all    gpu    breadth")
    for q in wa.index:
        print(f"  {q.date()}  {wa[q]:.3f}  {wg.get(q, np.nan):.3f}   {wb.get(q, np.nan):.3f}")


if __name__ == "__main__":
    build()
