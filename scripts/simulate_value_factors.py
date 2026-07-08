#!/usr/bin/env python3
"""
가치 버킷 팩터 탐색 시뮬
세 축: 성장(op/rev/ni/fcf CAGR), 저평가(P/E·P/OP·P/S·P/FCF), 투자(CAPEX·FCF)
"""

import math
import sqlite3
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent.parent
ANA_DIR = ROOT / 'data' / 'analytics'
RET_DB  = ROOT / 'data' / 'returns.db'

COMPLETE_12M = '2025Q2'
COMPLETE_18M = '2024Q4'
T = 0.75


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _sf(x):
    try:
        f = float(x)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except: return None

def _v(r, c):    return _sf(r.get(c))
def _neg(r, c):  v = _v(r, c); return v is not None and v < 0
def _pos(r, c):  v = _v(r, c); return v is not None and v > 0
def _low(r, m, ref): a,b=_v(r,m),_v(r,ref); return a is not None and b is not None and b>0 and a<b*T
def _high(r, m, ref):a,b=_v(r,m),_v(r,ref); return a is not None and b is not None and b>0 and a>b/T
def _acc(r, f, s):   a,b=_v(r,f),_v(r,s);   return a is not None and b is not None and a > b


# ── 팩터 정의 ─────────────────────────────────────────────────────────────────

FACTORS = [
    # ── 성장 ──
    ('op_1y↑',     lambda r: _pos(r,'op_geom_1y_mcum'),               '성장'),
    ('op_1y↓',     lambda r: _neg(r,'op_geom_1y_mcum'),               '성장'),
    ('op_2y↓',     lambda r: _neg(r,'op_geom_2y_mcum'),               '성장'),
    ('op_acc',     lambda r: _acc(r,'op_geom_1y_mcum','op_geom_2y_mcum'),  '성장'),
    ('rev_1y↑',    lambda r: _pos(r,'rev_geom_1y_mcum'),              '성장'),
    ('rev_1y↓',    lambda r: _neg(r,'rev_geom_1y_mcum'),              '성장'),
    ('rev_acc',    lambda r: _acc(r,'rev_geom_1y_mcum','rev_geom_2y_mcum'),'성장'),
    ('rev_2y_acc', lambda r: _acc(r,'rev_geom_2y_mcum','rev_geom_4y_mcum'),'성장'),
    ('ni_1y↑',     lambda r: _pos(r,'ni_geom_1y_mcum'),               '성장'),
    ('ni_1y↓',     lambda r: _neg(r,'ni_geom_1y_mcum'),               '성장'),
    ('ni_acc',     lambda r: _acc(r,'ni_geom_1y_mcum','ni_geom_2y_mcum'),  '성장'),
    ('fcf_1y↑',    lambda r: _pos(r,'fcf_geom_1y_mcum'),              '성장'),
    ('fcf_1y↓',    lambda r: _neg(r,'fcf_geom_1y_mcum'),              '성장'),
    ('fcf_acc',    lambda r: _acc(r,'fcf_geom_1y_mcum','fcf_geom_2y_mcum'),'성장'),
    # ── 저평가 ──
    ('pe_low',     lambda r: _low(r,'pe_20d','pe_4y'),                 '저평가'),
    ('pe_high',    lambda r: _high(r,'pe_20d','pe_4y'),                '저평가'),
    ('pop_low',    lambda r: _low(r,'pop_20d','pop_4y'),               '저평가'),
    ('pop_high',   lambda r: _high(r,'pop_20d','pop_4y'),              '저평가'),
    ('ps_low',     lambda r: _low(r,'ps_20d','ps_4y'),                 '저평가'),
    ('ps_high',    lambda r: _high(r,'ps_20d','ps_4y'),                '저평가'),
    ('pfcf_low',   lambda r: _low(r,'pfcf_20d','pfcf_4y'),             '저평가'),
    ('pfcf_high',  lambda r: _high(r,'pfcf_20d','pfcf_4y'),            '저평가'),
    # ── 투자 ──
    ('capex_1y↑',  lambda r: _pos(r,'capex_geom_1y_mcum'),            '투자'),
    ('capex_1y↓',  lambda r: _neg(r,'capex_geom_1y_mcum'),            '투자'),
    ('capex_2y↑',  lambda r: _pos(r,'capex_geom_2y_mcum'),            '투자'),
    ('capex_2y↓',  lambda r: _neg(r,'capex_geom_2y_mcum'),            '투자'),
    ('capex_acc',  lambda r: _acc(r,'capex_geom_1y_mcum','capex_geom_2y_mcum'),'투자'),
    ('cfo_1y↑',    lambda r: _pos(r,'cfo_geom_1y_mcum'),              '투자'),
    ('cfo_1y↓',    lambda r: _neg(r,'cfo_geom_1y_mcum'),              '투자'),
    ('fcf_pos',    lambda r: _pos(r,'fcf_geom_1y_mcum'),              '투자'),
    ('fcf_neg',    lambda r: _neg(r,'fcf_geom_1y_mcum'),              '투자'),
]

FACTOR_MAP  = {f[0]: f[1] for f in FACTORS}
FACTOR_AXIS = {f[0]: f[2] for f in FACTORS}


def apply_factor(df, lbl):
    return df.apply(FACTOR_MAP[lbl], axis=1)


