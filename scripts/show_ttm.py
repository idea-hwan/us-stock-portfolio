"""
단일 종목 TTM 시계열 조회
실행: python scripts/show_ttm.py AAPL
     python scripts/show_ttm.py NVDA
"""
import sys
import sqlite3
import pandas as pd
from pathlib import Path

ROOT   = Path(__file__).parent.parent
DB     = ROOT / 'data' / 'stocks.db'
UNIV   = ROOT / 'data' / 'stock_universe.csv'

FLOW = ['revenue', 'operating_income', 'net_income', 'cfo', 'capex']
SNAP = ['total_assets', 'total_equity', 'shares_diluted']

ticker = sys.argv[1].upper() if len(sys.argv) > 1 else 'AAPL'

univ   = pd.read_csv(UNIV)
fy_row = univ[univ['ticker'] == ticker]
if fy_row.empty:
    sys.exit(f'{ticker} 유니버스에 없음')
fy_end = int(fy_row.iloc[0]['fiscal_year_end_month'])

conn = sqlite3.connect(DB)
df   = pd.read_sql("SELECT * FROM quarterly_financials WHERE ticker=?", conn, params=(ticker,))
conn.close()

if df.empty:
    sys.exit(f'{ticker} 데이터 없음')

def sort_key(term):
    y, q = int(term[:4]), int(term[5])
    m = fy_end - (4 - q) * 3
    if m <= 0: m += 12
    cy = y - 1 if m > fy_end else y
    return cy * 12 + m

df['sk'] = df['term'].apply(sort_key)
df = df.sort_values('sk').reset_index(drop=True)

rows = []
for i in range(3, len(df)):
    window = df.iloc[i-3:i+1]
    anchor = df.iloc[i]['term']

    ttm = {'anchor': anchor,
           'q1': window['term'].iloc[0], 'q2': window['term'].iloc[1],
           'q3': window['term'].iloc[2], 'q4': window['term'].iloc[3]}

    for c in FLOW:
        vals = window[c].tolist()
        ttm[c] = int(sum(vals)) if all(pd.notna(v) for v in vals) else None

    for c in SNAP:
        snap = window[c].dropna()
        ttm[c] = int(snap.iloc[-1]) if not snap.empty else None

    ttm['fcf'] = (ttm['cfo'] - ttm['capex']) if (ttm['cfo'] is not None and ttm['capex'] is not None) else None

    sh = ttm['shares_diluted']
    def ps(val): return round(val / sh, 4) if (val is not None and sh) else None
    ttm['eps']        = ps(ttm['net_income'])
    ttm['revenue_ps'] = ps(ttm['revenue'])
    ttm['fcf_ps']     = ps(ttm['fcf'])
    rows.append(ttm)

ttm_df = pd.DataFrame(rows)

def fmt(v): return f"{int(v):>20,}" if v is not None else f"{'N/A':>20}"

print(f"\n{'='*150}")
print(f" {ticker}  TTM 시계열  (FY말={fy_end}월, {len(ttm_df)}개 스냅샷)  [USD, shares]")
print(f"{'='*150}")
print(f"{'anchor':>8}  {'q1':>8} {'q2':>8} {'q3':>8} {'q4':>8}  {'revenue':>20}  {'op_income':>20}  {'net_income':>20}  {'cfo':>20}  {'fcf':>20}  {'shares_diluted':>20}")
print(f"{'-'*150}")
for _, r in ttm_df.iterrows():
    print(f"{r['anchor']:>8}  {r['q1']:>8} {r['q2']:>8} {r['q3']:>8} {r['q4']:>8}"
          f"  {fmt(r['revenue'])}  {fmt(r['operating_income'])}  {fmt(r['net_income'])}"
          f"  {fmt(r['cfo'])}  {fmt(r['fcf'])}  {fmt(r['shares_diluted'])}")
print(f"{'='*150}")
