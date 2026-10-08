"""
신호 종목 원본 자동 대조 (읽기 전용): 대시보드의 매수·매도 신호 종목마다 DB의 최근 분기 값을
가장 최근 10-Q/10-K 원본 XBRL 인스턴스와 맞춰 본다. 주간 리포트 작성 전에 돌린다.

  python scripts/verify_signal_tickers.py                # 현재 신호 종목 전부
  python scripts/verify_signal_tickers.py LEN VEEV       # 지정 종목

보는 것:
  1. DB 위생 — 최근 8분기에 빈 값(매출·영업이익·순이익·CFO·CAPEX), 음수 capex, 분기 공백, 최신 분기가 SEC 최신 제출과 같은 기간인지.
  2. 원본 대조 — 최신 제출의 3개월 값(10-Q)과 누계 값(10-Q 누계·10-K 연간)을 DB 분기 값과 비교.
     누계는 DB의 같은 회계연도 분기 합이다. 표준 태그 후보 중 하나라도 맞으면 일치로 본다.
     원본에 표준 태그가 하나도 없으면 "extension 가능"(수집이 못 읽는 종목), 태그는 있는데 안 맞으면 "불일치".

2026-10-08 VEEV(capex 결측을 옛 값이 메움)·LEN(순액 capex 음수를 가드가 지움) 사건처럼, 신호에 걸린 종목의 숫자가 틀린 채
리포트에 올라가는 것을 막으려는 도구다. 결과가 ⚠인 종목은 리포트에서 판정을 보류하고 원인을 먼저 확인한다.
"""

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import collect_financials as cf
import edgar_xbrl_fallback as fb
from config import sec_get, sec_headers

ROOT = Path(__file__).parent.parent
DB = ROOT / 'data' / 'stocks.db'
HEADERS = sec_headers()
METRICS = ['revenue', 'operating_income', 'net_income', 'cfo', 'capex']
CIK_OVERRIDES = {'SATS': '0001415404', 'AEP': '0000004904', 'PSKY': '0002041610'}
HYGIENE_QUARTERS = 8


def signal_tickers() -> dict[str, str]:
    html = (ROOT / 'docs' / 'index.html').read_text()
    stocks = json.JSONDecoder().raw_decode(html[html.index('const STOCKS = ') + len('const STOCKS = '):])[0]
    out = {}
    for s in stocks:
        if s.get('signal') not in (None, '', '—'):
            out[s['ticker']] = '매수'
        if s.get('sell_sig') not in (None, '', '—'):
            out[s['ticker']] = out.get(s['ticker'], '') + '매도'
    return out


def term_of(end: str, fy_month: int) -> tuple[str, int, int]:
    """결산 기준 분기 라벨 — collect_financials와 같은 규칙(끝나는 날 −10일 보정, 52/53주 대응)."""
    adj = date.fromisoformat(end) - timedelta(days=10)
    year = adj.year + 1 if adj.month > fy_month else adj.year
    q = ((adj.month - fy_month - 1) % 12) // 3 + 1
    return f'{year}Q{q}', year, q


def term_key(t: str) -> int:
    return int(t[:4]) * 4 + int(t[5]) - 1


def tag_candidates(metric: str) -> list[str]:
    tags = next(t for name, t, _ in cf.TARGETS if name == metric)
    if metric == 'revenue':
        tags = list(tags) + sorted(set(cf.REV_TAG_WHITELIST) - set(tags))
    return list(tags)


def hygiene(ticker: str, rows: pd.DataFrame, latest_term: str | None) -> list[str]:
    issues = []
    last = rows.sort_values('term').tail(HYGIENE_QUARTERS)
    for m in METRICS:
        blank = last[last[m].isna()]['term'].tolist()
        if blank:
            issues.append(f'{m} 빈 분기 {",".join(blank)}')
    neg = last[last['capex'] < 0]['term'].tolist()
    if neg and ticker not in cf.NET_CAPEX_TICKERS:
        issues.append(f'capex 음수 {",".join(neg)}(순액 공시면 정상 — NET_CAPEX_TICKERS 확인)')
    keys = sorted(term_key(t) for t in last['term'])
    if keys and (keys[-1] - keys[0] + 1) != len(keys):
        issues.append('최근 분기에 공백')
    if latest_term and rows['term'].max() != latest_term:
        issues.append(f'DB 최신 분기 {rows["term"].max()} ≠ SEC 최신 제출 {latest_term}')
    return issues


