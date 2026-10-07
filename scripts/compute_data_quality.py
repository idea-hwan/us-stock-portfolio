"""
종목별 재무 데이터 품질 플래그 계산 (읽기 전용: stocks.db → data/analytics/data_quality.json)

  python scripts/compute_data_quality.py

대시보드가 신호 옆에 '⚠ 데이터 점검' 배지를 달고, 주간 리포트가 해당 신호 종목의 판정을 보류하는 근거.
자동 감지라서 실제 사업 변동(분사 직후 등)일 수도 있다 — 배지는 "확인 필요"라는 뜻이지 "오류 확정"이 아니다.

플래그 (최근 5개 회계연도, TTM·성장률 계산 구간에 들어가는 기간만):
  q4_anomaly  4분기 매출이 같은 해 1~3분기 평균의 0.55배 미만 또는 1.9배 초과.
              4분기는 '연간 − (Q1+Q2+Q3)'로 파생하는데, 분사·사업매각으로 연간 값은 소급 재작성됐고
              분기 값은 원래 값이 섞이면(예: CARR 2023 연간 22,098→18,951 재작성, Q1 원래·Q3 재작성)
              비정상 값이 나온다. 계절성이 큰 소매업도 1.9배 이내라 걸리지 않는다.
  zero_revenue 매출이 정확히 0인 분기 (수집 구멍 또는 SPAC 시절)
  gap         분석 구간 중간에 분기가 통째로 빠져 있음 (TTM 계산이 끊김)
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB = ROOT / 'data' / 'stocks.db'
OUT = ROOT / 'data' / 'analytics' / 'data_quality.json'

Q4_LOW, Q4_HIGH = 0.55, 1.9
RECENT_YEARS = 5


def term_key(term: str) -> int:
    return int(term[:4]) * 4 + int(term[5]) - 1


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    data: dict[str, dict[str, float | None]] = {}
    for t, term, rev in con.execute("select ticker, term, revenue from quarterly_financials"):
        data.setdefault(t, {})[term] = rev

    out = {}
    for t, q in data.items():
        last_year = max(int(x[:4]) for x in q)
        first_year = last_year - RECENT_YEARS + 1
        flags = []
        for y in range(first_year, last_year + 1):
            vals = [q.get(f'{y}Q{i}') for i in (1, 2, 3, 4)]
            if all(v is not None and v > 0 for v in vals):
                ratio = vals[3] / (sum(vals[:3]) / 3)
                if ratio < Q4_LOW or ratio > Q4_HIGH:
                    flags.append({'type': 'q4_anomaly', 'year': y, 'ratio': round(ratio, 2),
                                  'text': f'{y}년 4분기 매출이 1~3분기 평균의 {ratio:.2f}배 (연간 재작성·분기 혼합 의심)'})
        zeros = sorted(x for x, v in q.items() if v == 0 and int(x[:4]) >= first_year)
        if zeros:
            flags.append({'type': 'zero_revenue', 'terms': zeros,
                          'text': f'매출 0인 분기 {len(zeros)}개 ({zeros[0]}~{zeros[-1]})'})
        keys = sorted(term_key(x) for x in q if int(x[:4]) >= first_year)
        if len(keys) > 1:
            missing = sorted(set(range(keys[0], keys[-1] + 1)) - set(keys))
            if missing:
                flags.append({'type': 'gap', 'count': len(missing),
                              'text': f'분석 구간 중간에 빠진 분기 {len(missing)}개'})
        if flags:
            out[t] = flags

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(sorted(out.items())), ensure_ascii=False, indent=0))
    by_type = {}
    for fl in out.values():
        for f in fl:
            by_type[f['type']] = by_type.get(f['type'], 0) + 1
    print(f'데이터 점검 플래그: {len(out)}종목 / {len(data)}종목  {by_type}')
    print(f'→ {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
