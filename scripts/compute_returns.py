"""
분기별 선행 수익률 + SPY 벤치마크 대비 초과수익 계산 → data/returns.db

entry: filing_anchor_date 당일(또는 직전 거래일) 종가
exit:  entry일 + 12 / 15 / 18 개월 이내 마지막 거래일 종가
ret    = exit / entry - 1
alpha  = ret - spy_ret  (같은 entry일 기준 SPY 수익률)

실행: python scripts/compute_returns.py
     python scripts/compute_returns.py --ticker AAPL
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT   = Path(__file__).parent.parent
VAL_DB = ROOT / 'data' / 'valuation.db'
PX_DB  = ROOT / 'data' / 'prices.db'
RET_DB = ROOT / 'data' / 'returns.db'

MONTHS = [3, 6, 9, 12, 15, 18, 24]


# ── DB 초기화 ──────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forward_returns (
            ticker             TEXT,
            anchor_term        TEXT,
            filing_anchor_date TEXT,
            entry_price        REAL,
            ret_3m             REAL,
            ret_6m             REAL,
            ret_9m             REAL,
            ret_12m            REAL,
            ret_15m            REAL,
            ret_18m            REAL,
            ret_24m            REAL,
            spy_ret_3m         REAL,
            spy_ret_6m         REAL,
            spy_ret_9m         REAL,
            spy_ret_12m        REAL,
            spy_ret_15m        REAL,
            spy_ret_18m        REAL,
            spy_ret_24m        REAL,
            alpha_3m           REAL,
            alpha_6m           REAL,
            alpha_9m           REAL,
            alpha_12m          REAL,
            alpha_15m          REAL,
            alpha_18m          REAL,
            alpha_24m          REAL,
            computed_at        TEXT,
            PRIMARY KEY (ticker, anchor_term)
        )
    """)
    # 기존 테이블에 새 컬럼 추가 (이미 존재하면 무시)
    new_cols = [
        ('ret_3m', 'REAL'), ('ret_6m', 'REAL'), ('ret_9m', 'REAL'), ('ret_24m', 'REAL'),
        ('spy_ret_3m', 'REAL'), ('spy_ret_6m', 'REAL'), ('spy_ret_9m', 'REAL'), ('spy_ret_24m', 'REAL'),
        ('alpha_3m', 'REAL'), ('alpha_6m', 'REAL'), ('alpha_9m', 'REAL'), ('alpha_24m', 'REAL'),
    ]
    existing = {r[1] for r in conn.execute("PRAGMA table_info(forward_returns)").fetchall()}
    for col, typ in new_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE forward_returns ADD COLUMN {col} {typ}")
    conn.commit()


# ── 수익률 계산 ────────────────────────────────────────────────────────────────

def _returns_from(px: pd.DataFrame, anchor_d: pd.Timestamp) -> tuple[float | None, dict]:
    """anchor_d 기준 entry 가격과 12/15/18m 수익률 반환."""
    before = px[px['date'] <= anchor_d]
    if before.empty:
        return None, {f'ret_{m}m': None for m in MONTHS}
    entry = float(before.iloc[-1]['adj_close'])
    if entry <= 0:
        return None, {f'ret_{m}m': None for m in MONTHS}

    rets = {}
    for m in MONTHS:
        target = anchor_d + pd.DateOffset(months=m)
        after  = px[px['date'] <= target]
        if after.empty or after.iloc[-1]['date'] <= anchor_d:
            rets[f'ret_{m}m'] = None
        else:
            rets[f'ret_{m}m'] = float(after.iloc[-1]['adj_close']) / entry - 1.0
    return entry, rets


