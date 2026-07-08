"""
STZ·V — yfinance get_shares_full로 shares_diluted 보정
- EDGAR에 shares 태그가 없는 종목만 대상
- 분기말 기준 가장 가까운 이전 날짜의 shares 값 사용
- 이미 OK인 분기는 COALESCE로 건드리지 않음
"""

import calendar
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

DB_PATH   = Path(__file__).parent.parent / 'data' / 'stocks.db'
UNIVERSE  = Path(__file__).parent.parent / 'data' / 'stock_universe.csv'

TARGETS = None   # None이면 shares_diluted NULL이 있는 모든 종목 자동 선택


def term_to_end_date(term: str, fy_end_month: int) -> date:
    year = int(term[:4])
    q    = int(term[5])
    end_month = fy_end_month - (4 - q) * 3
    if end_month <= 0:
        end_month += 12
        year -= 1
    _, last_day = calendar.monthrange(year, end_month)
    return date(year, end_month, last_day)


def get_shares_series(ticker: str) -> pd.Series:
    """yfinance get_shares_full → date 인덱스 시리즈 (tz 제거)"""
    t  = yf.Ticker(ticker)
    sf = t.get_shares_full(start='2010-01-01')
    if sf is None or sf.empty:
        return pd.Series(dtype=float)
    sf.index = sf.index.tz_localize(None).normalize()
    return sf.sort_index()


def lookup_shares(sf: pd.Series, end_date: date) -> int | None:
    """분기말 이전 가장 가까운 거래일의 shares 값"""
    cutoff = pd.Timestamp(end_date)
    past   = sf[sf.index <= cutoff]
    if past.empty:
        return None
    return int(past.iloc[-1])


def main():
    univ   = pd.read_csv(UNIVERSE)
    fy_map = dict(zip(univ['ticker'], univ['fiscal_year_end_month'].fillna(12).astype(int)))

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    targets = TARGETS
    if targets is None:
        cur.execute('''
            SELECT DISTINCT ticker FROM quarterly_financials
            WHERE shares_diluted IS NULL
            ORDER BY ticker
        ''')
        targets = [r[0] for r in cur.fetchall()]
        print(f'자동 선택: NULL 있는 종목 {len(targets)}개\n')

    for ticker in targets:
        fy_end = fy_map.get(ticker, 12)
        print(f'\n=== {ticker} (FY end month={fy_end}) ===')

        sf = get_shares_series(ticker)
        if sf.empty:
            print(f'  yfinance 데이터 없음 — 건너뜀')
            continue
        print(f'  yfinance 기간: {sf.index[0].date()} ~ {sf.index[-1].date()}  ({len(sf)}건)')

        cur.execute(
            'SELECT term FROM quarterly_financials WHERE ticker=? ORDER BY term',
            (ticker,)
        )
        terms = [r[0] for r in cur.fetchall()]

        updates = []
        skipped = []
        for term in terms:
            end_date = term_to_end_date(term, fy_end)
            shares   = lookup_shares(sf, end_date)
            if shares is None:
                skipped.append(term)
            else:
                updates.append((shares, ticker, term))

        if skipped:
            print(f'  yfinance 범위 밖 (값 없음): {skipped}')

        conn.executemany(
            """UPDATE quarterly_financials
               SET shares_diluted = COALESCE(shares_diluted, ?)
               WHERE ticker=? AND term=?""",
            updates
        )
        conn.commit()
        print(f'  업데이트: {len(updates)}개 분기 (기존 NULL만 채움)')

    # 결과 확인
    print('\n=== 결과 ===')
    for ticker in targets:
        cur.execute(
            '''SELECT COUNT(*), SUM(CASE WHEN shares_diluted IS NULL THEN 1 ELSE 0 END)
               FROM quarterly_financials WHERE ticker=?''',
            (ticker,)
        )
        total, nulls = cur.fetchone()
        print(f'  {ticker}: 총 {total}분기, NULL {nulls}개')

    conn.close()


if __name__ == '__main__':
    main()
