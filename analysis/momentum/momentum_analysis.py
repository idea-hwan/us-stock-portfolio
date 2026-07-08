"""
Binance Alpha Tokenized Stocks - Weekly Momentum Analysis
Universe: AAPL, TSLA, NVDA, META, AMZN, MSFT, GOOGL, QQQ, CRCL
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy import stats
from datetime import datetime, timedelta

# ── Universe ──────────────────────────────────────────────────────────────────
TICKERS = {
    "AAPL":  "Apple",
    "MSFT":  "Microsoft",
    "NVDA":  "NVIDIA",
    "AMZN":  "Amazon",
    "GOOGL": "Alphabet",
    "META":  "Meta",
    "TSLA":  "Tesla",
    "QQQ":   "Nasdaq-100 ETF",
}
# CRCL은 2025년 상장이라 별도 처리
TICKERS_SHORT = {"CRCL": "Circle"}

START = "2015-01-01"
END   = datetime.today().strftime("%Y-%m-%d")

# ── Data Download ─────────────────────────────────────────────────────────────
print("Downloading price data from Yahoo Finance...")

raw = yf.download(
    list(TICKERS.keys()),
    start=START, end=END,
    interval="1wk",
    auto_adjust=True,
    progress=False
)["Close"]

raw_short = yf.download(
    list(TICKERS_SHORT.keys()),
    start="2025-01-01", end=END,
    interval="1wk",
    auto_adjust=True,
    progress=False
)["Close"]

# Weekly returns
returns = raw.pct_change().dropna(how="all")
returns_short = raw_short.pct_change().dropna(how="all")

if isinstance(returns_short, pd.Series):
    returns_short = returns_short.to_frame(name="CRCL")

print(f"Data range : {returns.index[0].date()} ~ {returns.index[-1].date()}")
print(f"Weeks      : {len(returns)}")
print(f"Tickers    : {list(returns.columns)}")
print()

# ── 1. Time-series Autocorrelation (per stock) ────────────────────────────────
print("=" * 60)
print("1. Time-series Autocorrelation  (ret[t] vs ret[t+1])")
print("=" * 60)
print(f"{'Ticker':<8} {'r':>7} {'p-value':>10}  {'Significant?':>12}")
print("-" * 45)

ts_results = []
for col in returns.columns:
    s = returns[col].dropna()
    r, p = stats.pearsonr(s.iloc[:-1], s.iloc[1:])
    sig = "YES **" if p < 0.05 else ("marginal" if p < 0.10 else "no")
    print(f"{col:<8} {r:>+7.4f} {p:>10.4f}  {sig:>12}")
    ts_results.append({"ticker": col, "r": r, "p": p})

print()

# ── 2. Cross-sectional Rank Correlation ───────────────────────────────────────
print("=" * 60)
print("2. Cross-sectional Rank Correlation (weekly ranking persistence)")
print("   Spearman ρ: rank[t] vs rank[t+1]")
print("=" * 60)

# Drop weeks where any ticker is missing
ret_clean = returns.dropna()
ranks = ret_clean.rank(axis=1, ascending=True)  # 1 = worst, N = best

rho_list = []
for i in range(len(ranks) - 1):
    r1 = ranks.iloc[i].values
    r2 = ranks.iloc[i + 1].values
    rho, _ = stats.spearmanr(r1, r2)
    rho_list.append(rho)

rho_series = pd.Series(rho_list, index=ranks.index[:-1])
mean_rho  = rho_series.mean()
t_stat, p_val = stats.ttest_1samp(rho_series, 0)

print(f"Mean Spearman ρ : {mean_rho:+.4f}")
print(f"t-statistic     : {t_stat:+.4f}")
print(f"p-value         : {p_val:.4f}")
print(f"Significant (5%): {'YES **' if p_val < 0.05 else 'No'}")
print()

# ── 3. Top vs Bottom quintile returns ────────────────────────────────────────
print("=" * 60)
print("3. Winner / Loser Portfolio  (top half vs bottom half)")
print("   Rebalance weekly. Equal weight within group.")
print("=" * 60)

n = len(returns.columns)
winner_returns = []
loser_returns  = []

for i in range(len(ret_clean) - 1):
    row     = ret_clean.iloc[i]
    nxt_row = ret_clean.iloc[i + 1]
    sorted_tickers = row.sort_values(ascending=False).index

    top    = sorted_tickers[:n // 2]
    bottom = sorted_tickers[n // 2:]

    winner_returns.append(nxt_row[top].mean())
    loser_returns.append(nxt_row[bottom].mean())

winner_ser = pd.Series(winner_returns, index=ret_clean.index[1:])
loser_ser  = pd.Series(loser_returns,  index=ret_clean.index[1:])
long_short = winner_ser - loser_ser

ann = 52  # weekly → annual
print(f"Winner  ann. return : {winner_ser.mean() * ann * 100:+.2f}%")
print(f"Loser   ann. return : {loser_ser.mean()  * ann * 100:+.2f}%")
print(f"L/S spread (ann.)   : {long_short.mean() * ann * 100:+.2f}%")
t2, p2 = stats.ttest_1samp(long_short, 0)
print(f"L/S t-stat / p-val  : {t2:+.3f} / {p2:.4f}")
print()

# ── 4. Visualizations ────────────────────────────────────────────────────────
fig = plt.figure(figsize=(16, 14))
fig.suptitle("Binance Alpha Tokenized Stocks — Weekly Momentum Analysis\n"
             f"Universe: {', '.join(returns.columns.tolist())}  |  Period: {START} ~ {END}",
             fontsize=13, fontweight="bold", y=0.98)
gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

# 4-A: Per-stock autocorrelation bar chart
ax0 = fig.add_subplot(gs[0, :2])
df_ts = pd.DataFrame(ts_results).set_index("ticker")
colors = ["steelblue" if p < 0.05 else "lightgray" for p in df_ts["p"]]
bars = ax0.bar(df_ts.index, df_ts["r"], color=colors, edgecolor="black", linewidth=0.5)
ax0.axhline(0, color="black", linewidth=0.8)
ax0.set_title("(A) Time-series Autocorrelation  ret[t] → ret[t+1]", fontsize=11)
ax0.set_ylabel("Pearson r")
ax0.set_ylim(-0.3, 0.3)
for bar, (_, row) in zip(bars, df_ts.iterrows()):
    ax0.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 0.005 * np.sign(row["r"] + 1e-9),
             f"{row['r']:+.3f}", ha="center", va="bottom", fontsize=8.5)
ax0.text(0.98, 0.95, "Blue = p<0.05", transform=ax0.transAxes,
         ha="right", va="top", fontsize=9, color="steelblue")

# 4-B: Rolling Spearman rho (52-week window)
ax1 = fig.add_subplot(gs[0, 2])
roll_rho = rho_series.rolling(52).mean()
ax1.plot(roll_rho, color="darkorange", linewidth=1.2)
ax1.axhline(0, color="black", linewidth=0.8, linestyle="--")
ax1.fill_between(roll_rho.index, roll_rho, 0,
                 where=(roll_rho > 0), alpha=0.25, color="green", label="positive")
ax1.fill_between(roll_rho.index, roll_rho, 0,
                 where=(roll_rho < 0), alpha=0.25, color="red", label="negative")
ax1.set_title("(B) Rolling 52-wk Spearman ρ", fontsize=11)
ax1.set_ylabel("ρ")
ax1.legend(fontsize=8)

# 4-C: Scatter — rank[t] vs rank[t+1]
ax2 = fig.add_subplot(gs[1, :2])
all_r1 = []
all_r2 = []
for i in range(len(ranks) - 1):
    all_r1.extend(ranks.iloc[i].values)
    all_r2.extend(ranks.iloc[i + 1].values)

ax2.scatter(all_r1, all_r2, alpha=0.08, s=8, color="royalblue")
m, b = np.polyfit(all_r1, all_r2, 1)
xs = np.linspace(1, n, 50)
ax2.plot(xs, m * xs + b, color="red", linewidth=1.5)
ax2.set_title(f"(C) Cross-sectional Rank Persistence  (ρ={mean_rho:+.4f}, p={p_val:.4f})", fontsize=11)
ax2.set_xlabel("Rank this week  (1=worst, N=best)")
ax2.set_ylabel("Rank next week")

# 4-D: Winner / Loser cumulative wealth
ax3 = fig.add_subplot(gs[1, 2])
cum_w = (1 + winner_ser).cumprod()
cum_l = (1 + loser_ser).cumprod()
cum_ls = (1 + long_short).cumprod()
ax3.plot(cum_w,  label="Winner (top half)",  color="green",     linewidth=1.2)
ax3.plot(cum_l,  label="Loser  (btm half)",  color="red",       linewidth=1.2)
ax3.plot(cum_ls, label="L/S spread",         color="black",     linewidth=1.2, linestyle="--")
ax3.axhline(1, color="gray", linewidth=0.5)
ax3.set_title("(D) Cumulative Wealth", fontsize=11)
ax3.set_ylabel("Growth of $1")
ax3.legend(fontsize=7.5)

# 4-E: Distribution of L/S weekly returns
ax4 = fig.add_subplot(gs[2, :2])
ax4.hist(long_short * 100, bins=60, color="steelblue", edgecolor="white", linewidth=0.3)
ax4.axvline(long_short.mean() * 100, color="red", linewidth=1.5,
            label=f"Mean={long_short.mean()*100:+.2f}%")
ax4.axvline(0, color="black", linewidth=0.8, linestyle="--")
ax4.set_title("(E) Distribution of Weekly L/S Return", fontsize=11)
ax4.set_xlabel("Weekly L/S return (%)")
ax4.set_ylabel("Frequency")
ax4.legend(fontsize=9)

# 4-F: Summary text
ax5 = fig.add_subplot(gs[2, 2])
ax5.axis("off")
lines = [
    "── Summary ──",
    "",
    f"Period : {START} ~ {END}",
    f"Weeks  : {len(returns)}",
    "",
    "Time-series AC",
    f"  Average r  : {df_ts['r'].mean():+.4f}",
    f"  Sig. stocks: {(df_ts['p']<0.05).sum()} / {len(df_ts)}",
    "",
    "Cross-sectional",
    f"  Mean ρ : {mean_rho:+.4f}",
    f"  p-value: {p_val:.4f}",
    f"  {'★ Significant' if p_val < 0.05 else '✗ Not significant'}",
    "",
    "Winner - Loser spread",
    f"  Ann. {long_short.mean()*ann*100:+.2f}%",
    f"  p-val : {p2:.4f}",
    f"  {'★ Significant' if p2 < 0.05 else '✗ Not significant'}",
]
ax5.text(0.05, 0.97, "\n".join(lines), transform=ax5.transAxes,
         va="top", fontsize=9, fontfamily="monospace",
         bbox=dict(boxstyle="round,pad=0.4", facecolor="lightyellow", alpha=0.8))

plt.savefig("momentum_analysis.png", dpi=150, bbox_inches="tight")
print("Chart saved: momentum_analysis.png")
plt.close()
print("Done.")
