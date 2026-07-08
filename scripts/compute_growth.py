"""
TTM 시계열 기반 성장률 계산 → data/ttm_growth.db
실행: python scripts/compute_growth.py
     python scripts/compute_growth.py --ticker AAPL
     python scripts/compute_growth.py --ticker AAPL --ticker MSFT
     python scripts/compute_growth.py --all
"""

import argparse
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).parent.parent
TTM_DB  = ROOT / 'data' / 'ttm_valuation.db'
GROW_DB = ROOT / 'data' / 'ttm_growth.db'
UNIV    = ROOT / 'data' / 'stock_universe.csv'

# (DB 컬럼 접두사, ttm_financials 컬럼명)
METRICS = [
    ('rev',   'ttm_revenue'),
    ('op',    'ttm_op_income'),
    ('ni',    'ttm_net_income'),
    ('cfo',   'ttm_cfo'),
    ('capex', 'ttm_capex'),
    ('fcf',   'ttm_fcf'),
]
# (창 이름, 분기 수)
WINDOWS = [('1y', 4), ('2y', 8), ('4y', 16), ('8y', 32)]


def _growth_cols() -> list[str]:
    cols = []
    for prefix, _ in METRICS:
        cols += [f'{prefix}_cum_geom_pct', f'{prefix}_span_q']
        for wname, _ in WINDOWS:
            cols += [
                f'{prefix}_geom_{wname}_mcum',
                f'{prefix}_{wname}_q_empty',
                f'{prefix}_{wname}_q_minus',
            ]
    return cols


def init_db(conn: sqlite3.Connection):
    col_defs = ['ticker TEXT', 'anchor_term TEXT', 'computed_at TEXT']
    for prefix, _ in METRICS:
        col_defs += [
            f'{prefix}_cum_geom_pct REAL',
            f'{prefix}_span_q INTEGER',
        ]
        for wname, _ in WINDOWS:
            col_defs += [
                f'{prefix}_geom_{wname}_mcum REAL',
                f'{prefix}_{wname}_q_empty INTEGER',
                f'{prefix}_{wname}_q_minus INTEGER',
            ]
    col_defs.append('PRIMARY KEY (ticker, anchor_term)')
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS ttm_growth_series ({', '.join(col_defs)})"
    )
    conn.commit()


def _cum_geom(values: list) -> tuple[list, list]:
    """
    마지막 양수 앵커 기준 분기당 기하평균 성장률(%) 및 span.

    - 값이 양수일 때만 앵커를 갱신한다.
    - 0 이하 / None 구간은 성장률을 비워 두고 앵커를 유지한다.
    - 흑자 복귀 시: (현재 / 앵커)^(1/span) - 1
    - 연속 양수 구간(span=1): 단순 QoQ%와 동일.
    """
    n    = len(values)
    pct  = [None] * n
    span = [None] * n
    anchor_idx: int | None = None
    anchor_val: float | None = None

    for i, v in enumerate(values):
        if v is None or (isinstance(v, float) and pd.isna(v)) or v <= 0:
            pass  # 앵커 유지, 성장률 없음
        else:
            if anchor_idx is not None:
                s       = i - anchor_idx
                pct[i]  = ((float(v) / anchor_val) ** (1.0 / s) - 1.0) * 100.0
                span[i] = s
            anchor_idx = i
            anchor_val = float(v)

    return pct, span


def _window_stats(
    pct_series: list, raw_list: list, k: int
) -> tuple[list, list, list]:
    """
    k분기 창 누적 CAGR(%), q_empty, q_minus.

    - 창 [i-k+1, i]에서 데이터 범위(j>=0) 밖은 g_t=0 으로 처리.
    - 데이터 범위 내 pct 전부 None이면 geom=None.
    - product = ∏(1+g_t), None/범위 외 → g_t=0.
    - geom = (product^(1/k) - 1) * 100  (k는 항상 고정).
    """
    n       = len(pct_series)
    geom    = [None] * n
    q_empty = [None] * n
    q_minus = [None] * n

    for i in range(n):
        start    = i - k + 1
        lo       = max(0, start)
        in_range = pct_series[lo: i + 1]  # 실제 데이터 구간

        empty = sum(1 for g in in_range if g is None)
        q_empty[i] = empty
        q_minus[i] = sum(
            1 for j in range(lo, i + 1)
            if raw_list[j] is not None
            and not (isinstance(raw_list[j], float) and pd.isna(raw_list[j]))
            and raw_list[j] < 0
        )

        if empty == len(in_range):
            continue  # 모두 None → geom 유지(None)

        product = 1.0
        for j in range(start, i + 1):
            if 0 <= j < n and pct_series[j] is not None:
                product *= 1.0 + pct_series[j] / 100.0
            # j < 0 또는 None → g_t=0, product 변화 없음

        if product <= 0:
            continue
        geom[i] = (product ** (1.0 / k) - 1.0) * 100.0

    return geom, q_empty, q_minus


