"""
매수 후보 스크리닝 — 팩터 분석 결과 적용

실행: python scripts/screen_candidates.py
     python scripts/screen_candidates.py --bucket cyclical
     python scripts/screen_candidates.py --bucket growth
     python scripts/screen_candidates.py --bucket value

출력: 콘솔 + data/analytics/screen_results.csv

팩터 근거: docs/cyclical_classification.md, docs/bucket_factor_analysis.md
"""

import argparse
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent.parent
ANA_DIR = ROOT / 'data' / 'analytics'

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 160)


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _v(row, col):
    """NaN → None, 그 외 float."""
    v = row.get(col)
    if pd.isna(v):
        return None
    return float(v)

def _low(row, m, ref):
    """배수 m이 4y 기준 ref보다 낮으면 True. 어느 쪽이든 NaN이면 False."""
    a, b = _v(row, m), _v(row, ref)
    if a is None or b is None or b == 0:
        return False
    return a < b

def _pos(row, col):
    v = _v(row, col)
    return v is not None and v > 0

def _neg(row, col):
    v = _v(row, col)
    return v is not None and v < 0

def _acc(row, fast, slow):
    """fast 성장률 > slow 성장률 (가속)."""
    a, b = _v(row, fast), _v(row, slow)
    if a is None or b is None:
        return False
    return a > b


# ── 경기순환 업종별 팩터 ──────────────────────────────────────────────────────

def _val_pop_ps_pe(row):
    return (_low(row, 'pop_20d', 'pop_4y') and
            _low(row, 'ps_20d',  'ps_4y')  and
            _low(row, 'pe_20d',  'pe_4y'))

def _val_ps_pe_pfcf(row):
    return (_low(row, 'ps_20d',   'ps_4y')   and
            _low(row, 'pe_20d',   'pe_4y')   and
            _low(row, 'pfcf_20d', 'pfcf_4y'))

def _val_pop_pe_pfcf(row):
    return (_low(row, 'pop_20d',  'pop_4y')  and
            _low(row, 'pe_20d',   'pe_4y')   and
            _low(row, 'pfcf_20d', 'pfcf_4y'))

def _val_ps_pfcf(row):
    return (_low(row, 'ps_20d',   'ps_4y') and
            _low(row, 'pfcf_20d', 'pfcf_4y'))

SECTOR_RULES = {
    # (val_fn, capex_fn_or_None, label)
    'construction': (
        _val_pop_ps_pe, None,
        'pop+ps+pe 저평가'
    ),
    'aerospace_defense': (
        _val_pop_ps_pe, None,
        'pop+ps+pe 저평가'
    ),
    'housing': (
        _val_ps_pe_pfcf, None,
        'ps+pe+pfcf 저평가'
    ),
    'capital_goods': (
        _val_ps_pe_pfcf,
        lambda r: _neg(r, 'capex_geom_2y_mcum'),
        'ps+pe+pfcf 저평가 + capex 삭감 2y'
    ),
    'leisure': (
        _val_ps_pe_pfcf,
        lambda r: _pos(r, 'capex_geom_1y_mcum') and _pos(r, 'op_geom_1y_mcum'),
        'ps+pe+pfcf 저평가 + capex확대 + op회복'
    ),
    'retail': (
        _val_pop_pe_pfcf,
        lambda r: _pos(r, 'capex_geom_1y_mcum') and _pos(r, 'op_geom_1y_mcum'),
        'pop+pe+pfcf 저평가 + capex확대 + op회복'
    ),
    'semiconductor': (
        lambda r: _neg(r, 'op_geom_2y_mcum'),  # 핵심 팩터
        None,
        'op 2y 역성장 (사이클 바닥)'
    ),
}

SECTOR_VAL_ONLY = {
    # capex 조건 없이 val만으로 참고 신호
    'semiconductor_val': _val_ps_pfcf,
}


