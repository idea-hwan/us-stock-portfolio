"""
재무 DB 최신 분기 누락 점검 (읽기 전용 — DB 수정 없음)

  python scripts/check_stale_quarters.py [--term 2026Q2] [--period 2026-06-30]
  (기본값: 제출 기한(분기말 + 50일)이 지난 가장 최근 분기를 자동 계산)

12월 결산 종목 중 stocks.db의 최신 분기가 --term 미만인 종목을 찾아, 각각
  1) EDGAR에 해당 분기 10-Q가 실제로 제출됐는지 (submissions API)
  2) SEC companyfacts API에 그 기간(--period ±7일, 52/53주 회계 대응)의 기간(flow) 데이터가 있는지
를 대조한다. 결과 분류:
  - SEC 원천 지연: 10-Q는 제출됐는데 companyfacts에 데이터 없음 (수집 코드 문제 아님)
  - 수집 누락:     companyfacts엔 데이터가 있는데 DB에 없음 (collect_financials 점검 필요)
  - 미제출:        아직 10-Q 자체가 없음 (정상)
"""

import argparse
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import sec_headers, sec_get

DB = Path(__file__).parent.parent / 'data' / 'stocks.db'
HEADERS = sec_headers()


def shift(d, n):
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def get(url):
    time.sleep(0.15)
    return sec_get(url, HEADERS).json()


def latest_due_quarter(today: date | None = None) -> tuple[str, str]:
    """제출 기한(분기말 + 50일)이 지난 가장 최근 달력 분기 → (term, 분기말 날짜). 12월 결산 기준."""
    today = today or date.today()
    for y in (today.year, today.year - 1):
        for q, (m, d) in reversed(list(enumerate([(3, 31), (6, 30), (9, 30), (12, 31)], 1))):
            end = date(y, m, d)
            if end + timedelta(days=50) <= today:
                return f'{y}Q{q}', end.isoformat()
    raise RuntimeError('기준 분기를 계산하지 못함')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--term', default=None)
    ap.add_argument('--period', default=None)
    a = ap.parse_args()
    if not a.term or not a.period:
        a.term, a.period = latest_due_quarter()
        print(f'기준 분기 자동 계산: {a.term} (분기말 {a.period})')

    con = sqlite3.connect(DB)
    stale = [r for r in con.execute(
        "select ticker, max(term) from quarterly_financials where fiscal_year_end_month=12 "
        "group by ticker having max(term) < ? order by ticker", (a.term,))]
    print(f'12월 결산 중 최신 분기 < {a.term}: {len(stale)}종목')

    cik = {v['ticker']: int(v['cik_str'])
           for v in get('https://www.sec.gov/files/company_tickers.json').values()}
    groups = {'SEC 원천 지연': [], '수집 누락': [], '미제출': []}
    for t, latest in stale:
        c = cik.get(t.replace('.', '-'))
        if c is None:
            print(f'{t}: CIK 없음 — 건너뜀')
            continue
        r = get(f'https://data.sec.gov/submissions/CIK{c:010d}.json')['filings']['recent']
        lo, hi = shift(a.period, -7), shift(a.period, 7)
        filed = next((d for f, d, rd in zip(r['form'], r['filingDate'], r['reportDate'])
                      if f in ('10-Q', '10-K') and lo <= rd <= hi), None)
        facts = get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json')['facts']
        # 손익·현금흐름 같은 '기간(flow)' 데이터만 본다 (시점 데이터는 일부만 반영될 수 있음)
        has = any(lo <= x['end'] <= hi and x.get('start') and 60 <= days(x['start'], x['end']) <= 200
                  for ns in facts.values() for tag in ns.values()
                  for u in tag['units'].values() for x in u)
        key = '미제출' if not filed else ('수집 누락' if has else 'SEC 원천 지연')
        groups[key].append((t, latest, filed))

    for k, rows in groups.items():
        print(f'\n[{k}] {len(rows)}종목')
        for t, latest, filed in rows:
            print(f'  {t:<6} DB최신 {latest}  10-Q제출 {filed or "-"}')


if __name__ == '__main__':
    main()
