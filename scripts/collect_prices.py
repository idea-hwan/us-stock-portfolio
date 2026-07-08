"""
일별 수정주가 수집 → data/prices.db
실행: python scripts/collect_prices.py          # 증분 업데이트 (최초 실행 시 전체)
     python scripts/collect_prices.py --full    # 2006-01-01부터 강제 전체 재수집
"""

import argparse
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT      = Path(__file__).parent.parent
PRICES_DB = ROOT / 'data' / 'prices.db'
UNIV      = ROOT / 'data' / 'stock_universe.csv'

START_DATE = '2006-01-01'
BATCH_SIZE = 100


def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker    TEXT,
            date      TEXT,
            adj_close REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn.commit()


def last_dates(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT ticker, MAX(date) FROM daily_prices GROUP BY ticker"
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def fetch_batch(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """배치 다운로드 → (ticker, date, adj_close) DataFrame."""
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        return pd.DataFrame(columns=['ticker', 'date', 'adj_close'])

    # auto_adjust=True → Close 컬럼이 수정주가
    close = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw[['Close']].rename(columns={'Close': tickers[0]})

    # 배치 내 NaN: 전일가로 채움 (상장 전은 NaN 유지됨)
    close = close.ffill()

    close.index = pd.to_datetime(close.index).strftime('%Y-%m-%d')
    long = close.stack().reset_index()
    long.columns = ['date', 'ticker', 'adj_close']
    return long.dropna(subset=['adj_close'])[['ticker', 'date', 'adj_close']]


def upsert(conn: sqlite3.Connection, df: pd.DataFrame):
    conn.executemany(
        """INSERT INTO daily_prices (ticker, date, adj_close)
           VALUES (?, ?, ?)
           ON CONFLICT(ticker, date) DO UPDATE SET adj_close = excluded.adj_close""",
        df.itertuples(index=False, name=None),
    )
    conn.commit()


def run_batches(conn: sqlite3.Connection, start_map: dict[str, str], end: str):
    """start_map: {ticker: start_date}를 시작일별로 묶어 배치 실행."""
    by_start: dict[str, list[str]] = defaultdict(list)
    for t, s in start_map.items():
        by_start[s].append(t)

    total = 0
    for start, group in sorted(by_start.items()):
        print(f"  [{start} → {end}]  {len(group)}개 종목")
        for i in range(0, len(group), BATCH_SIZE):
            chunk = group[i:i + BATCH_SIZE]
            df = fetch_batch(chunk, start, end)
            if df.empty:
                print(f"    청크 {i // BATCH_SIZE + 1}: 데이터 없음")
                continue
            upsert(conn, df)
            total += len(df)
            print(f"    청크 {i // BATCH_SIZE + 1}: {len(df):,}행 저장")
    return total


def main():
    parser = argparse.ArgumentParser(description='수정주가 수집 → prices.db')
    parser.add_argument('--full', action='store_true', help=f'{START_DATE}부터 강제 전체 재수집')
    args = parser.parse_args()

    univ    = pd.read_csv(UNIV)
    tickers = sorted(univ[univ['exclude_analysis'] == False]['ticker'].tolist())
    print(f"대상: {len(tickers)}개 종목\n")

    conn = sqlite3.connect(PRICES_DB)
    init_db(conn)

    end = date.today().strftime('%Y-%m-%d')

    if args.full:
        start_map = {t: START_DATE for t in tickers}
        print(f"전체 재수집: {START_DATE} → {end}")
    else:
        last = last_dates(conn)
        start_map = {}
        for t in tickers:
            if t not in last:
                start_map[t] = START_DATE
            else:
                nxt = (date.fromisoformat(last[t]) + timedelta(days=1)).isoformat()
                if nxt <= end:
                    start_map[t] = nxt

        if not start_map:
            print("모든 종목 최신 상태 — 업데이트 불필요")
            conn.close()
            return

        new  = sum(1 for t, s in start_map.items() if s == START_DATE)
        upd  = len(start_map) - new
        print(f"신규 {new}개 (전체 히스토리)  /  업데이트 {upd}개 (증분)")

    total = run_batches(conn, start_map, end)
    conn.close()
    print(f"\n완료  총 {total:,}행 저장")


if __name__ == '__main__':
    main()