def screen_cyclical(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        sector = row['cyclical_type']
        rule = SECTOR_RULES.get(sector)
        if rule is None:
            # transport, auto: 유효 팩터 없음 → 그냥 포함 (참고용)
            rows.append({**row, 'signal': '(팩터 없음)', 'pass_val': False,
                         'pass_capex': False, 'score': 0})
            continue

        val_fn, cap_fn, label = rule
        pass_val  = val_fn(row)
        pass_cap  = cap_fn(row) if cap_fn else None

        if cap_fn is not None:
            score = (2 if (pass_val and pass_cap) else
                     1 if pass_val else 0)
        else:
            score = 1 if pass_val else 0

        rows.append({**row,
                     'signal':     label,
                     'pass_val':   pass_val,
                     'pass_capex': pass_cap if cap_fn else '-',
                     'score':      score})

    result = pd.DataFrame(rows)
    return result.sort_values(['cyclical_type', 'score'], ascending=[True, False])


# ── 성장주 팩터 ──────────────────────────────────────────────────────────────

def screen_growth(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        # 12m 핵심: op 1y+2y 역성장 + rev 가속
        sig_12m_strong = (
            _neg(row, 'op_geom_1y_mcum') and
            _neg(row, 'op_geom_2y_mcum') and
            _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum')
        )
        # 12m 보수적: op 1y 역성장 + rev 가속
        sig_12m_base = (
            _neg(row, 'op_geom_1y_mcum') and
            _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum')
        )
        # 18m 최강: op 2y 역성장 + rev 2y 가속
        sig_18m = (
            _neg(row, 'op_geom_2y_mcum') and
            _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum')
        )

        score  = (3 if sig_12m_strong else
                  2 if sig_12m_base  else
                  1 if sig_18m       else 0)
        signal = ('op1y+2y역성장+rev가속 (12m최강)' if sig_12m_strong else
                  'op1y역성장+rev가속 (12m보수)'     if sig_12m_base  else
                  'op2y역성장+rev2y가속 (18m최강)'   if sig_18m       else
                  '—')

        rows.append({**row, 'signal': signal, 'score': score})

    result = pd.DataFrame(rows)
    return result.sort_values('score', ascending=False)


# ── 가치주 팩터 (제외 필터) ───────────────────────────────────────────────────

def screen_value(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in df.iterrows():
        # 회피 조건 (하나라도 해당하면 skip)
        avoid_rev   = _neg(row, 'rev_geom_2y_mcum')
        avoid_ps_op = (_low(row, 'ps_20d', 'ps_4y') and _neg(row, 'op_geom_1y_mcum'))
        avoid_pop_op= (_low(row, 'pop_20d', 'pop_4y') and _neg(row, 'op_geom_1y_mcum'))

        skip_reasons = []
        if avoid_rev:    skip_reasons.append('매출2y역성장')
        if avoid_ps_op:  skip_reasons.append('P/S저평가+영업역성장')
        if avoid_pop_op: skip_reasons.append('P/OP저평가+영업역성장')

        skip   = bool(skip_reasons)
        signal = ', '.join(skip_reasons) if skip else '—'
        score  = -len(skip_reasons)

        rows.append({**row, 'skip': skip, 'skip_reason': signal, 'score': score})

    result = pd.DataFrame(rows)
    return result.sort_values('score', ascending=False)


# ── 출력 ─────────────────────────────────────────────────────────────────────

DISPLAY_COLS_CYCLICAL = [
    'ticker', 'cyclical_type', 'anchor_term',
    'signal', 'pass_val', 'pass_capex', 'score',
    'op_geom_1y_mcum', 'op_geom_2y_mcum',
    'rev_geom_1y_mcum', 'capex_geom_1y_mcum', 'capex_geom_2y_mcum',
    'pop_20d', 'pop_4y', 'ps_20d', 'ps_4y', 'pe_20d', 'pe_4y',
    'pfcf_20d', 'pfcf_4y',
]

DISPLAY_COLS_GROWTH = [
    'ticker', 'anchor_term', 'signal', 'score',
    'op_geom_1y_mcum', 'op_geom_2y_mcum',
    'rev_geom_1y_mcum', 'rev_geom_2y_mcum', 'rev_geom_4y_mcum',
]

DISPLAY_COLS_VALUE = [
    'ticker', 'anchor_term', 'skip', 'skip_reason', 'score',
    'rev_geom_2y_mcum', 'op_geom_1y_mcum',
    'ps_20d', 'ps_4y', 'pop_20d', 'pop_4y',
]


def _pct(v):
    if pd.isna(v):
        return 'n/a'
    return f'{float(v)*100:+.1f}%'

def _ratio(v):
    if pd.isna(v):
        return 'n/a'
    return f'{float(v):.1f}x'


def print_cyclical(df: pd.DataFrame):
    print('\n══════════════════════════════════════════')
    print('  경기순환 (CYCLICAL) 스크리닝 결과')
    print('══════════════════════════════════════════')

    for sector in sorted(df['cyclical_type'].unique()):
        sub = df[df['cyclical_type'] == sector].sort_values('score', ascending=False)
        rule = SECTOR_RULES.get(sector)
        factor_desc = rule[2] if rule else '유효 팩터 없음'
        pass_count  = int((sub['score'] >= 1).sum()) if rule else 0

        print(f'\n── {sector.upper()} ({len(sub)}개 종목) — 팩터: {factor_desc}')

        for _, row in sub.iterrows():
            score = int(row.get('score', 0))
            mark  = '★' if score >= 2 else ('○' if score >= 1 else '·')
            print(f'  {mark} {row["ticker"]:6s} [{row["anchor_term"]}]', end='')
            if rule:
                print(f'  op1y={_pct(row.get("op_geom_1y_mcum"))}',
                      f' op2y={_pct(row.get("op_geom_2y_mcum"))}',
                      f' rev1y={_pct(row.get("rev_geom_1y_mcum"))}',
                      f' pop={_ratio(row.get("pop_20d"))}/{_ratio(row.get("pop_4y"))}',
                      f' ps={_ratio(row.get("ps_20d"))}/{_ratio(row.get("ps_4y"))}',
                      f' pe={_ratio(row.get("pe_20d"))}/{_ratio(row.get("pe_4y"))}',
                      f' pfcf={_ratio(row.get("pfcf_20d"))}/{_ratio(row.get("pfcf_4y"))}',
                      end='')
            print()


def print_growth(df: pd.DataFrame):
    print('\n══════════════════════════════════════════')
    print('  성장주 (GROWTH) 스크리닝 결과')
    print('══════════════════════════════════════════')
    print('  팩터: 영업이익 일시 역성장 + 매출 가속 (투자 선집행 구간)')

    for _, row in df.iterrows():
        score = int(row.get('score', 0))
        mark  = '★★' if score >= 3 else ('★' if score >= 2 else ('○' if score >= 1 else '·'))
        print(f'  {mark} {row["ticker"]:6s} [{row["anchor_term"]}]',
              f' op1y={_pct(row.get("op_geom_1y_mcum"))}',
              f' op2y={_pct(row.get("op_geom_2y_mcum"))}',
              f' rev1y={_pct(row.get("rev_geom_1y_mcum"))}',
              f' rev2y={_pct(row.get("rev_geom_2y_mcum"))}',
              f' | {row["signal"]}')


def print_value(df: pd.DataFrame):
    print('\n══════════════════════════════════════════')
    print('  가치주 (VALUE) 스크리닝 결과')
    print('══════════════════════════════════════════')
    print('  팩터: 제외 필터 (skip=True이면 회피)')

    pass_df = df[~df['skip']].copy()
    skip_df = df[ df['skip']].copy()

    print(f'\n  [통과 — {len(pass_df)}개]')
    for _, row in pass_df.iterrows():
        print(f'  ✓ {row["ticker"]:6s} [{row["anchor_term"]}]',
              f' rev2y={_pct(row.get("rev_geom_2y_mcum"))}',
              f' op1y={_pct(row.get("op_geom_1y_mcum"))}',
              f' ps={_ratio(row.get("ps_20d"))}/{_ratio(row.get("ps_4y"))}',
              f' pop={_ratio(row.get("pop_20d"))}/{_ratio(row.get("pop_4y"))}')

    print(f'\n  [회피 — {len(skip_df)}개]')
    for _, row in skip_df.iterrows():
        print(f'  ✗ {row["ticker"]:6s}  이유: {row["skip_reason"]}')


# ── 메인 ─────────────────────────────────────────────────────────────────────

def load_latest(bucket: str) -> pd.DataFrame:
    """종목별 최신 anchor_term 행만 반환."""
    path = ANA_DIR / f'{bucket}_stocks.csv'
    df   = pd.read_csv(path)
    df   = df.sort_values('anchor_term')
    return df.groupby('ticker').last().reset_index()


def main():
    parser = argparse.ArgumentParser(description='팩터 기반 매수 후보 스크리닝')
    parser.add_argument('--bucket', choices=['cyclical', 'growth', 'value', 'all'],
                        default='all', help='분석할 버킷 (기본: all)')
    args = parser.parse_args()

    buckets = (['cyclical', 'growth', 'value'] if args.bucket == 'all'
               else [args.bucket])

    all_results = []

    if 'cyclical' in buckets:
        df  = load_latest('cyclical')
        res = screen_cyclical(df)
        print_cyclical(res)
        res['bucket'] = 'cyclical'
        all_results.append(res)

    if 'growth' in buckets:
        df  = load_latest('growth')
        res = screen_growth(df)
        print_growth(res)
        res['bucket'] = 'growth'
        all_results.append(res)

    if 'value' in buckets:
        df  = load_latest('value')
        res = screen_value(df)
        print_value(res)
        res['bucket'] = 'value'
        all_results.append(res)

    # CSV 저장
    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        out = ANA_DIR / 'screen_results.csv'
        combined.to_csv(out, index=False)
        print(f'\n→ {out.relative_to(ROOT)} 저장 완료 ({len(combined)}행)')


if __name__ == '__main__':
    main()
