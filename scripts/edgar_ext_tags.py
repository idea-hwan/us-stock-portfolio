"""
회사 고유(extension) 태그 보충 — companyfacts API에 없는 태그를 10-Q/10-K 원본 인스턴스에서 읽어 facts에 합친다.

companyfacts는 us-gaap 등 표준 태그만 준다. 일부 종목은 현금흐름표의 설비투자 줄을 회사 고유 태그로 공시해서
(PSX `psx_CapitalExpendituresAndInvestments`, COP, TKO, D, DTE, NEE) CAPEX가 비어 있었고, CAPEX 조건이 필요한
매수·매도 신호가 이 종목들에서는 나올 수 없었다(2026-10-08 `capex_missing` 플래그).

방식: 종목별로 EXT_CAPEX에 적은 태그를 과거 모든 10-Q/10-K 인스턴스에서 읽는다.
  - 대안(alternative)은 순서대로 시도하고, 한 대안 안의 태그들은 합산한다(DTE: 유틸리티+비유틸리티 두 줄).
  - 값은 합성 태그 `EXT_CAPEX`로 us-gaap 항목에 넣어 기존 YTD 차감·분기 계산을 그대로 탄다.
  - 읽은 결과는 data/ext_facts/<티커>.json에 캐시한다(접수번호 단위). 새 공시만 추가로 받는다.
"""

import json
import re
import time
from pathlib import Path

import edgar_xbrl_fallback as fb
from config import sec_get

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / 'data' / 'ext_facts'
SINCE = '2013-06-01'          # 수집 시작 연도(CUTOFF 이전 + 여유)
SYNTH_TAG = 'EXT_CAPEX'

# 티커 → 대안 목록. 각 대안은 합산할 태그 목록. 앞 대안이 있는 공시는 그 대안을 쓴다.
# 현금흐름표 R 페이지의 줄(defref)로 확인한 태그 (2026-10-08, 최신 10-Q).
EXT_CAPEX: dict[str, list[list[str]]] = {
    'PSX': [['CapitalExpendituresAndInvestments']],
    'COP': [['PaymentToAcquireProductiveAssetsAndInvestments']],
    'TKO': [['PaymentsToAcquirePropertyPlantAndEquipmentAndOther']],
    'D':   [['PaymentsToAcquirePropertyPlantAndEquipmentIncludingNuclearFuel']],
    'DTE': [['PlantAndEquipmentExpendituresUtility', 'PlantAndEquipmentExpendituresNonUtility']],
    # NEE: FPL 설비투자 + NEER 투자 + 핵연료 + 기타를 합산한 회사 고유 합계 태그(= 네 줄의 합과 일치 확인)
    'NEE': [['CapitalExpendituresIndependentPowerInvestmentsAndNuclearFuelPurchases'],
            ['CapitalExpendituresOfFPL', 'IndependentPowerInvestments', 'PaymentsForProceedsFromNuclearFuel',
             'ProceedsPaymentsFromOtherCapitalExpenditures'],
            # 2020~2021 10-Q: FPL 부문 + Gulf Power(2019 인수) + NEER 투자 + 핵연료 + 기타 (태그 이름이 다르다)
            ['CapitalExpendituresOfFPLSegment', 'CapitalExpendituresOfGulfPowerSegment', 'IndependentPowerInvestments',
             'PaymentsForProceedsFromNuclearFuel', 'OtherCapitalExpenditures']],
}


def _cache_path(ticker: str) -> Path:
    return CACHE_DIR / f'{ticker.upper()}.json'


def _load_cache(ticker: str) -> dict:
    p = _cache_path(ticker)
    if p.exists():
        return json.loads(p.read_text())
    return {'done': {}, 'rows': []}


def list_filings(cik: str, headers: dict) -> list[tuple[str, str, str]]:
    """(제출일, 양식, 접수번호) — 최근 목록 + 과거 분할 파일까지 모두."""
    sub = sec_get(f'https://data.sec.gov/submissions/CIK{cik}.json', headers, 60).json()
    blocks = [sub['filings']['recent']]
    for f in sub['filings'].get('files', []):
        if f.get('filingTo', '9999') >= SINCE:
            time.sleep(0.12)
            blocks.append(sec_get(f"https://data.sec.gov/submissions/{f['name']}", headers, 60).json())
    out = []
    for r in blocks:
        for form, d, a in zip(r['form'], r['filingDate'], r['accessionNumber']):
            if form in ('10-Q', '10-K') and d >= SINCE:
                out.append((d, form, a))
    return sorted(set(out))


def _rows_from_filing(parsed: dict, alternatives: list[list[str]], filed: str, form: str, acc: str):
    """파싱 결과에서 대안 순서대로 합산해 행 목록을 만든다. 못 찾으면 None."""
    by_tag: dict[str, dict[tuple, float]] = {}
    for tag, _, start, end, val in parsed['records']:
        if start:
            by_tag.setdefault(tag, {})[(start, end)] = val
    fp = 'FY' if form == '10-K' else parsed.get('fp', '')
    if fp not in ('Q1', 'Q2', 'Q3', 'FY'):
        return None
    for alt in alternatives:
        if not all(t in by_tag for t in alt):
            continue
        periods = set.intersection(*(set(by_tag[t]) for t in alt))
        if not periods:
            continue
        # 설비투자는 지출이라 부호 규약이 태그마다 달라도 크기만 더한다(NEE 2021: FPL·Gulf 음수, NEER 투자 양수 혼재).
        return [{'start': s, 'end': e, 'val': sum(abs(by_tag[t][(s, e)]) for t in alt), 'accn': acc,
                 'fp': fp, 'form': form, 'filed': filed, 'fy': int(e[:4])} for s, e in sorted(periods)]
    return None


def inject(facts: dict, ticker: str, cik: str, headers: dict, log=print) -> int:
    """facts에 합성 태그 EXT_CAPEX를 넣는다(새 공시만 인스턴스를 받는다). 반환: 넣은 행 수."""
    alternatives = EXT_CAPEX.get(ticker.upper())
    if not alternatives:
        return 0
    cache = _load_cache(ticker)
    if cache.get('spec') != alternatives:                   # 태그 정의가 바뀌면 처음부터 다시 읽는다
        cache = {'spec': alternatives, 'done': {}, 'rows': []}
    wanted = {t: 'USD' for alt in alternatives for t in alt}
    new = 0
    for filed, form, acc in list_filings(cik, headers):
        if acc in cache['done']:
            continue
        try:
            url = fb._find_instance(int(cik), acc, headers)
            parsed = fb.parse_instance(fb._get(url, headers).text, wanted, any_ns=True) if url else {}
        except Exception as e:                              # 일시 오류는 다음 실행에서 다시 시도한다
            log(f'  [{ticker}] {form} {filed} 조회 실패: {str(e)[:60]}')
            continue
        rows = _rows_from_filing(parsed, alternatives, filed, form, acc) if parsed and parsed.get('records') else None
        cache['done'][acc] = len(rows) if rows else 0       # 0 = 해당 태그 없음(다른 태그 시대일 수 있음)
        if rows:
            cache['rows'].extend(rows)
            new += 1
        else:
            log(f'  [{ticker}] {form} {filed} {acc}: 설비투자 태그 없음')
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(ticker).write_text(json.dumps(cache, ensure_ascii=False))
    if cache['rows']:
        facts.setdefault('facts', {}).setdefault('us-gaap', {})[SYNTH_TAG] = {'units': {'USD': cache['rows']}}
    return len(cache['rows'])
