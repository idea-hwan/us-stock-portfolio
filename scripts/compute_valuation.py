"""
분기별 밸류에이션 멀티플 계산 → data/valuation.db
  P/E · P/S · P/FCF · P/OP  (20일 평균 · 4년 평균)

실행: python scripts/compute_valuation.py
     python scripts/compute_valuation.py --ticker AAPL
     python scripts/compute_valuation.py --all
"""

import argparse
import calendar
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT   = Path(__file__).parent.parent
TTM_DB = ROOT / 'data' / 'ttm_valuation.db'
PX_DB  = ROOT / 'data' / 'prices.db'
VAL_DB = ROOT / 'data' / 'valuation.db'
UNIV   = ROOT / 'data' / 'stock_universe.csv'

# (컬럼 접두사, ttm_financials 컬럼명)
METRICS = [
    ('pe',   'ttm_net_income'),
    ('ps',   'ttm_revenue'),
    ('pfcf', 'ttm_fcf'),
    ('pop',  'ttm_op_income'),
]


# ── 공시 앵커일 ────────────────────────────────────────────────────────────────

def _quarter_end(term: str, fy_end: int) -> date:
    """회계분기 레이블 → 분기말 달력 날짜."""
    y, q = int(term[:4]), int(term[5])
    m = fy_end - (4 - q) * 3
    if m <= 0:
        m += 12
    cy = y - 1 if m > fy_end else y
    _, last_day = calendar.monthrange(cy, m)
    return date(cy, m, last_day)


def _filing_anchor(term: str, fy_end: int) -> date:
    """10-Q: 분기말 +45일  /  10-K(Q4): +60일."""
    qend = _quarter_end(term, fy_end)
    days = 60 if int(term[5]) == 4 else 45
    return qend + timedelta(days=days)


