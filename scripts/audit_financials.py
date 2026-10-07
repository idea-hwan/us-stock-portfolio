"""
재무 DB(stocks.db) 감사 — 읽기 전용, DB 수정 없음

  python scripts/audit_financials.py [--from 2013] [--skip-external]

A. 구조: (ticker, term) 중복, 분기 공백, 열별 결측률, 미래 분기
B. 이상치: 정확히 0인 값(수집 구멍 의심), 분기 간 급변, 부호 이상
C. 독립 출처(SEC frames API) 대조
   - 분기: 매출·영업이익·순이익 Q1~Q3 (12월 결산 외 종목도 기간 종료월로 매칭)
   - 연간: 12월 결산 종목의 4분기 합계 vs 연간값 (Q4 파생 로직 + CFO·CAPEX 검증)

일치 기준: 값 차이가 max(100만 달러, 0.5%) 이하. 단 매출은 '일치'여도 후보 태그 최대값의 90% 미만이면
*_low_rev 로 따로 기록한다(하위 항목 태그를 총매출로 잘못 고른 경우 탐지). 매출·CAPEX처럼 태그가 여러 개인 항목은
후보 태그 중 하나라도 맞으면 일치로 본다(관대한 기준 — 불일치는 더 강한 증거).
불일치 목록은 data/analytics/audit_financials_mismatch.json 에 저장한다.
"""

import argparse
import calendar
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import sec_headers, sec_get

ROOT = Path(__file__).parent.parent
DB = ROOT / 'data' / 'stocks.db'
OUT = ROOT / 'data' / 'analytics' / 'audit_financials_mismatch.json'
HEADERS = sec_headers()

COLS = ['revenue', 'operating_income', 'net_income', 'cfo', 'capex']
REV_TAGS = ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
            'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet',
            'SalesRevenueGoodsNet', 'RegulatedAndUnregulatedOperatingRevenue',
            'OilAndGasRevenue', 'NetRevenues']
OP_TAGS = ['OperatingIncomeLoss']
NI_TAGS = ['NetIncomeLoss', 'ProfitLoss']
CFO_TAGS = ['NetCashProvidedByUsedInOperatingActivities',
            'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations']
CAPEX_TAGS = ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets',
              'PaymentsToAcquireOtherPropertyPlantAndEquipment']
TAGS = {'revenue': REV_TAGS, 'operating_income': OP_TAGS, 'net_income': NI_TAGS,
        'cfo': CFO_TAGS, 'capex': CAPEX_TAGS}


def get(url):
    time.sleep(0.12)
    try:
        return sec_get(url, HEADERS, timeout=60).json()
    except requests.HTTPError as e:
        if "404" in str(e):
            return None
        raise


def term_key(term):
    return int(term[:4]) * 4 + int(term[5]) - 1


def load(con, since):
    rows = con.execute("select ticker, term, fiscal_year_end_month, revenue, operating_income, "
                       "net_income, cfo, capex from quarterly_financials").fetchall()
    data = defaultdict(dict)
    fy = {}
    for t, term, m, *vals in rows:
        fy[t] = m
        data[t][term] = dict(zip(COLS, vals))
    return data, fy, len(rows)


# ── A. 구조 ───────────────────────────────────────────────────────────

def audit_structure(con, data, since):
    print('\n[A] 구조 점검')
    dup = con.execute("select count(*) from (select ticker, term from quarterly_financials "
                      "group by 1,2 having count(*)>1)").fetchone()[0]
    print(f'  (ticker, term) 중복: {dup}')
    gaps = []
    for t, terms in data.items():
        ks = sorted(term_key(x) for x in terms if int(x[:4]) >= since)
        if len(ks) > 1:
            missing = set(range(ks[0], ks[-1] + 1)) - set(ks)
            if missing:
                gaps.append((t, len(missing)))
    print(f'  분기 공백(중간 분기 누락)이 있는 종목: {len(gaps)}종목 / 공백 합계 {sum(g for _, g in gaps)}분기')
    if gaps:
        print('    상위:', sorted(gaps, key=lambda x: -x[1])[:10])
    cur_year = date.today().year
    future = [(t, x) for t, terms in data.items() for x in terms if int(x[:4]) > cur_year + 1]
    print(f'  미래 분기(이상): {len(future)}건')
    print('  열별 결측률(분석 구간):')
    for c in COLS:
        tot = nul = 0
        for t, terms in data.items():
            for x, v in terms.items():
                if int(x[:4]) >= since:
                    tot += 1
                    nul += v[c] is None
        print(f'    {c:<17} {nul:>6,}/{tot:,} ({nul / tot:.1%})')
    return gaps


# ── B. 이상치 ─────────────────────────────────────────────────────────

def audit_anomalies(data, since):
    print('\n[B] 이상치 점검')
    zeros = Counter()
    zero_ex = defaultdict(list)
    neg_rev = []
    jumps = []
    opgt = []
    for t, terms in data.items():
        ks = sorted(terms)
        prev = None
        for x in ks:
            if int(x[:4]) < since:
                continue
            v = terms[x]
            for c in ('revenue', 'operating_income', 'net_income'):
                if v[c] == 0:
                    zeros[c] += 1
                    if len(zero_ex[c]) < 6:
                        zero_ex[c].append((t, x))
            if v['revenue'] is not None and v['revenue'] < 0:
                neg_rev.append((t, x))
            if (v['revenue'] and v['operating_income'] is not None
                    and v['operating_income'] > v['revenue'] * 1.0 and v['revenue'] > 0):
                opgt.append((t, x))
            if prev and v['revenue'] and prev['revenue'] and prev['revenue'] > 0:
                r = v['revenue'] / prev['revenue']
                if r > 5 or r < 0.2:
                    jumps.append((t, x, round(r, 2)))
            prev = v
    for c in ('revenue', 'operating_income', 'net_income'):
        print(f'  {c} == 0 인 분기: {zeros[c]}건  예: {zero_ex[c]}')
    print(f'  매출 음수: {len(neg_rev)}건 {neg_rev[:5]}')
    print(f'  영업이익 > 매출(비정상): {len(opgt)}건 {opgt[:5]}')
    print(f'  매출 전분기 대비 5배 초과/0.2배 미만: {len(jumps)}건 {jumps[:6]}')
    return {'zeros': dict(zeros), 'jumps': jumps, 'opgt': opgt}


