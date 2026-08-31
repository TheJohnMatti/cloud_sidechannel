"""Render research/feasibility/spot_premium.png from spot_weekly_index.parquet."""
import pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = __file__.rsplit("/", 1)[0]
wk = pd.read_parquet(f"{HERE}/data/spot_weekly_index.parquet")
wk["week"] = pd.to_datetime(wk["week"])

fig, ax = plt.subplots(2, 1, figsize=(13, 8), sharex=True, height_ratios=[2, 1])
for sc, lab, c in [("all", "all families", "#2563eb"), ("gpu", "GPU families", "#dc2626"),
                   ("cpu", "non-GPU", "#94a3b8")]:
    s = wk[wk.scope == sc].set_index("week")["mean_premium"].sort_index().rolling(3).mean()
    ax[0].plot(s.index, s.values, label=lab, color=c, lw=1.6)

# episode shading
for lo, hi, c, txt in [
    ("2020-03-01", "2020-07-01", "orange", "COVID"),
    ("2023-03-15", "2023-10-01", "red", "AI round 1"),
    ("2024-08-01", "2025-06-01", "purple", "broad constraint\n(AWS+GCP join)"),
]:
    ax[0].axvspan(pd.Timestamp(lo), pd.Timestamp(hi), alpha=.09, color=c)
    ax[0].annotate(txt, xy=(pd.Timestamp(lo), 0.52), fontsize=8, color=c)

ax[0].set_ylabel("mean spot premium (spot / on-demand)")
ax[0].legend(loc="upper left")
ax[0].set_title("EC2 spot-price premium — self-measured cloud-capacity tightness (2018–2025)\n"
                "ISI archive 2018–2023  +  Pauley archive 2024–2025")
ax[0].grid(alpha=.3)

b = wk[wk.scope == "all"].set_index("week")["breadth_gt60"].sort_index().rolling(3).mean()
ax[1].fill_between(b.index, b.values, color="#2563eb", alpha=.4)
ax[1].set_ylabel("breadth\n(% pools >60% of OD)")
ax[1].grid(alpha=.3)

plt.tight_layout()
plt.savefig(f"{HERE}/spot_premium.png", dpi=110)
print(f"wrote {HERE}/spot_premium.png")