# ── DB 초기화 ──────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS valuation_multiples (
            ticker             TEXT,
            anchor_term        TEXT,
            filing_anchor_date TEXT,
            shares_latest      INTEGER,
            pe_20d             REAL,
            pe_4y              REAL,
            ps_20d             REAL,
            ps_4y              REAL,
            pfcf_20d           REAL,
            pfcf_4y            REAL,
            pop_20d            REAL,
            pop_4y             REAL,
            computed_at        TEXT,
            PRIMARY KEY (ticker, anchor_term)
        )
    """)
    conn.commit()


# ── 멀티플 계산 ────────────────────────────────────────────────────────────────

def compute_valuation(
    df_ttm: pd.DataFrame,
    px: pd.DataFrame,
    fy_end: int,
    latest_shares: int,
) -> list[dict]:
    """
    한 종목의 anchor_term별 멀티플 계산.

    P/E 등 = adj_close × latest_shares / ttm_value
      - adj_close는 분할 소급 ÷, latest_shares는 분할 소급 ×  → 상쇄 = 실제 시총 복원
      - 분모가 양수일 때만 계산 (적자 P/E 제외)
    """
    today = pd.Timestamp.today().normalize()

    px = px.copy()
    px['date'] = pd.to_datetime(px['date'])
    px = px.sort_values('date').reset_index(drop=True)

    df = df_ttm.sort_values('anchor_term').reset_index(drop=True)
    df['_anchor_d'] = df['anchor_term'].apply(
        lambda t: pd.Timestamp(_filing_anchor(t, fy_end))
    )

    # 메트릭별 일별 비율(4y 평균용): merge_asof로 filing 날짜 기준 step-function 유지
    daily_ratio: dict[str, pd.DataFrame] = {}
    for prefix, col in METRICS:
        basis_rows = []
        for _, row in df.iterrows():
            v = row[col]
            if pd.notna(v) and v > 0:
                basis_rows.append({
                    'date':  row['_anchor_d'],
                    'basis': float(v) / latest_shares,
                })
        if not basis_rows:
            daily_ratio[prefix] = pd.DataFrame(columns=['date', 'ratio'])
            continue

        basis_df = pd.DataFrame(basis_rows).sort_values('date')
        merged   = pd.merge_asof(px, basis_df, on='date', direction='backward')
        merged['ratio'] = merged['adj_close'] / merged['basis']
        merged['ratio'] = merged['ratio'].replace([np.inf, -np.inf], np.nan)
        daily_ratio[prefix] = merged[['date', 'ratio']]

    rows = []
    for _, row in df.iterrows():
        anchor_d = row['_anchor_d']
        cap_d    = min(anchor_d, today)   # 미래 날짜는 today로 캡

        # 앵커일 이전 20거래일 평균 주가
        px_20    = px[px['date'] <= cap_d].tail(20)
        avg_px20 = float(px_20['adj_close'].mean()) if not px_20.empty else None

        rec: dict = {
            'ticker':             row['ticker'],
            'anchor_term':        row['anchor_term'],
            'filing_anchor_date': anchor_d.strftime('%Y-%m-%d'),
            'shares_latest':      latest_shares,
        }

        for prefix, col in METRICS:
            v     = row[col]
            basis = float(v) / latest_shares if pd.notna(v) and v > 0 else None

            # 20일 평균가 ÷ 분모
            rec[f'{prefix}_20d'] = (avg_px20 / basis) if (basis and avg_px20) else None

            # 4년 일별 배수 평균
            dr   = daily_ratio[prefix]
            win  = dr[(dr['date'] > cap_d - pd.DateOffset(years=4)) & (dr['date'] <= cap_d)]
            vals = win['ratio'].dropna()
            rec[f'{prefix}_4y'] = float(vals.mean()) if len(vals) > 0 else None

        rows.append(rec)
    return rows


# ── DB 저장 ────────────────────────────────────────────────────────────────────

def upsert(conn: sqlite3.Connection, rows: list[dict], now: str):
    cols = [
        'ticker', 'anchor_term', 'filing_anchor_date', 'shares_latest',
        'pe_20d', 'pe_4y', 'ps_20d', 'ps_4y',
        'pfcf_20d', 'pfcf_4y', 'pop_20d', 'pop_4y', 'computed_at',
    ]
    ph  = ', '.join(['?'] * len(cols))
    upd = ', '.join(f'{c} = excluded.{c}' for c in cols if c not in ('ticker', 'anchor_term'))
    sql = (
        f"INSERT INTO valuation_multiples ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT(ticker, anchor_term) DO UPDATE SET {upd}"
    )
    data = [
        (
            r['ticker'], r['anchor_term'], r['filing_anchor_date'], r['shares_latest'],
            r.get('pe_20d'),  r.get('pe_4y'),
            r.get('ps_20d'),  r.get('ps_4y'),
            r.get('pfcf_20d'), r.get('pfcf_4y'),
            r.get('pop_20d'), r.get('pop_4y'),
            now,
        )
        for r in rows
    ]
    conn.executemany(sql, data)
    conn.commit()


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='밸류에이션 멀티플 계산 → valuation.db')
    parser.add_argument('--ticker', action='append', default=None, metavar='TICKER')
    parser.add_argument('--all',    action='store_true', help='제외 섹터 포함 전체 처리')
    args = parser.parse_args()

    univ   = pd.read_csv(UNIV)
    fy_map = dict(zip(univ['ticker'], univ['fiscal_year_end_month'].fillna(12).astype(int)))

    ttm_conn = sqlite3.connect(TTM_DB)
    df_all   = pd.read_sql("SELECT * FROM ttm_financials", ttm_conn)
    ttm_conn.close()

    px_conn  = sqlite3.connect(PX_DB)
    px_all   = pd.read_sql("SELECT ticker, date, adj_close FROM daily_prices", px_conn)
    px_conn.close()

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    elif args.all:
        tickers = sorted(df_all['ticker'].unique())
    else:
        eligible = set(univ[univ['exclude_analysis'] == False]['ticker'])
        tickers  = sorted(t for t in df_all['ticker'].unique() if t in eligible)

    print(f"멀티플 계산 대상: {len(tickers)}개 종목\n")

    val_conn = sqlite3.connect(VAL_DB)
    init_db(val_conn)
    from datetime import datetime
    now = datetime.utcnow().isoformat()
    ok = skip = 0

    for i, ticker in enumerate(tickers, 1):
        df_ttm = df_all[df_all['ticker'] == ticker].copy()
        df_px  = px_all[px_all['ticker'] == ticker].copy()

        if df_ttm.empty or df_px.empty:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | 데이터 없음 — skip")
            skip += 1
            continue

        # 최신 shares_diluted (분할 소급 완료 기준)
        shares_s = df_ttm.dropna(subset=['shares_diluted']).sort_values('anchor_term')
        if shares_s.empty:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | shares_diluted 없음 — skip")
            skip += 1
            continue
        latest_shares = int(shares_s.iloc[-1]['shares_diluted'])

        fy_end = fy_map.get(ticker, 12)
        rows   = compute_valuation(df_ttm, df_px, fy_end, latest_shares)
        upsert(val_conn, rows, now)
        print(f"[{i:3}/{len(tickers)}] {ticker:8} | {len(rows)}개 저장")
        ok += 1

    val_conn.close()
    print(f"\n완료  성공 {ok}  /  스킵 {skip}")


if __name__ == '__main__':
    main()
