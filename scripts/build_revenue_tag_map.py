"""
종목별 '손익계산서 맨 윗줄' 매출 태그 매핑 생성 (SEC 읽기 전용 → data/revenue_tag_map.json)

  python scripts/build_revenue_tag_map.py [--ticker X ...]

왜 필요한가: 매출 태그 후보가 여러 개(RevenueFromContractWithCustomer…, Revenues, SalesRevenueNet …)라
"먼저 값이 있는 태그"를 쓰면 일부 종목(URI·ADM·BG·GM·VST 등)에서 총매출이 아닌 하위 항목이 잡힌다.
반대로 "큰 값 우선"은 RSG(내부거래 제거 전 총액)·PM(소비세 포함)·HAS에서 틀린다.
→ 기업이 가장 최근 10-Q 손익계산서에서 실제로 쓴 최상단 매출 행의 XBRL 태그를 정답으로 삼는다.

선택 규칙(최상단 ~ 첫 비용 행 사이의 매출성 행 중, 비매출 태그 행은 건너뛰고 계속 읽음):
  1) 행이 하나면 그 행
  2) 여럿이면 라벨이 total / net revenue(s) / net sales 로 시작하는 마지막 행 (예: PM 'Net revenues',
     CNC 'Total revenues', GM 'Total net sales and revenue')
  3) 그래도 없으면 값이 가장 큰 행

회계 기준 변경(2018 ASC 606 등)으로 시대마다 최상단 태그가 다르므로 2014·2017·2020·2023년과 최신 10-Q를
샘플링해 {제출연도: 태그}로 저장한다(종목당 최대 5개). collect_financials.py 는 각 분기에 대해
'그 연도 이후 첫 샘플'의 태그를 1순위로 쓰고, 그 기간에 값이 없으면 기본 우선순위로 넘어간다.
"""

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from config import sec_headers, sec_get

ROOT = Path(__file__).parent.parent
OUT = ROOT / 'data' / 'revenue_tag_map.json'
HEADERS = sec_headers()
STMT = re.compile(r'statements?\s+of\s+(consolidated\s+|condensed\s+)*(operations|income|earnings)'
                  r'|income\s+statements?|results\s+of\s+operations', re.I)
# 손익계산서가 포괄손익계산서 한 페이지에 합쳐진 회사(ISRG 등) — 일반 후보가 없을 때만 보조로 시도
STMT_FALLBACK = re.compile(r'statements?\s+of\s+(consolidated\s+|condensed\s+)*comprehensive\s+(income|loss|earnings)', re.I)
BAD = re.compile(r'(parenthetical|cash|equity|stockholders|tax|segment|per share|details|schedule)', re.I)
# 매출 태그 판정: 이름이 Revenue/Sales 로 시작하거나 Revenue(s) 로 끝나는 것만 (AvailableForSaleSecurities 같은
# 'Sales' 부분 문자열 오탐 방지). 포괄손익·비용 태그는 제외.
REV_TAG = re.compile(r'^(?!OtherComprehensive)(Revenue|Sales|NetRevenue|\w*OperatingRevenue|\w*Revenues?$)')
COST_TAG = re.compile(r'(Cost|Expense)', re.I)
TOTAL_LABEL = re.compile(r'^(total|net revenues?|net sales|revenues?, net|net revenue)', re.I)
DEFREF = re.compile(r"defref_([A-Za-z\-]+)_([A-Za-z0-9]+)")


def get(url):
    time.sleep(0.13)
    return sec_get(url, HEADERS, timeout=60)


def num(s):
    s = s.replace('$', '').replace(',', '').replace('\xa0', '').strip()
    if not re.match(r'^\(?-?\d+(\.\d+)?\)?$', s):
        return None
    v = float(s.strip('()'))
    return -v if s.startswith('(') else v


