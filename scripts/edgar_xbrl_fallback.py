"""
companyfacts 누락 보충 — 10-Q/10-K 원본 XBRL 인스턴스에서 직접 읽기

SEC companyfacts API는 종목별로 갱신이 수주~수개월 멈추는 경우가 있다
(2026-10 기준 12월 결산 60종목이 7월 말 2분기 10-Q를 못 받음, AEP 사례 등).
이때 submissions API에는 제출 목록이 있으므로, companyfacts에 없는 최신 10-Q/10-K를
찾아 해당 제출물의 인스턴스 문서(<이름>_htm.xml)를 파싱하고, companyfacts 행과
같은 모양의 레코드로 facts에 병합한다. 이후 처리(YTD 차감 등)는 기존 로직이 그대로 한다.

- 현재 보고 기간(DocumentPeriodEndDate)과 끝나는 값만, 차원(segment) 없는 값만 사용
- 이전 연도 비교 값은 이미 DB에 있으므로 쓰지 않는다
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import requests

ARCHIVES = 'https://www.sec.gov/Archives/edgar/data'
LINKBASE = re.compile(r'_(cal|def|lab|pre)\.xml$|FilingSummary\.xml$', re.I)


def _get(url: str, headers: dict) -> requests.Response:
    from config import sec_get
    time.sleep(0.12)
    return sec_get(url, headers, timeout=60)


def _known_accessions(facts: dict) -> tuple[set, str]:
    """companyfacts에 이미 들어 있는 접수번호 집합과 가장 최근 제출일."""
    known, latest = set(), ''
    for entry in facts.get('facts', {}).get('us-gaap', {}).values():
        for rows in entry.get('units', {}).values():
            for r in rows:
                known.add(r.get('accn'))
                if r.get('form') in ('10-Q', '10-K'):
                    latest = max(latest, r.get('filed', ''))
    return known, latest


def _find_instance(cik: int, acc: str, headers: dict) -> str | None:
    base = f"{ARCHIVES}/{cik}/{acc.replace('-', '')}/"
    names = re.findall(r'href="/Archives/[^"]+/([^"/]+\.xml)"', _get(base, headers).text)
    cands = [n for n in names if not LINKBASE.search(n)]
    cands.sort(key=lambda n: (not n.endswith('_htm.xml'), n))  # 인라인 XBRL 추출본 우선
    return base + cands[0] if cands else None


def _local(tag: str) -> tuple[str, str]:
    ns, _, name = tag[1:].partition('}') if tag.startswith('{') else ('', '', tag)
    return ns, name


def parse_instance(xml_text: str, wanted: dict, any_ns: bool = False) -> dict:
    """wanted: {태그: 단위('USD'|'shares')}. 반환: {'fp','end','records':[(tag,unit,start,end,val)]}
    any_ns=True면 us-gaap이 아닌 회사 고유(extension) 네임스페이스의 같은 이름 요소도 읽는다."""
    root = ET.fromstring(xml_text)
    contexts, units, dei = {}, {}, {}
    for el in root:
        ns, name = _local(el.tag)
        if name == 'context':
            has_dim = any(_local(c.tag)[1] in ('segment', 'scenario') for c in el.iter())
            p = {_local(c.tag)[1]: (c.text or '').strip() for c in el.iter()
                 if _local(c.tag)[1] in ('startDate', 'endDate', 'instant')}
            contexts[el.get('id')] = (has_dim, p)
        elif name == 'unit':
            m = [(c.text or '') for c in el.iter() if _local(c.tag)[1] == 'measure']
            units[el.get('id')] = m[0] if len(m) == 1 else None
        elif ns.startswith('http://xbrl.sec.gov/dei/'):
            dei[name] = (el.text or '').strip()

    period_end = dei.get('DocumentPeriodEndDate', '')
    if not period_end:
        return {}
    try:
        period_end = date.fromisoformat(period_end).isoformat()
    except ValueError:  # 'June 30, 2026' 형식
        from datetime import datetime
        period_end = datetime.strptime(period_end, '%B %d, %Y').date().isoformat()

    recs = []
    for el in root:
        ns, name = _local(el.tag)
        if name not in wanted or not (any_ns or ns.startswith('http://fasb.org/us-gaap/')):
            continue
        cref = el.get('contextRef')
        has_dim, p = contexts.get(cref, (True, {}))
        if has_dim or not el.text or not el.text.strip():
            continue
        end = p.get('endDate') or p.get('instant')
        if end != period_end:
            continue
        measure = units.get(el.get('unitRef')) or ''
        unit = 'USD' if measure.endswith('USD') else ('shares' if measure.endswith('shares') else None)
        if unit != wanted[name]:
            continue
        try:
            val = float(el.text.strip())
        except ValueError:
            continue
        recs.append((name, unit, p.get('startDate'), end, val))
    return {'fp': dei.get('DocumentFiscalPeriodFocus', ''), 'end': period_end, 'records': recs}


def patch_missing_filings(facts: dict, submissions: dict, cik: int, targets: list,
                          headers: dict, lookback_days: int = 1200, max_filings: int = 8) -> list[str]:
    """companyfacts에 없는 최근 10-Q/10-K를 인스턴스에서 읽어 facts에 병합. 반영한 접수번호 목록 반환.

    companyfacts에 이미 들어 있는 접수번호가 아니면 모두 대상이다 — 가장 최근 제출일 '이후'만 보던 이전 로직은
    중간 공시가 빠진 구멍(TAP 2026Q1, CAH 2026Q3: 뒤쪽 공시는 있는데 4/30 10-Q만 없음)을 못 메웠다.
    요청 폭주를 막으려고 최근 순으로 max_filings건까지만 처리한다."""
    wanted = {tag: unit for _, tags, unit in targets for tag in tags}
    known, latest = _known_accessions(facts)
    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    r = submissions.get('filings', {}).get('recent', {})
    missing = [(d, f, a) for f, d, a in zip(r.get('form', []), r.get('filingDate', []),
                                            r.get('accessionNumber', []))
               if f in ('10-Q', '10-K') and a not in known and d >= cutoff]
    missing = sorted(missing, reverse=True)[:max_filings]       # 최근 max_filings건
    patched = []
    usgaap = facts.setdefault('facts', {}).setdefault('us-gaap', {})
    for filed, form, acc in sorted(missing):
        url = _find_instance(cik, acc, headers)
        if not url:
            continue
        parsed = parse_instance(_get(url, headers).text, wanted)
        fp = 'FY' if form == '10-K' else parsed.get('fp', '')
        if not parsed or not parsed['records'] or fp not in ('Q1', 'Q2', 'Q3', 'FY'):
            continue
        for tag, unit, start, end, val in parsed['records']:
            row = {'end': end, 'val': val, 'accn': acc, 'fp': fp, 'form': form, 'filed': filed,
                   'fy': int(end[:4])}
            if start:
                row['start'] = start
            usgaap.setdefault(tag, {'units': {}})['units'].setdefault(unit, []).append(row)
        patched.append(acc)
    return patched