def compare(ticker: str, rows: pd.DataFrame, cik: str, fy_month: int) -> tuple[list[str], list[str], str | None]:
    sub = sec_get(f'https://data.sec.gov/submissions/CIK{cik}.json', HEADERS, 60).json()
    r = sub['filings']['recent']
    cands = sorted([(d, a, f) for f, d, a in zip(r['form'], r['filingDate'], r['accessionNumber'])
                    if f in ('10-Q', '10-K')], reverse=True)
    if not cands:
        return ['제출 목록에 10-Q/10-K 없음'], [], None
    filed, acc, form = cands[0]
    url = fb._find_instance(int(cik), acc, HEADERS)
    if not url:
        return [f'{form} {filed} 인스턴스 문서를 못 찾음'], [], None
    wanted = {t: u for _, tags, u in cf.TARGETS for t in tags}
    wanted.update({t: 'USD' for t in cf.REV_TAG_WHITELIST})
    parsed = fb.parse_instance(fb._get(url, HEADERS).text, wanted)
    if not parsed or not parsed.get('records'):
        return [f'{form} {filed} 인스턴스에서 값을 못 읽음'], [], None
    term, year, q = term_of(parsed['end'], fy_month)
    bucket = {}
    for tag, _, start, end, val in parsed['records']:
        if not start:
            continue
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        kind = '3M' if 80 <= days <= 100 else ('YTD' if form == '10-Q' and 100 < days < 300 else
                                               ('FY' if form == '10-K' and 330 <= days <= 380 else None))
        if kind:
            bucket.setdefault((tag, kind), val)
    db = rows.set_index('term')
    problems, notes = [], []
    matched = 0
    checks = []
    if form == '10-K':
        checks.append(('FY', [f'{year}Q{i}' for i in range(1, 5)]))
    else:
        checks.append(('3M', [term]))
        if q > 1:
            checks.append(('YTD', [f'{year}Q{i}' for i in range(1, q + 1)]))
    for metric in METRICS:
        tags = tag_candidates(metric)
        for kind, terms in checks:
            if kind == '3M' and q > 1 and metric in ('cfo', 'capex'):
                continue          # 현금흐름표는 10-Q에 누계만 있다(Q1 제외) — YTD 대조로 갈음
            vals = [db[metric].get(t) if t in db.index else None for t in terms]
            if any(v is None or pd.isna(v) for v in vals):
                missing = [t for t, v in zip(terms, vals) if v is None or pd.isna(v)]
                src = [(t, bucket[(t, kind)]) for t in tags if (t, kind) in bucket]
                problems.append(f'{metric} {kind}: DB 빈 분기 {",".join(missing)}'
                                + (f' (원본 {src[0][0]}={src[0][1] / 1e6:,.1f}백만)' if src else ''))
                continue
            db_val = float(sum(vals))
            present = [(t, bucket[(t, kind)]) for t in tags if (t, kind) in bucket]
            if not present:
                notes.append(f'{metric} {kind}: 원본에 표준 태그 없음 — extension 가능')
                continue
            ok = [t for t, v in present if abs(v - db_val) <= max(1e6, abs(v) * 0.005)]
            if ok:
                matched += 1
                continue
            problems.append(f'{metric} {kind}: DB {db_val / 1e6:,.1f}백만 ≠ 원본 '
                            + ', '.join(f'{t[:28]}={v / 1e6:,.1f}' for t, v in present[:3]))
    notes.insert(0, f'일치 {matched}항목')
    return problems, notes, f'{form} {filed} ({term})'


def main():
    univ = pd.read_csv(ROOT / 'data' / 'stock_universe.csv')
    fy_map = dict(zip(univ['ticker'], univ['fiscal_year_end_month'].fillna(12).astype(int)))
    sig = signal_tickers()
    args = [a.upper() for a in sys.argv[1:]]
    tickers = args or sorted(sig)
    cik = {v['ticker'].upper(): str(v['cik_str']).zfill(10)
           for v in sec_get('https://www.sec.gov/files/company_tickers.json', HEADERS).json().values()}
    cik.update(CIK_OVERRIDES)
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    bad = 0
    for t in tickers:
        rows = pd.read_sql("select * from quarterly_financials where ticker=? order by term", con, params=(t,))
        if rows.empty or t not in cik:
            print(f'⚠ {t:6} DB 또는 CIK 없음')
            bad += 1
            continue
        try:
            problems, notes, label = compare(t, rows, cik[t], fy_map.get(t, 12))
        except Exception as e:                     # 네트워크·파싱 실패는 통과로 보지 않는다
            problems, notes, label = [f'원본 조회 실패: {str(e)[:80]}'], [], None
        latest_term = label[label.index('(') + 1:-1] if label else None
        problems = hygiene(t, rows, latest_term) + problems
        mark = '⚠' if problems else '✓'
        bad += bool(problems)
        print(f'{mark} {t:6} {sig.get(t, ""):4} 대조: {label or "-"}')
        for p in problems:
            print(f'     ⚠ {p}')
        for n in notes:
            print(f'     · {n}')
    print(f'\n점검 {len(tickers)}종목 / ⚠ {bad}종목')


if __name__ == '__main__':
    main()