def compute_ticker(
    ticker: str,
    df_anchors: pd.DataFrame,
    px: pd.DataFrame,
    spy: pd.DataFrame,
) -> list[dict]:
    rows = []
    for _, row in df_anchors.iterrows():
        anchor_d = pd.Timestamp(row['filing_anchor_date'])

        entry, rets    = _returns_from(px,  anchor_d)
        _,     spy_rets = _returns_from(spy, anchor_d)

        if entry is None:
            continue

        rec = {
            'ticker':             ticker,
            'anchor_term':        row['anchor_term'],
            'filing_anchor_date': row['filing_anchor_date'],
            'entry_price':        entry,
            **{f'ret_{m}m':     rets.get(f'ret_{m}m')     for m in MONTHS},
            **{f'spy_ret_{m}m': spy_rets.get(f'ret_{m}m') for m in MONTHS},
        }
        for m in MONTHS:
            r = rec[f'ret_{m}m']
            s = rec[f'spy_ret_{m}m']
            rec[f'alpha_{m}m'] = (r - s) if (r is not None and s is not None) else None

        rows.append(rec)
    return rows


# ── DB 저장 ────────────────────────────────────────────────────────────────────

def upsert(conn: sqlite3.Connection, rows: list[dict], now: str):
    cols = (
        ['ticker', 'anchor_term', 'filing_anchor_date', 'entry_price'] +
        [f'ret_{m}m'     for m in MONTHS] +
        [f'spy_ret_{m}m' for m in MONTHS] +
        [f'alpha_{m}m'   for m in MONTHS] +
        ['computed_at']
    )
    ph  = ', '.join(['?'] * len(cols))
    upd = ', '.join(f'{c} = excluded.{c}' for c in cols if c not in ('ticker', 'anchor_term'))
    sql = (
        f"INSERT INTO forward_returns ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT(ticker, anchor_term) DO UPDATE SET {upd}"
    )
    data = [
        (r['ticker'], r['anchor_term'], r['filing_anchor_date'], r['entry_price'],
         *[r.get(f'ret_{m}m')     for m in MONTHS],
         *[r.get(f'spy_ret_{m}m') for m in MONTHS],
         *[r.get(f'alpha_{m}m')   for m in MONTHS],
         now)
        for r in rows
    ]
    conn.executemany(sql, data)
    conn.commit()


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='선행 수익률 + alpha 계산 → returns.db')
    parser.add_argument('--ticker', action='append', default=None, metavar='TICKER')
    args = parser.parse_args()

    print("데이터 로드 중...")
    v_conn = sqlite3.connect(VAL_DB)
    df_val = pd.read_sql(
        "SELECT ticker, anchor_term, filing_anchor_date FROM valuation_multiples", v_conn)
    v_conn.close()

    px_conn = sqlite3.connect(PX_DB)
    df_px   = pd.read_sql("SELECT ticker, date, adj_close FROM daily_prices", px_conn)
    px_conn.close()
    df_px['date'] = pd.to_datetime(df_px['date'])

    spy = df_px[df_px['ticker'] == 'SPY'].sort_values('date').reset_index(drop=True)
    if spy.empty:
        raise RuntimeError("prices.db에 SPY 데이터 없음 — collect_prices.py 먼저 실행")

    tickers = [t.upper() for t in args.ticker] if args.ticker else sorted(df_val['ticker'].unique())
    print(f"수익률 계산 대상: {len(tickers)}개 종목\n")

    ret_conn = sqlite3.connect(RET_DB)
    init_db(ret_conn)
    now = datetime.utcnow().isoformat()
    ok = skip = 0

    for i, ticker in enumerate(tickers, 1):
        anchors = df_val[df_val['ticker'] == ticker]
        px      = df_px[df_px['ticker'] == ticker].sort_values('date').reset_index(drop=True)

        if anchors.empty or px.empty:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | skip")
            skip += 1
            continue

        rows = compute_ticker(ticker, anchors, px, spy)
        if rows:
            upsert(ret_conn, rows, now)
        print(f"[{i:3}/{len(tickers)}] {ticker:8} | {len(rows)}개")
        ok += 1

    ret_conn.close()
    print(f"\n완료  성공 {ok}  /  스킵 {skip}")


if __name__ == '__main__':
    main()
