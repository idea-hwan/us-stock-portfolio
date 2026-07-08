"""
전체 유니버스 TTM 시계열 계산 → ttm_valuation.db
실행: python scripts/compute_ttm.py
     python scripts/compute_ttm.py --ticker AAPL
"""

import argparse
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path

ROOT   = Path(__file__).parent.parent
SRC_DB = ROOT / 'data' / 'stocks.db'
TTM_DB = ROOT / 'data' / 'ttm_valuation.db'
UNIV   = ROOT / 'data' / 'stock_universe.csv'

FLOW = ['revenue', 'operating_income', 'net_income', 'cfo', 'capex']
SNAP = ['total_assets', 'total_equity', 'shares_diluted']


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ttm_financials (
            ticker          TEXT,
            anchor_term     TEXT,
            q1_term         TEXT,
            q2_term         TEXT,
            q3_term         TEXT,
            q4_term         TEXT,
            ttm_revenue     INTEGER,
            ttm_op_income   INTEGER,
            ttm_net_income  INTEGER,
            ttm_cfo         INTEGER,
            ttm_capex       INTEGER,
            ttm_fcf         INTEGER,
            total_assets    INTEGER,
            total_equity    INTEGER,
            shares_diluted  INTEGER,
            computed_at     TEXT,
            PRIMARY KEY (ticker, anchor_term)
        )
    """)
    conn.commit()


def sort_key(term: str, fy_end: int) -> int:
    y, q = int(term[:4]), int(term[5])
    m = fy_end - (4 - q) * 3
    if m <= 0:
        m += 12
    cy = y - 1 if m > fy_end else y
    return cy * 12 + m


def compute_ttm(df: pd.DataFrame, fy_end: int) -> list[dict]:
    df = df.copy()
    df['sk'] = df['term'].apply(lambda t: sort_key(t, fy_end))
    df = df.sort_values('sk').reset_index(drop=True)

    rows = []
    for i in range(3, len(df)):
        window = df.iloc[i - 3:i + 1]
        anchor = df.iloc[i]['term']

        row = {
            'anchor_term': anchor,
            'q1_term': window['term'].iloc[0],
            'q2_term': window['term'].iloc[1],
            'q3_term': window['term'].iloc[2],
            'q4_term': window['term'].iloc[3],
        }

        for c in FLOW:
            vals = window[c].tolist()
            col  = 'ttm_op_income' if c == 'operating_income' else f'ttm_{c}'
            row[col] = int(sum(vals)) if all(pd.notna(v) for v in vals) else None

        cfo = row.get('ttm_cfo')
        cap = row.get('ttm_capex')
        row['ttm_fcf'] = (cfo - cap) if (cfo is not None and cap is not None) else None

        for c in SNAP:
            snap = window[c].dropna()
            row[c] = int(snap.iloc[-1]) if not snap.empty else None

        rows.append(row)
    return rows


def upsert(conn: sqlite3.Connection, ticker: str, rows: list[dict], now: str):
    data = [
        (
            ticker, r['anchor_term'],
            r['q1_term'], r['q2_term'], r['q3_term'], r['q4_term'],
            r.get('ttm_revenue'), r.get('ttm_op_income'), r.get('ttm_net_income'),
            r.get('ttm_cfo'), r.get('ttm_capex'), r.get('ttm_fcf'),
            r.get('total_assets'), r.get('total_equity'), r.get('shares_diluted'),
            now,
        )
        for r in rows
    ]
    conn.executemany("""
        INSERT INTO ttm_financials
            (ticker, anchor_term, q1_term, q2_term, q3_term, q4_term,
             ttm_revenue, ttm_op_income, ttm_net_income,
             ttm_cfo, ttm_capex, ttm_fcf,
             total_assets, total_equity, shares_diluted, computed_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker, anchor_term) DO UPDATE SET
            q1_term        = excluded.q1_term,
            q2_term        = excluded.q2_term,
            q3_term        = excluded.q3_term,
            q4_term        = excluded.q4_term,
            ttm_revenue    = excluded.ttm_revenue,
            ttm_op_income  = excluded.ttm_op_income,
            ttm_net_income = excluded.ttm_net_income,
            ttm_cfo        = excluded.ttm_cfo,
            ttm_capex      = excluded.ttm_capex,
            ttm_fcf        = excluded.ttm_fcf,
            total_assets   = excluded.total_assets,
            total_equity   = excluded.total_equity,
            shares_diluted = excluded.shares_diluted,
            computed_at    = excluded.computed_at
    """, data)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ticker', action='append', default=None)
    parser.add_argument('--all', action='store_true', help='제외 섹터 포함 전체 처리')
    args = parser.parse_args()

    univ   = pd.read_csv(UNIV)
    fy_map = dict(zip(univ['ticker'], univ['fiscal_year_end_month'].fillna(12).astype(int)))

    src  = sqlite3.connect(SRC_DB)
    df_all = pd.read_sql("SELECT * FROM quarterly_financials", src)
    src.close()

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    elif args.all:
        tickers = sorted(df_all['ticker'].unique())
    else:
        eligible = set(univ[univ['exclude_analysis'] == False]['ticker'])
        tickers = sorted(t for t in df_all['ticker'].unique() if t in eligible)
    print(f"TTM 계산 대상: {len(tickers)}개 종목\n")

    ttm_conn = sqlite3.connect(TTM_DB)
    init_db(ttm_conn)

    now = datetime.utcnow().isoformat()
    ok = skip = 0

    for i, ticker in enumerate(tickers, 1):
        fy_end = fy_map.get(ticker, 12)
        df = df_all[df_all['ticker'] == ticker]
        if len(df) < 4:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | 분기 부족({len(df)}개) — skip")
            skip += 1
            continue

        rows = compute_ttm(df, fy_end)
        if not rows:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | TTM 행 없음 — skip")
            skip += 1
            continue

        upsert(ttm_conn, ticker, rows, now)
        print(f"[{i:3}/{len(tickers)}] {ticker:8} | {len(rows)}개 저장")
        ok += 1

    ttm_conn.close()
    print(f"\n완료  성공 {ok}  /  스킵 {skip}")


if __name__ == '__main__':
    main()
