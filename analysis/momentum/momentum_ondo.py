import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ── 1. 개별 주식만 필터링 ──────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    'ETF', 'Fund', 'Trust', 'iShares', 'SPDR', 'Vanguard', 'ProShares',
    'WisdomTree', 'VanEck', 'Global X', 'Franklin', 'Sprott', 'PIMCO',
    'abrdn', 'Janus Henderson', 'First Trust', 'KraneShares', 'Invesco DB',
    'US Natural Gas', 'US Brent Oil', 'United States Oil', 'Physical',
    'US Brent', 'Commodity', 'Bond ETF', 'Treasury', 'High Yield',
    'Uranium ETF', 'Copper Miners', 'Oil Services',
]

df_raw = pd.read_csv('ondo_tokenized_stocks.csv')

def is_individual_stock(name):
    return not any(kw.lower() in name.lower() for kw in EXCLUDE_KEYWORDS)

df_stocks = df_raw[df_raw['name'].apply(is_individual_stock)].copy()

# 심볼 끝 "ON" 제거 → 실제 티커
df_stocks['ticker'] = df_stocks['symbol'].str[:-2]

print(f"개별 주식 종목 수: {len(df_stocks)}")
print(df_stocks[['symbol', 'ticker', 'name']].head(10).to_string(index=False))

# ── 2. Yahoo Finance 10년 데이터 다운로드 ─────────────────────────
END   = datetime.today()
START = END - timedelta(days=365 * 10)

tickers = df_stocks['ticker'].tolist()

print(f"\n데이터 다운로드 중 ({len(tickers)}개 티커)...")
raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=True)

# Close 가격만 추출
if isinstance(raw.columns, pd.MultiIndex):
    prices = raw['Close']
else:
    prices = raw[['Close']]

# 데이터 충분한 종목만 (최소 500거래일 = 약 2년)
valid_cols = prices.columns[prices.count() >= 500].tolist()
prices = prices[valid_cols].dropna(how='all')

print(f"\n유효 종목 수: {len(valid_cols)}")
print(f"기간: {prices.index[0].date()} ~ {prices.index[-1].date()}")

# ── 3. 20일 수익률 계산 ───────────────────────────────────────────
WINDOW = 20

ret_past   = prices.pct_change(WINDOW)          # 과거 20일 수익률
ret_future = prices.pct_change(WINDOW).shift(-WINDOW)  # 미래 20일 수익률

# long format으로 변환
past_stack   = ret_past.stack().rename('ret_past')
future_stack = ret_future.stack().rename('ret_future')

merged = pd.concat([past_stack, future_stack], axis=1).dropna()
merged.index.names = ['date', 'ticker']
merged = merged.reset_index()

# ── 4. 양수인 경우만 필터링 ──────────────────────────────────────
positive = merged[merged['ret_past'] > 0].copy()

print(f"\n전체 관측값: {len(merged):,}")
print(f"양수(과거 20일 수익률 > 0) 관측값: {len(positive):,} ({len(positive)/len(merged)*100:.1f}%)")

# ── 5. 상관관계 계산 ─────────────────────────────────────────────
corr_all      = merged['ret_past'].corr(merged['ret_future'])
corr_positive = positive['ret_past'].corr(positive['ret_future'])

print(f"\n전체 상관계수 (Pearson):          {corr_all:.4f}")
print(f"양수 구간 상관계수 (Pearson):     {corr_positive:.4f}")

# 종목별 상관계수
per_ticker = (
    positive.groupby('ticker')
    .apply(lambda g: g['ret_past'].corr(g['ret_future']) if len(g) > 30 else np.nan)
    .dropna()
    .sort_values(ascending=False)
)
print(f"\n종목별 양수 구간 상관계수 (상위 10):")
print(per_ticker.head(10).to_string())
print(f"\n종목별 양수 구간 상관계수 (하위 10):")
print(per_ticker.tail(10).to_string())
print(f"\n종목별 평균 상관계수: {per_ticker.mean():.4f}")
print(f"양의 상관 종목 비율: {(per_ticker > 0).mean()*100:.1f}%")

# ── 6. 시각화 ─────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(18, 6))
fig.suptitle('Ondo Tokenized Stocks — 20-Day Momentum Analysis\n(Positive Past Return Only)', fontsize=14)

# (A) 산점도: 과거 vs 미래 20일 수익률
ax = axes[0]
sample = positive.sample(min(5000, len(positive)), random_state=42)
ax.scatter(sample['ret_past'] * 100, sample['ret_future'] * 100,
           alpha=0.15, s=5, color='steelblue')
ax.axhline(0, color='red', linewidth=0.8, linestyle='--')
ax.axvline(0, color='gray', linewidth=0.5, linestyle='--')
# 회귀선
m, b = np.polyfit(sample['ret_past'], sample['ret_future'], 1)
x_line = np.linspace(sample['ret_past'].min(), sample['ret_past'].max(), 100)
ax.plot(x_line * 100, (m * x_line + b) * 100, 'r-', linewidth=1.5)
ax.set_xlabel('Past 20-Day Return (%)')
ax.set_ylabel('Future 20-Day Return (%)')
ax.set_title(f'Scatter Plot\nCorr = {corr_positive:.4f}')
ax.set_xlim([-5, 100])
ax.set_ylim([-60, 100])

# (B) 종목별 상관계수 분포 (히스토그램)
ax = axes[1]
ax.hist(per_ticker.values, bins=30, color='steelblue', edgecolor='white', linewidth=0.5)
ax.axvline(0, color='red', linewidth=1.5, linestyle='--', label='r=0')
ax.axvline(per_ticker.mean(), color='orange', linewidth=1.5, linestyle='-',
           label=f'mean={per_ticker.mean():.3f}')
ax.set_xlabel('Correlation Coefficient')
ax.set_ylabel('Count')
ax.set_title(f'Per-Ticker Correlation Distribution\n(n={len(per_ticker)} tickers)')
ax.legend()

# (C) 분위별 미래 수익률 (십분위)
ax = axes[2]
positive['decile'] = pd.qcut(positive['ret_past'], q=10, labels=False) + 1
decile_stats = positive.groupby('decile')['ret_future'].agg(['mean', 'median', 'std'])
bars = ax.bar(decile_stats.index, decile_stats['mean'] * 100,
              color=['#d32f2f' if v < 0 else '#1976d2' for v in decile_stats['mean']],
              edgecolor='white')
ax.errorbar(decile_stats.index, decile_stats['mean'] * 100,
            yerr=decile_stats['std'] * 100 / 10, fmt='none', color='black', capsize=3)
ax.axhline(0, color='black', linewidth=0.8)
ax.set_xlabel('Past 20-Day Return Decile (1=Low, 10=High)')
ax.set_ylabel('Mean Future 20-Day Return (%)')
ax.set_title('Future Return by Past Return Decile')
ax.set_xticks(range(1, 11))

plt.tight_layout()
plt.savefig('momentum_ondo.png', dpi=150, bbox_inches='tight')
plt.show()
print("\n차트 저장: momentum_ondo.png")
