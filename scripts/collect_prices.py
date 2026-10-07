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
BENCHMARK  = 'SPY'
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


def check_benchmark_lag(conn: sqlite3.Connection, end: str):
    """SPY 가격이 다른 종목보다 3일 넘게 뒤처지면 한 번 재시도하고, 그래도 뒤처지면 경고를 크게 남긴다.
    (SPY는 알파·백테스트의 벤치마크 — 멈춰 있으면 초과수익이 부풀려진다. 2026-06-18 정지 사례)"""
    def lag():
        latest = conn.execute("SELECT MAX(date) FROM daily_prices WHERE ticker != ?", (BENCHMARK,)).fetchone()[0]
        spy = conn.execute("SELECT MAX(date) FROM daily_prices WHERE ticker = ?", (BENCHMARK,)).fetchone()[0]
        if not latest or not spy:
            return 999, spy, latest
        return (date.fromisoformat(latest) - date.fromisoformat(spy)).days, spy, latest

    days, spy, latest = lag()
    if days <= 3:
        return
    print(f"  ⚠ 벤치마크 {BENCHMARK} 가격이 {days}일 뒤처짐 (SPY {spy} / 전체 {latest}) — 재시도")
    nxt = (date.fromisoformat(spy) + timedelta(days=1)).isoformat() if spy else START_DATE
    run_batches(conn, {BENCHMARK: nxt}, end)
    days, spy, latest = lag()
    if days > 3:
        print(f"  ⚠⚠ 벤치마크 {BENCHMARK} 가격 갱신 실패: SPY {spy} / 전체 {latest} ({days}일 차이) — "
              f"알파·백테스트 수치를 믿지 말고 확인할 것")


def main():
    parser = argparse.ArgumentParser(description='수정주가 수집 → prices.db')
    parser.add_argument('--full', action='store_true', help=f'{START_DATE}부터 강제 전체 재수집')
    args = parser.parse_args()

    univ    = pd.read_csv(UNIV)
    tickers = sorted(univ[univ['exclude_analysis'] == False]['ticker'].tolist())
    # 벤치마크(SPY)는 유니버스에 없어서 일일 수집이 한 번도 갱신하지 않았고 2026-06-18에서 멈춰 있었다
    # (compute_returns 알파·백테스트가 SPY를 쓰므로 7월 이후 수치가 영향을 받음) → 항상 포함한다.
    if BENCHMARK not in tickers:
        tickers = sorted(tickers + [BENCHMARK])
    print(f"대상: {len(tickers)}개 종목 (벤치마크 {BENCHMARK} 포함)\n")

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
    check_benchmark_lag(conn, end)
    conn.close()
    print(f"\n완료  총 {total:,}행 저장")


if __name__ == '__main__':
    main()
