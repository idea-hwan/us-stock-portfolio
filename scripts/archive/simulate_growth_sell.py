#!/usr/bin/env python3
"""
성장 버킷 매도 신호 시뮬
세 축: 성장 꺾임(op/rev 감속·역성장), 고평가(P/E·P/OP·P/S·P/FCF), 투자 압박(FCF↓·CAPEX↑)
3/6/9m SPY 초과수익 기준
"""

import math
import sqlite3
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent.parent
ANA_DIR = ROOT / 'data' / 'analytics'
RET_DB  = ROOT / 'data' / 'returns.db'

T_HIGH = 1.25


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _sf(x):
    try:
        f = float(x)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except: return None

def _v(r, c):    return _sf(r.get(c))
def _neg(r, c):  v = _v(r, c); return v is not None and v < 0
def _pos(r, c):  v = _v(r, c); return v is not None and v > 0
def _acc(r, f, s): a, b = _v(r,f), _v(r,s); return a is not None and b is not None and a > b
def _dec(r, f, s): a, b = _v(r,f), _v(r,s); return a is not None and b is not None and a < b

def _high(r, cur, avg):
    c, a = _v(r, cur), _v(r, avg)
    return c is not None and a is not None and a > 0 and c > 0 and c / a > T_HIGH


# ── 팩터 정의 ─────────────────────────────────────────────────────────────────