def compute_growth(df: pd.DataFrame) -> list[dict]:
    """anchor_term 오름차순 정렬 후 성장률 계산."""
    df = df.sort_values('anchor_term').reset_index(drop=True)

    # 메트릭별 분기성장률·span 계산
    pct_map:  dict[str, list] = {}
    span_map: dict[str, list] = {}
    for prefix, col in METRICS:
        pct_map[prefix], span_map[prefix] = _cum_geom(df[col].tolist())

    # 메트릭·창별 통계 사전 계산
    win_map: dict[str, dict[str, tuple]] = {}
    for prefix, col in METRICS:
        raw = df[col].tolist()
        win_map[prefix] = {
            wname: _window_stats(pct_map[prefix], raw, k)
            for wname, k in WINDOWS
        }

    rows = []
    for i in range(len(df)):
        row: dict = {
            'ticker':      df.at[i, 'ticker'],
            'anchor_term': df.at[i, 'anchor_term'],
        }
        for prefix, _ in METRICS:
            row[f'{prefix}_cum_geom_pct'] = pct_map[prefix][i]
            row[f'{prefix}_span_q']       = span_map[prefix][i]
            for wname, _ in WINDOWS:
                g, qe, qm = win_map[prefix][wname]
                row[f'{prefix}_geom_{wname}_mcum'] = g[i]
                row[f'{prefix}_{wname}_q_empty']   = qe[i]
                row[f'{prefix}_{wname}_q_minus']   = qm[i]
        rows.append(row)
    return rows


def upsert(conn: sqlite3.Connection, rows: list[dict], now: str):
    all_cols = ['ticker', 'anchor_term', 'computed_at'] + _growth_cols()
    placeholders = ', '.join(['?'] * len(all_cols))
    updates = ', '.join(
        f'{c} = excluded.{c}'
        for c in all_cols
        if c not in ('ticker', 'anchor_term')
    )
    sql = (
        f"INSERT INTO ttm_growth_series ({', '.join(all_cols)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(ticker, anchor_term) DO UPDATE SET {updates}"
    )
    data = [
        (row['ticker'], row['anchor_term'], now)
        + tuple(row.get(c) for c in _growth_cols())
        for row in rows
    ]
    conn.executemany(sql, data)
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description='TTM 성장률 계산 → ttm_growth.db')
    parser.add_argument('--ticker', action='append', default=None, metavar='TICKER')
    parser.add_argument('--all', action='store_true', help='제외 섹터 포함 전체 처리')
    args = parser.parse_args()

    univ = pd.read_csv(UNIV)

    ttm_conn = sqlite3.connect(TTM_DB)
    df_all   = pd.read_sql("SELECT * FROM ttm_financials", ttm_conn)
    ttm_conn.close()

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    elif args.all:
        tickers = sorted(df_all['ticker'].unique())
    else:
        eligible = set(univ[univ['exclude_analysis'] == False]['ticker'])
        tickers  = sorted(t for t in df_all['ticker'].unique() if t in eligible)

    print(f"성장률 계산 대상: {len(tickers)}개 종목\n")

    grow_conn = sqlite3.connect(GROW_DB)
    init_db(grow_conn)
    now = datetime.utcnow().isoformat()
    ok = skip = 0

    for i, ticker in enumerate(tickers, 1):
        df = df_all[df_all['ticker'] == ticker].copy()
        if len(df) < 2:
            print(f"[{i:3}/{len(tickers)}] {ticker:8} | 데이터 부족({len(df)}개) — skip")
            skip += 1
            continue

        rows = compute_growth(df)
        upsert(grow_conn, rows, now)
        print(f"[{i:3}/{len(tickers)}] {ticker:8} | {len(rows)}개 저장")
        ok += 1

    grow_conn.close()
    print(f"\n완료  성공 {ok}  /  스킵 {skip}")


if __name__ == '__main__':
    main()
