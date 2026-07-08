import pandas as pd
import yfinance as yf
import time
import warnings
warnings.filterwarnings('ignore')

# ── 1. 종목 목록 로드 ─────────────────────────────────────────────
universe = pd.read_csv('../data/stock_universe.csv')
tickers = universe['ticker'].tolist()
print(f"종목 수: {len(tickers)}개")

# ── 2. 수익률 계산 (최근 200일 배치 다운로드) ─────────────────────
print("가격 데이터 다운로드 중...")
prices = yf.download(tickers, period='200d', auto_adjust=True, progress=True)['Close']
prices = prices.dropna(how='all')

latest = prices.iloc[-1]
p20  = prices.iloc[-21]  if len(prices) > 20  else None
p60  = prices.iloc[-61]  if len(prices) > 60  else None
p180 = prices.iloc[-181] if len(prices) > 180 else None

def ret(latest, past):
    if past is None:
        return pd.Series(dtype=float)
    return ((latest - past) / past * 100).round(2)

ret20  = ret(latest, p20)
ret60  = ret(latest, p60)
ret180 = ret(latest, p180)

# ── 3. PER 수집 (info 재호출) ─────────────────────────────────────
print("\nPER 수집 중...")
per_data = {}
for i, ticker in enumerate(tickers, 1):
    try:
        info = yf.Ticker(ticker).info
        per_data[ticker] = {
            'trailing_pe': info.get('trailingPE'),
            'forward_pe':  info.get('forwardPE'),
        }
        pe_str = f"{info.get('trailingPE', 'N/A'):.1f}" if info.get('trailingPE') else 'N/A'
        print(f"[{i:3}/{len(tickers)}] {ticker:6} | PER(trailing)={pe_str}")
    except Exception as e:
        per_data[ticker] = {'trailing_pe': None, 'forward_pe': None}
        print(f"[{i:3}/{len(tickers)}] {ticker:6} | ERROR")

    if i % 20 == 0:
        time.sleep(0.5)

# ── 4. 합치기 ─────────────────────────────────────────────────────
pe_df = pd.DataFrame(per_data).T.reset_index().rename(columns={'index': 'ticker'})

result = universe.merge(pe_df, on='ticker', how='left')

result['ret_20d']  = result['ticker'].map(ret20)
result['ret_60d']  = result['ticker'].map(ret60)
result['ret_180d'] = result['ticker'].map(ret180)

# 시총 기준 정렬
result = result.sort_values('market_cap', ascending=False)

# 컬럼 순서 정리
cols = [
    'ticker', 'company', 'sector', 'industry', 'country',
    'market_cap', 'market_cap_str',
    'fiscal_year_end_month',
    'ret_20d', 'ret_60d', 'ret_180d',
    'trailing_pe', 'forward_pe',
    'biz_model',
]
result = result[cols]

# PER 소수점 정리
result['trailing_pe'] = result['trailing_pe'].apply(lambda x: round(x, 1) if pd.notna(x) else '')
result['forward_pe']  = result['forward_pe'].apply(lambda x: round(x, 1) if pd.notna(x) else '')

# 수익률에 % 부호
for col in ['ret_20d', 'ret_60d', 'ret_180d']:
    result[col] = result[col].apply(lambda x: f"{x:+.1f}%" if pd.notna(x) else '')

result.to_csv('../data/stock_universe.csv', index=False, encoding='utf-8-sig')
print(f"\n✅ 저장 완료: data/stock_universe.csv")

# ── 5. 콘솔 미리보기 ─────────────────────────────────────────────
print("\n" + "="*110)
print(f"{'티커':8} {'섹터':25} {'국가':15} {'시총':8} {'20일':8} {'60일':8} {'180일':9} {'PER(T)':8} {'PER(F)':8}")
print("="*110)
for _, r in result.iterrows():
    print(f"{r['ticker']:8} {str(r['sector']):25} {str(r['country']):15} "
          f"{str(r['market_cap_str']):8} {str(r['ret_20d']):8} {str(r['ret_60d']):8} "
          f"{str(r['ret_180d']):9} {str(r['trailing_pe']):8} {str(r['forward_pe']):8}")