FACTORS = [
    # ── 성장 꺾임 (매도 후보 — 이익/매출 피크아웃) ──
    ('op_dec',      lambda r: _dec(r, 'op_geom_1y_mcum',  'op_geom_2y_mcum'),  '성장'),
    ('op_1y↓',      lambda r: _neg(r, 'op_geom_1y_mcum'),                       '성장'),
    ('op_2y↓',      lambda r: _neg(r, 'op_geom_2y_mcum'),                       '성장'),
    ('op_2y_dec',   lambda r: _dec(r, 'op_geom_2y_mcum',  'op_geom_4y_mcum'),  '성장'),
    ('rev_dec',     lambda r: _dec(r, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum'), '성장'),
    ('rev_1y↓',     lambda r: _neg(r, 'rev_geom_1y_mcum'),                      '성장'),
    ('rev_2y_dec',  lambda r: _dec(r, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum'), '성장'),
    ('ni_dec',      lambda r: _dec(r, 'ni_geom_1y_mcum',  'ni_geom_2y_mcum'),  '성장'),
    ('ni_1y↓',      lambda r: _neg(r, 'ni_geom_1y_mcum'),                       '성장'),
    ('fcf_dec',     lambda r: _dec(r, 'fcf_geom_1y_mcum', 'fcf_geom_2y_mcum'), '성장'),
    # ── 고평가 ──
    ('pe_high',     lambda r: _high(r, 'pe_20d',   'pe_4y'),   '고평가'),
    ('pop_high',    lambda r: _high(r, 'pop_20d',  'pop_4y'),  '고평가'),
    ('ps_high',     lambda r: _high(r, 'ps_20d',   'ps_4y'),   '고평가'),
    ('pfcf_high',   lambda r: _high(r, 'pfcf_20d', 'pfcf_4y'), '고평가'),
    # ── 투자 압박 ──
    ('fcf_1y↓',     lambda r: _neg(r, 'fcf_geom_1y_mcum'),                          '투자'),
    ('capex_1y↑',   lambda r: _pos(r, 'capex_geom_1y_mcum'),                        '투자'),
    ('capex_acc',   lambda r: _acc(r, 'capex_geom_1y_mcum', 'capex_geom_2y_mcum'),  '투자'),
    ('cfo_1y↓',     lambda r: _neg(r, 'cfo_geom_1y_mcum'),                          '투자'),
]

FACTOR_MAP  = {f[0]: f[1] for f in FACTORS}
FACTOR_AXIS = {f[0]: f[2] for f in FACTORS}


def apply_f(df, lbl):
    return df.apply(FACTOR_MAP[lbl], axis=1)


# ── 집계 ──────────────────────────────────────────────────────────────────────

def stats(df, mask, b):
    g = df[mask]
    n = len(g)
    if n < 10:
        return None
    return {
        'n':  n,
        'pct': n / len(df) * 100,
        'a3':  g['alpha_3m'].mean() * 100,
        'a6':  g['alpha_6m'].mean() * 100,
        'a9':  g['alpha_9m'].mean() * 100,
    }

def fmt(st, b):
    def cell(v, bv):
        arr = '▼' if v < bv - 1 else ('▲' if v > bv + 1 else ' ')
        return f'{arr}{v:+.1f}%'
    return (f"n={st['n']:4d}({st['pct']:4.1f}%)  "
            f"3m={cell(st['a3'],b['a3'])}  "
            f"6m={cell(st['a6'],b['a6'])}  "
            f"9m={cell(st['a9'],b['a9'])}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    snap = pd.read_csv(ANA_DIR / 'growth_stocks.csv')
    snap = snap[snap['bucket'].str.contains('growth')].copy()

    con = sqlite3.connect(RET_DB)
    rets = pd.read_sql(
        "SELECT ticker, anchor_term, alpha_3m, alpha_6m, alpha_9m "
        "FROM forward_returns "
        "WHERE alpha_3m IS NOT NULL AND alpha_6m IS NOT NULL AND alpha_9m IS NOT NULL",
        con
    )
    con.close()

    df = snap.merge(rets, on=['ticker', 'anchor_term'], how='inner')
    base_n = len(df)
    b = {
        'a3': df['alpha_3m'].mean() * 100,
        'a6': df['alpha_6m'].mean() * 100,
        'a9': df['alpha_9m'].mean() * 100,
    }

    print(f"성장 버킷: {df['ticker'].nunique()}종목  관측 {base_n:,}행")
    print(f"베이스라인:  3m={b['a3']:+.1f}%  6m={b['a6']:+.1f}%  9m={b['a9']:+.1f}%")

    # ── 1. 단일 팩터 ─────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    print("1. 단일 팩터 (n≥10, 9m alpha 오름차순)")
    print("=" * 74)
    singles = []
    for lbl, fn, axis in FACTORS:
        mask = apply_f(df, lbl)
        st = stats(df, mask, b)
        if st:
            singles.append((lbl, axis, st))
    singles.sort(key=lambda x: x[2]['a9'])
    for lbl, axis, st in singles:
        marker = '▼' if st['a9'] < b['a9'] - 1 else ('▲' if st['a9'] > b['a9'] + 1 else ' ')
        print(f"  {marker} [{axis:4s}] {lbl:13s}  {fmt(st, b)}")

    # ── 2. 2팩터 조합 (축 다르게, 베이스 -2%p 이상) ──────────────────────────
    print()
    print("=" * 74)
    print("2. 2팩터 조합 (서로 다른 축, n≥20, 9m 베이스 -2%p 이상 under)")
    print("=" * 74)
    labels = [f[0] for f in FACTORS]
    combos2 = []
    for a, b2 in combinations(labels, 2):
        if FACTOR_AXIS[a] == FACTOR_AXIS[b2]:
            continue
        mask = apply_f(df, a) & apply_f(df, b2)
        st = stats(df, mask, b)
        if st and st['n'] >= 20 and st['a9'] <= b['a9'] - 2:
            combos2.append((f'{a} + {b2}', st))
    combos2.sort(key=lambda x: x[1]['a9'])
    for lbl, st in combos2[:20]:
        print(f"  ▼ {lbl:40s}  {fmt(st, b)}")
    if not combos2:
        print("  (없음)")

    # ── 3. 3팩터 조합 (세 축 모두, n≥10, 9m 베이스 -3%p 이상) ──────────────
    print()
    print("=" * 74)
    print("3. 3팩터 조합 (성장꺾임+고평가+투자압박, n≥10, 9m 베이스 -3%p 이상 under)")
    print("=" * 74)
    g_lbls = [f[0] for f in FACTORS if f[2] == '성장']
    v_lbls = [f[0] for f in FACTORS if f[2] == '고평가']
    i_lbls = [f[0] for f in FACTORS if f[2] == '투자']
    combos3 = []
    for g in g_lbls:
        for v in v_lbls:
            for i in i_lbls:
                mask = apply_f(df, g) & apply_f(df, v) & apply_f(df, i)
                st = stats(df, mask, b)
                if st and st['n'] >= 10 and st['a9'] <= b['a9'] - 3:
                    combos3.append((f'{g} + {v} + {i}', st))
    combos3.sort(key=lambda x: x[1]['a9'])
    for lbl, st in combos3[:20]:
        print(f"  ▼▼ {lbl:55s}  {fmt(st, b)}")
    if not combos3:
        print("  (없음 — 조건 완화 필요)")


if __name__ == '__main__':
    main()
