#!/usr/bin/env python3
"""
싸이클 버킷 신호 백테스트
출력: 업종별 × 신호별 alpha_12m 집계
"""

import math
import sqlite3
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).parent.parent
ANA_DIR  = ROOT / 'data' / 'analytics'
RET_DB   = ROOT / 'data' / 'returns.db'

COMPLETE_12M = '2025Q2'   # 이 이하만 12m 수익률 확정
COMPLETE_18M = '2024Q4'   # 이 이하만 18m 수익률 확정


# ── 신호 로직 (build_dashboard.py 와 동일) ────────────────────────────────────

def _sf(x):
    if x is None or x == '':
        return None
    try:
        f = float(x)
    except (ValueError, TypeError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f

def _v(row, col):   return _sf(row.get(col))
def _neg(row, col): v = _v(row, col); return v is not None and v < 0
def _pos(row, col): v = _v(row, col); return v is not None and v > 0
def _low(row, m, ref, t=1.0):
    a, b = _v(row, m), _v(row, ref)
    return a is not None and b is not None and b != 0 and a < b * t

def signal_cyclical(row) -> str:
    ctype = str(row.get('cyclical_type', '') or '')
    T = 0.75
    if ctype == 'semiconductor':
        return '★ op2y역성장' if _neg(row, 'op_geom_2y_mcum') else '—'
    if ctype in ('construction', 'aerospace_defense'):
        val = (_low(row, 'pop_20d', 'pop_4y', T) and
               _low(row, 'ps_20d',  'ps_4y',  T) and
               _low(row, 'pe_20d',  'pe_4y',  T))
        return '★ val저평가' if val else '—'
    if ctype == 'housing':
        val = (_low(row, 'ps_20d',   'ps_4y',  T) and
               _low(row, 'pe_20d',   'pe_4y',  T) and
               _low(row, 'pfcf_20d', 'pfcf_4y', T))
        return '★ val저평가' if val else '—'
    if ctype == 'capital_goods':
        val = (_low(row, 'ps_20d',   'ps_4y',  T) and
               _low(row, 'pe_20d',   'pe_4y',  T) and
               _low(row, 'pfcf_20d', 'pfcf_4y', T))
        cap = _neg(row, 'capex_geom_2y_mcum')
        return '★★ val+cap삭감' if (val and cap) else '★ val' if val else '—'
    if ctype == 'leisure':
        val = (_low(row, 'ps_20d',   'ps_4y',  T) and
               _low(row, 'pe_20d',   'pe_4y',  T) and
               _low(row, 'pfcf_20d', 'pfcf_4y', T))
        cap = _pos(row, 'capex_geom_1y_mcum') and _pos(row, 'op_geom_1y_mcum')
        return '★★ val+cap확대' if (val and cap) else '★ val' if val else '—'
    if ctype == 'retail':
        val = (_low(row, 'pop_20d',  'pop_4y', T) and
               _low(row, 'pe_20d',   'pe_4y',  T) and
               _low(row, 'pfcf_20d', 'pfcf_4y', T))
        cap = _pos(row, 'capex_geom_1y_mcum') and _pos(row, 'op_geom_1y_mcum')
        return '★★ val+cap확대' if (val and cap) else '★ val' if val else '—'
    return '—'


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    snap = pd.read_csv(ANA_DIR / 'cyclical_stocks.csv')

    con  = sqlite3.connect(RET_DB)
    rets = pd.read_sql(
        "SELECT ticker, anchor_term, alpha_12m, alpha_18m FROM forward_returns", con
    )
    con.close()

    df = snap.merge(rets, on=['ticker', 'anchor_term'], how='inner')
    df12 = df[df['anchor_term'] <= COMPLETE_12M].copy()
    df18 = df[df['anchor_term'] <= COMPLETE_18M].copy()

    df12['signal'] = df12.apply(signal_cyclical, axis=1)
    df18['signal'] = df18.apply(signal_cyclical, axis=1)

    print(f"전체 관측: 12m={len(df12):,}행  18m={len(df18):,}행  ({df12['ticker'].nunique()}종목)\n")

    INDUSTRY_ORDER = [
        'semiconductor', 'transport', 'housing', 'auto',
        'leisure', 'aerospace_defense', 'capital_goods', 'construction', 'retail',
    ]

    for ctype in INDUSTRY_ORDER:
        s12 = df12[df12['cyclical_type'] == ctype]
        s18 = df18[df18['cyclical_type'] == ctype]
        if s12.empty:
            continue

        base_n      = len(s12)
        base_a12    = s12['alpha_12m'].mean() * 100
        base_a18    = s18['alpha_18m'].mean() * 100 if not s18.empty else float('nan')

        print(f"── {ctype.upper()}  (베이스 n={base_n}, 12m={base_a12:+.1f}%, 18m={base_a18:+.1f}%)")

        for sig, grp in s12.groupby('signal', sort=False):
            n     = len(grp)
            a12   = grp['alpha_12m'].mean() * 100
            freq  = n / base_n * 100
            g18   = df18[(df18['cyclical_type'] == ctype) & (df18['signal'] == sig)]
            a18   = g18['alpha_18m'].mean() * 100 if not g18.empty else float('nan')
            tickers = ', '.join(sorted(grp['ticker'].unique()))
            a18s  = f'{a18:+.1f}%' if not math.isnan(a18) else '—'
            print(f"   {sig:30s}  n={n:4d} ({freq:4.0f}%)  12m={a12:+.1f}%  18m={a18s}  [{tickers}]")
        print()


if __name__ == '__main__':
    main()