def top_line(base):
    """FilingSummary → 손익계산서 R 페이지 → 최상단 매출 행 (태그, 값(원 단위), 라벨). 못 찾으면 None."""
    fs = ET.fromstring(get(base + 'FilingSummary.xml').text)
    pages = [(r.findtext('ShortName') or '', r.findtext('HtmlFileName') or '') for r in fs.iter('Report')]
    cand = [h for n, h in pages if STMT.search(n) and not BAD.search(n) and h]
    cand += [h for n, h in pages if STMT_FALLBACK.search(n) and not STMT.search(n) and not BAD.search(n) and h]
    for h in cand[:3]:
        html_text = get(base + h).text
        soup = BeautifulSoup(html_text, 'lxml')
        rows = []
        for tr in soup.find_all('tr'):
            cells = tr.find_all(['th', 'td'])
            if len(cells) < 2:
                continue
            m = DEFREF.search(str(cells[0]))
            val = num(cells[1].get_text(' ', strip=True))
            if not m or val is None:
                continue
            ns, tag = m.groups()
            if ns != 'us-gaap':
                continue
            if COST_TAG.search(tag):
                break                                   # 첫 비용 행 → 매출 구간 끝 (CostOfRevenue 등 포함)
            if REV_TAG.search(tag):
                rows.append((cells[0].get_text(' ', strip=True), tag, val))
            # 매출 태그가 아닌 행(예: HUM의 Premiums·Investment income)을 만나도 끊지 않고 첫 비용 행까지 계속 읽는다 —
            # 끊으면 그 뒤의 'Total revenues' 행에 도달하지 못해 하위 항목(Services 1,264)이 선택된다.
        if rows:
            pick = rows[0] if len(rows) == 1 else None
            if pick is None:
                totals = [r for r in rows if TOTAL_LABEL.search(r[0])]
                pick = totals[-1] if totals else max(rows, key=lambda r: abs(r[2]))
            low = html_text.lower()
            scale = 1e6 if 'in millions' in low else (1e3 if 'in thousands' in low else 1)
            return pick[1], pick[2] * scale, pick[0]
    return None


def top_line_tag(base):
    r = top_line(base)
    return r[0] if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', action='append')
    a = ap.parse_args()
    import pandas as pd
    tickers = a.ticker or pd.read_csv(ROOT / 'data' / 'stock_universe.csv')['ticker'].tolist()
    cik = {v['ticker'].upper(): str(v['cik_str']).zfill(10)
           for v in get('https://www.sec.gov/files/company_tickers.json').json().values()}
    cik.update({'SATS': '0001415404', 'AEP': '0000004904'})
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    res, fail = dict(old), []
    sample_years = (2014, 2017, 2020, 2023)
    for i, t in enumerate(tickers, 1):
        c = cik.get(t.upper())
        if not c:
            fail.append((t, 'CIK 없음'))
            continue
        try:
            facts = get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{c}.json').json()['facts']['us-gaap']
            filings = {}                                   # accn -> filed (10-Q만)
            for tag in ('OperatingIncomeLoss', 'NetIncomeLoss', 'Revenues',
                        'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet'):
                for r in facts.get(tag, {}).get('units', {}).get('USD', []):
                    if r.get('form') == '10-Q':
                        filings[r['accn']] = r['filed']
            if not filings:
                fail.append((t, '10-Q 없음'))
                continue
            picks = [max(filings.items(), key=lambda kv: kv[1])[0]]           # 최신
            for y in sample_years:
                cand = sorted((f, a) for a, f in filings.items() if f.startswith(str(y)))
                if cand:
                    picks.append(cand[0][1])                                    # 그 해 첫 10-Q
            tags = {}
            for acc in sorted(picks, key=lambda a: filings[a]):
                tag = top_line_tag(f"https://www.sec.gov/Archives/edgar/data/{int(c)}/{acc.replace('-', '')}/")
                if tag:
                    tags[filings[acc][:4]] = tag          # 제출연도 → 최상단 매출 태그
            if tags:
                res[t.upper()] = tags
            else:
                fail.append((t, '손익계산서 매출 행 못 찾음'))
        except Exception as e:
            fail.append((t, str(e)[:60]))
        if i % 25 == 0:
            print(f'진행 {i}/{len(tickers)}', flush=True)
    OUT.write_text(json.dumps(dict(sorted(res.items())), indent=0, ensure_ascii=False))
    print(f'저장 {len(res)}종목 → {OUT.relative_to(ROOT)} | 실패 {len(fail)}')
    for t, why in fail[:40]:
        print('  실패', t, why)


if __name__ == '__main__':
    main()
