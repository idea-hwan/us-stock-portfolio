"""
SEC EDGAR 1차 출처 조회 도구 (주간 신호 리포트 검증용)

  python scripts/edgar_lookup.py filings TICKER [--since 2026-09-29] [--forms 8-K,4,10-Q]
      최근 공시 목록 (날짜·양식·접수번호·본문 URL)
  python scripts/edgar_lookup.py form4 TICKER [--since 2026-09-01] [--code P,S]
      Form 4 거래 집계 (제출자별·구간별 주식수·금액·평균가, 보유주식수)
  python scripts/edgar_lookup.py grep URL PATTERN [--context 200]
      공시 본문(HTML)에서 정규식 PATTERN 주변 텍스트 출력

수치는 전부 SEC 원문 기준이다. 뉴스·2차 출처와 충돌하면 이 결과를 우선한다.
"""

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests

from config import sec_headers, sec_get

HEADERS = sec_headers()
ARCHIVES = 'https://www.sec.gov/Archives/edgar/data'


def get(url: str) -> requests.Response:
    time.sleep(0.15)  # SEC 초당 10건 제한 여유
    return sec_get(url, HEADERS)


def ticker_to_cik(ticker: str) -> int:
    data = get('https://www.sec.gov/files/company_tickers.json').json()
    for v in data.values():
        if v['ticker'].upper() == ticker.upper().replace('.', '-'):
            return int(v['cik_str'])
    sys.exit(f'CIK를 찾지 못함: {ticker}')


def recent_filings(cik: int, since: str = '', forms: set = None) -> list:
    r = get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json').json()['filings']['recent']
    rows = []
    for form, dt, acc, doc in zip(r['form'], r['filingDate'], r['accessionNumber'], r['primaryDocument']):
        if dt < since or (forms and form not in forms):
            continue
        # xsl 접두 경로는 렌더링된 HTML이라 원본 XML 경로로 바꾼다
        doc = re.sub(r'^xsl[^/]+/', '', doc)
        rows.append({'date': dt, 'form': form, 'acc': acc,
                     'url': f"{ARCHIVES}/{cik}/{acc.replace('-', '')}/{doc}"})
    return rows


def cmd_filings(a):
    cik = ticker_to_cik(a.ticker)
    forms = set(a.forms.split(',')) if a.forms else None
    for f in recent_filings(cik, a.since, forms):
        print(f"{f['date']}  {f['form']:<8} {f['acc']}  {f['url']}")


def parse_form4(url: str) -> dict:
    root = ET.fromstring(get(url).text)
    owners = ', '.join(e.text for e in root.iter('rptOwnerName'))
    txs = []
    for tx in root.iter('nonDerivativeTransaction'):
        g = lambda p: tx.findtext(p)
        shares = g('transactionAmounts/transactionShares/value')
        price = g('transactionAmounts/transactionPricePerShare/value')
        txs.append({
            'date': g('transactionDate/value'),
            'code': g('transactionCoding/transactionCode'),
            'ad': g('transactionAmounts/transactionAcquiredDisposedCode/value'),
            'shares': float(shares or 0),
            'price': float(price or 0),
            'security': g('securityTitle/value'),
            'after': float(g('postTransactionAmounts/sharesOwnedFollowingTransaction/value') or 0),
        })
    return {'owners': owners, 'txs': txs}


def cmd_form4(a):
    cik = ticker_to_cik(a.ticker)
    codes = set(a.code.split(','))
    filings = recent_filings(cik, a.since, {'4', '4/A'})
    if not filings:
        print('해당 기간 Form 4 없음')
        return
    total = defaultdict(lambda: [0.0, 0.0])
    last_after = {}
    for f in sorted(filings, key=lambda x: x['date']):
        try:
            p = parse_form4(f['url'])
        except ET.ParseError:
            print(f"{f['date']} {f['acc']}: XML 파싱 실패 → {f['url']}")
            continue
        agg = defaultdict(lambda: [0.0, 0.0])
        dates = []
        for t in p['txs']:
            if t['code'] not in codes:
                continue
            sign = 1 if t['ad'] == 'A' else -1
            key = (t['code'], t['security'])
            agg[key][0] += sign * t['shares']
            agg[key][1] += sign * t['shares'] * t['price']
            dates.append(t['date'])
            last_after[(p['owners'], t['security'])] = (t['date'], t['after'])
        if not agg:
            continue
        print(f"[제출 {f['date']}] {p['owners']}  거래일 {min(dates)}~{max(dates)}  ({f['acc']})")
        for (code, sec), (sh, usd) in agg.items():
            avg = usd / sh if sh else 0
            print(f"    {code} {sec}: {sh:,.0f}주  {usd:,.0f}달러  평균 {avg:,.2f}")
            total[(code, sec)][0] += sh
            total[(code, sec)][1] += usd
    print('\n합계')
    for (code, sec), (sh, usd) in total.items():
        print(f"    {code} {sec}: {sh:,.0f}주  {usd:,.0f}달러  평균 {usd / sh if sh else 0:,.2f}")
    print('최근 보유주식수(거래 후)')
    for (own, sec), (d, after) in last_after.items():
        print(f"    {own} | {sec}: {after:,.0f}주 (거래일 {d})")


def cmd_grep(a):
    html = get(a.url).text
    text = re.sub(r'<(script|style).*?</\1>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;|&#160;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    hits = list(re.finditer(a.pattern, text, flags=re.I))
    print(f'{len(hits)}건 일치')
    for m in hits[:a.max]:
        s, e = max(0, m.start() - a.context), min(len(text), m.end() + a.context)
        print('…' + text[s:e] + '…\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('filings')
    p.add_argument('ticker')
    p.add_argument('--since', default='')
    p.add_argument('--forms', default='')
    p.set_defaults(fn=cmd_filings)

    p = sub.add_parser('form4')
    p.add_argument('ticker')
    p.add_argument('--since', default='')
    p.add_argument('--code', default='P,S', help='거래코드 (P=장내매수, S=장내매도 등)')
    p.set_defaults(fn=cmd_form4)

    p = sub.add_parser('grep')
    p.add_argument('url')
    p.add_argument('pattern')
    p.add_argument('--context', type=int, default=200)
    p.add_argument('--max', type=int, default=8)
    p.set_defaults(fn=cmd_grep)

    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