def stats(df12, df18, mask12, mask18, base_n):
    g12 = df12[mask12]
    n   = len(g12)
    if n < 10:
        return None
    a12  = g12['alpha_12m'].mean() * 100
    freq = n / base_n * 100
    g18  = df18[mask18]
    a18  = g18['alpha_18m'].mean() * 100 if not g18.empty else float('nan')
    return {'n': n, 'freq': freq, 'a12': a12, 'a18': a18}


def fmt(st):
    a18s = f'{st["a18"]:+.1f}%' if not math.isnan(st['a18']) else '   —  '
    return f'n={st["n"]:5d} ({st["freq"]:4.1f}%)  12m={st["a12"]:+.1f}%  18m={a18s}'


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    snap = pd.read_csv(ANA_DIR / 'value_stocks.csv')
    snap = snap[snap['bucket'].str.contains('value')].copy()

    con  = sqlite3.connect(RET_DB)
    rets = pd.read_sql(
        "SELECT ticker, anchor_term, alpha_12m, alpha_18m FROM forward_returns", con
    )
    con.close()

    df   = snap.merge(rets, on=['ticker','anchor_term'], how='inner')
    df12 = df[df['anchor_term'] <= COMPLETE_12M].copy()
    df18 = df[df['anchor_term'] <= COMPLETE_18M].copy()

    base_n   = len(df12)
    base_a12 = df12['alpha_12m'].mean() * 100
    base_a18 = df18['alpha_18m'].mean() * 100
    print(f"가치 버킷: {df12['ticker'].nunique()}종목  관측 {base_n:,}행")
    print(f"베이스라인: 12m={base_a12:+.1f}%  18m={base_a18:+.1f}%\n")

    # 순수 value vs growth+value 분리 확인
    pure    = df12[~df12['bucket'].str.contains('growth')]
    overlap = df12[df12['bucket'].str.contains('growth')]
    print(f"순수 value:   n={len(pure):,}행  {pure['ticker'].nunique()}종목  12m={pure['alpha_12m'].mean()*100:+.1f}%")
    print(f"growth+value: n={len(overlap):,}행  {overlap['ticker'].nunique()}종목  12m={overlap['alpha_12m'].mean()*100:+.1f}%\n")

    # ── 1. 단일 팩터 ─────────────────────────────────────────────────────────
    print("=" * 70)
    print("1. 단일 팩터 (n≥10, 12m alpha 내림차순)")
    print("=" * 70)

    singles = []
    for lbl, fn, axis in FACTORS:
        m12 = apply_factor(df12, lbl)
        m18 = apply_factor(df18, lbl)
        st  = stats(df12, df18, m12, m18, base_n)
        if st:
            singles.append((lbl, axis, st))

    singles.sort(key=lambda x: x[2]['a12'], reverse=True)
    for lbl, axis, st in singles:
        marker = '▲' if st['a12'] > base_a12 + 1 else ('▼' if st['a12'] < base_a12 - 1 else ' ')
        print(f"  {marker} [{axis:3s}] {lbl:15s}  {fmt(st)}")

    # ── 2. 2팩터 조합 (축 다르게) ────────────────────────────────────────────
    print()
    print("=" * 70)
    print("2. 2팩터 조합 (서로 다른 축, n≥30, 베이스 +2%p 이상)")
    print("=" * 70)

    factor_labels = [f[0] for f in FACTORS]
    combos2 = []
    for a, b in combinations(factor_labels, 2):
        if FACTOR_AXIS[a] == FACTOR_AXIS[b]:
            continue
        m12 = apply_factor(df12, a) & apply_factor(df12, b)
        m18 = apply_factor(df18, a) & apply_factor(df18, b)
        st  = stats(df12, df18, m12, m18, base_n)
        if st and st['n'] >= 30 and st['a12'] >= base_a12 + 2:
            combos2.append((f'{a} + {b}', st))

    combos2.sort(key=lambda x: x[1]['a12'], reverse=True)
    for lbl, st in combos2[:25]:
        print(f"  ▲ {lbl:40s}  {fmt(st)}")

    # ── 3. 3팩터 조합 (세 축 모두) ───────────────────────────────────────────
    print()
    print("=" * 70)
    print("3. 3팩터 조합 (성장+저평가+투자, n≥20, 베이스 +3%p 이상)")
    print("=" * 70)

    g_factors = [f[0] for f in FACTORS if f[2] == '성장']
    v_factors = [f[0] for f in FACTORS if f[2] == '저평가']
    i_factors = [f[0] for f in FACTORS if f[2] == '투자']

    combos3 = []
    for g in g_factors:
        for v in v_factors:
            for i in i_factors:
                m12 = apply_factor(df12,g) & apply_factor(df12,v) & apply_factor(df12,i)
                m18 = apply_factor(df18,g) & apply_factor(df18,v) & apply_factor(df18,i)
                st  = stats(df12, df18, m12, m18, base_n)
                if st and st['n'] >= 20 and st['a12'] >= base_a12 + 3:
                    combos3.append((f'{g} + {v} + {i}', st))

    combos3.sort(key=lambda x: x[1]['a12'], reverse=True)
    for lbl, st in combos3[:25]:
        print(f"  ★ {lbl:55s}  {fmt(st)}")

    if not combos3:
        print("  (없음 — 조건 완화 필요)")


if __name__ == '__main__':
    main()