# ── C. 독립 출처 대조 ──────────────────────────────────────────────────

def cy_period_end(fy_month, year, q):
    """회계연도 year의 q분기 종료 (연, 월). 회계연도는 year년 fy_month월에 끝난다."""
    m = fy_month - (4 - q) * 3
    y = year
    while m <= 0:
        m += 12
        y -= 1
    return y, m


def frame(tag, period):
    d = get(f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json')
    return d['data'] if d else []


def audit_external(data, fy, since):
    print('\n[C] 독립 출처(SEC frames) 대조')
    cik_map = {int(v['cik_str']): v['ticker'].upper()
               for v in get('https://www.sec.gov/files/company_tickers.json').values()}
    mism = []

    # C-1 분기 (Q1~Q3): 기간 종료 (연,월) 로 매칭
    stat = {c: [0, 0] for c in ('revenue', 'operating_income', 'net_income')}
    end_year = date.today().year
    for y in range(since, end_year + 1):
        for q in (1, 2, 3):
            # 이 달력분기에 끝나는 기간을 가진 종목 → 회계분기로 역산해 DB 값과 비교
            per = f'CY{y}Q{q}'
            for col in stat:
                vals = defaultdict(list)  # (ticker, end 날짜) -> [후보값]
                for tag in TAGS[col]:
                    for x in frame(tag, per):
                        t = cik_map.get(x['cik'])
                        if t in data:
                            vals[(t, x['end'])].append(x['val'])
                for (t, end_s), cands in vals.items():
                    m = fy.get(t, 12)
                    e = date.fromisoformat(end_s)
                    # DB 쪽 term 찾기: 회계분기 종료월의 말일과 ±7일 이내인 것 (52/53주 회계 대응)
                    hit = None
                    for fyr in (e.year, e.year + 1):
                        for qq in (1, 2, 3):
                            py, pm = cy_period_end(m, fyr, qq)
                            month_end = date(py, pm, calendar.monthrange(py, pm)[1])
                            if abs((e - month_end).days) <= 7:
                                hit = (fyr, qq)
                    if not hit:
                        continue
                    term = f'{hit[0]}Q{hit[1]}'
                    v = data[t].get(term, {}).get(col)
                    if v is None:
                        continue
                    stat[col][0] += 1
                    if any(abs(v - c) <= max(1e6, abs(c) * 0.005) for c in cands):
                        stat[col][1] += 1
                        if col == 'revenue' and v < 0.9 * max(cands):
                            mism.append({'kind': 'quarter_low_rev', 'ticker': t, 'term': term,
                                         'col': col, 'db': v, 'sec': cands})
                    else:
                        mism.append({'kind': 'quarter', 'ticker': t, 'term': term, 'col': col,
                                     'db': v, 'sec': cands})
    for col, (n, ok) in stat.items():
        print(f'  분기 {col:<17} 비교 {n:>6,}건 | 일치 {ok:>6,} ({ok / n:.1%})' if n else f'  {col}: 비교 불가')

    # C-2 연간: 12월 결산 종목의 4분기 합계 vs 연간값
    astat = {c: [0, 0] for c in COLS}
    for y in range(since, end_year):
        for col in COLS:
            vals = defaultdict(list)
            for tag in TAGS[col]:
                for x in frame(tag, f'CY{y}'):
                    t = cik_map.get(x['cik'])
                    if t in data and fy.get(t) == 12:
                        vals[t].append(x['val'])
            for t, cands in vals.items():
                qs = [data[t].get(f'{y}Q{q}', {}).get(col) for q in (1, 2, 3, 4)]
                if any(v is None for v in qs):
                    continue
                s = sum(qs)
                astat[col][0] += 1
                if any(abs(s - c) <= max(1e6, abs(c) * 0.005) for c in cands):
                    astat[col][1] += 1
                    if col == 'revenue' and s < 0.9 * max(cands):
                        mism.append({'kind': 'annual_low_rev', 'ticker': t, 'term': f'{y}FY',
                                     'col': col, 'db': s, 'sec': cands})
                else:
                    mism.append({'kind': 'annual', 'ticker': t, 'term': f'{y}FY', 'col': col,
                                 'db': s, 'sec': cands})
    for col, (n, ok) in astat.items():
        print(f'  연간합계 {col:<17} 비교 {n:>6,}건 | 일치 {ok:>6,} ({ok / n:.1%})' if n else f'  {col}: 비교 불가')
    return mism


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='since', type=int, default=2013)
    ap.add_argument('--skip-external', action='store_true')
    a = ap.parse_args()

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    data, fy, n = load(con, a.since)
    print(f'DB: {len(data)}종목, {n:,}행 (분석 구간 {a.since}~)')
    audit_structure(con, data, a.since)
    anomalies = audit_anomalies(data, a.since)
    mism = [] if a.skip_external else audit_external(data, fy, a.since)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({'mismatch': mism, 'anomalies': anomalies}, default=str))
    print(f'\n불일치 {len(mism):,}건 → {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
