"""
최신 분기 재무 × 오늘 가격으로 "현재" 밸류에이션 멀티플 계산
  P/E · P/S · P/FCF · P/OP (live)

`valuation.db`(분기별 20d/4y 배수, 공시 앵커일 기준)는 건드리지 않고
별도 캐시(`data/analytics/valuation_current.json`)에 저장한다.
분기 사이 기간에는 20d 배수가 최대 수개월 stale하므로, 이 캐시가
build_dashboard.py에서 "지금 이 순간" 기준 배수를 보여주는 용도.

실행: python scripts/compute_valuation_current.py
     python scripts/compute_valuation_current.py --ticker AAPL
     python scripts/compute_valuation_current.py --all
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT   = Path(__file__).parent.parent
TTM_DB = ROOT / 'data' / 'ttm_valuation.db'
PX_DB  = ROOT / 'data' / 'prices.db'
UNIV   = ROOT / 'data' / 'stock_universe.csv'
OUT    = ROOT / 'data' / 'analytics' / 'valuation_current.json'

# (출력 접두사, ttm_financials 컬럼명)
METRICS = [
    ('pe',   'ttm_net_income'),
    ('ps',   'ttm_revenue'),
    ('pfcf', 'ttm_fcf'),
    ('pop',  'ttm_op_income'),
]


def latest_ttm_row(df_ttm: pd.DataFrame) -> pd.Series:
    """종목별 최신 anchor_term 재무 (가장 최근 보고 분기 TTM)."""
    return df_ttm.sort_values('anchor_term').iloc[-1]


def latest_shares(df_ttm: pd.DataFrame) -> int | None:
    """최신 shares_diluted (NULL 아닌 것 중 가장 최근 anchor_term)."""
    s = df_ttm.dropna(subset=['shares_diluted']).sort_values('anchor_term')
    if s.empty:
        return None
    return int(s.iloc[-1]['shares_diluted'])


def compute_current(ticker: str, df_ttm: pd.DataFrame, df_px: pd.DataFrame) -> dict | None:
    if df_ttm.empty or df_px.empty:
        return None

    shares = latest_shares(df_ttm)
    if shares is None:
        return None

    ttm_row  = latest_ttm_row(df_ttm)
    px_row   = df_px.sort_values('date').iloc[-1]
    price    = float(px_row['adj_close'])
    price_dt = str(px_row['date'])[:10]

    rec = {
        'anchor_term': str(ttm_row['anchor_term']),
        'price':       round(price, 2),
        'price_date':  price_dt,
    }
    for prefix, col in METRICS:
        v = ttm_row[col]
        basis = float(v) / shares if pd.notna(v) and v > 0 else None
        rec[f'{prefix}_now'] = round(price / basis, 2) if basis else None
    return rec


def main():
    parser = argparse.ArgumentParser(description='현재 밸류에이션 멀티플 계산 → valuation_current.json')
    parser.add_argument('--ticker', action='append', default=None, metavar='TICKER')
    parser.add_argument('--all',    action='store_true', help='제외 섹터 포함 전체 처리')
    args = parser.parse_args()

    import sqlite3
    univ = pd.read_csv(UNIV)

    ttm_conn = sqlite3.connect(TTM_DB)
    df_all   = pd.read_sql("SELECT * FROM ttm_financials", ttm_conn)
    ttm_conn.close()

    px_conn = sqlite3.connect(PX_DB)
    px_all  = pd.read_sql("SELECT ticker, date, adj_close FROM daily_prices", px_conn)
    px_conn.close()

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    elif args.all:
        tickers = sorted(df_all['ticker'].unique())
    else:
        eligible = set(univ[univ['exclude_analysis'] == False]['ticker'])
        tickers  = sorted(t for t in df_all['ticker'].unique() if t in eligible)

    print(f"현재 멀티플 계산 대상: {len(tickers)}개 종목\n")

    now = datetime.now(timezone.utc).isoformat()
    out = {}
    if OUT.exists():
        out = json.loads(OUT.read_text())

    ok = skip = 0
    for i, ticker in enumerate(tickers, 1):
        df_ttm = df_all[df_all['ticker'] == ticker].copy()
        df_px  = px_all[px_all['ticker'] == ticker].copy()

        rec = compute_current(ticker, df_ttm, df_px)
        if rec is None:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | 데이터 없음 — skip")
            skip += 1
            continue

        rec['computed_at'] = now
        out[ticker] = rec
        print(f"[{i:3}/{len(tickers)}] {ticker:8} | P/E {rec.get('pe_now')} (기준일 {rec['price_date']})")
        ok += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n완료  성공 {ok}  /  스킵 {skip}  →  {OUT}")


if __name__ == '__main__':
    main()
