#!/usr/bin/env python3
"""
성장 버킷 팩터 탐색 시뮬 — PIT(16분기) 교정판.

archive/simulate_growth_factors.py의 재현이지만 이벤트 소스를 바꿈:
  - 구버전: growth_stocks.csv(현재 시점 기준 static 분류를 전체 과거에 역산 적용 — 생존편향)
  - 신버전: data/analytics/all_stocks.csv(전종목 전체 히스토리) + pit_buckets16.growth_pit16=1 필터

세 축: 성장(op/rev/ni/fcf CAGR), 저평가(P/E·P/OP·P/S·P/FCF), 투자(CAPEX·CFO)
단일 팩터 → 2팩터 → 3팩터(세 축 모두) 조합 순으로 alpha_12m/18m 탐색.
"""

import math
import sqlite3
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT    = Path(__file__).parent.parent
ANA_DIR = ROOT / 'data' / 'analytics'
RET_DB  = ROOT / 'data' / 'returns.db'
PIT_DB  = ROOT / 'data' / 'analytics' / 'pit_buckets.db'

T = 0.75   # 저평가 임계값


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


# ── 팩터 정의 (archive 버전과 동일) ───────────────────────────────────────────

FACTORS = [
    # ── 성장 ──
    ('op_1y↑',     lambda r: _pos(r,'op_geom_1y_mcum'),              '성장'),
    ('op_1y↓',     lambda r: _neg(r,'op_geom_1y_mcum'),              '성장'),
    ('op_2y↓',     lambda r: _neg(r,'op_geom_2y_mcum'),              '성장'),
    ('op_acc',     lambda r: _acc(r,'op_geom_1y_mcum','op_geom_2y_mcum'), '성장'),
    ('rev_1y↑',    lambda r: _pos(r,'rev_geom_1y_mcum'),             '성장'),
    ('rev_1y↓',    lambda r: _neg(r,'rev_geom_1y_mcum'),             '성장'),
    ('rev_acc',    lambda r: _acc(r,'rev_geom_1y_mcum','rev_geom_2y_mcum'), '성장'),
    ('rev_2y_acc', lambda r: _acc(r,'rev_geom_2y_mcum','rev_geom_4y_mcum'),'성장'),
    ('ni_1y↑',     lambda r: _pos(r,'ni_geom_1y_mcum'),              '성장'),
    ('ni_1y↓',     lambda r: _neg(r,'ni_geom_1y_mcum'),              '성장'),
    ('ni_acc',     lambda r: _acc(r,'ni_geom_1y_mcum','ni_geom_2y_mcum'),  '성장'),
    ('fcf_1y↑',    lambda r: _pos(r,'fcf_geom_1y_mcum'),             '성장'),
    ('fcf_1y↓',    lambda r: _neg(r,'fcf_geom_1y_mcum'),             '성장'),
    ('fcf_acc',    lambda r: _acc(r,'fcf_geom_1y_mcum','fcf_geom_2y_mcum'),'성장'),
    # ── 저평가 ──
    ('pe_low',     lambda r: _low(r,'pe_20d','pe_4y'),                '저평가'),
    ('pe_high',    lambda r: _high(r,'pe_20d','pe_4y'),               '저평가'),
    ('pop_low',    lambda r: _low(r,'pop_20d','pop_4y'),              '저평가'),
    ('pop_high',   lambda r: _high(r,'pop_20d','pop_4y'),             '저평가'),
    ('ps_low',     lambda r: _low(r,'ps_20d','ps_4y'),                '저평가'),
    ('ps_high',    lambda r: _high(r,'ps_20d','ps_4y'),               '저평가'),
    ('pfcf_low',   lambda r: _low(r,'pfcf_20d','pfcf_4y'),            '저평가'),
    ('pfcf_high',  lambda r: _high(r,'pfcf_20d','pfcf_4y'),           '저평가'),
    # ── 투자 ──
    ('capex_1y↑',  lambda r: _pos(r,'capex_geom_1y_mcum'),           '투자'),
    ('capex_1y↓',  lambda r: _neg(r,'capex_geom_1y_mcum'),           '투자'),
    ('capex_2y↑',  lambda r: _pos(r,'capex_geom_2y_mcum'),           '투자'),
    ('capex_2y↓',  lambda r: _neg(r,'capex_geom_2y_mcum'),           '투자'),
    ('capex_acc',  lambda r: _acc(r,'capex_geom_1y_mcum','capex_geom_2y_mcum'),'투자'),
    ('cfo_1y↑',    lambda r: _pos(r,'cfo_geom_1y_mcum'),             '투자'),
    ('cfo_1y↓',    lambda r: _neg(r,'cfo_geom_1y_mcum'),             '투자'),
]

FACTOR_MAP  = {f[0]: f[1] for f in FACTORS}
FACTOR_AXIS = {f[0]: f[2] for f in FACTORS}


def precompute_masks(df):
    return {lbl: df.apply(fn, axis=1) for lbl, fn, axis in FACTORS}


def stats(df12, m12, df18, m18, base_n):
    g12 = df12[m12]
    n = len(g12)
    if n < 10:
        return None
    a12 = g12['alpha_12m'].mean() * 100
    freq = n / base_n * 100
    g18 = df18[m18]
    a18 = g18['alpha_18m'].mean() * 100 if not g18.empty else float('nan')
    return {'n': n, 'freq': freq, 'a12': a12, 'a18': a18}


def fmt(st):
    a18s = f'{st["a18"]:+.1f}%' if not math.isnan(st['a18']) else '   —  '
    return f'n={st["n"]:5d} ({st["freq"]:4.1f}%)  12m={st["a12"]:+.1f}%  18m={a18s}'


# ── PIT 이벤트 로드 ───────────────────────────────────────────────────────────

def load_pit_growth_panel() -> pd.DataFrame:
    panel = pd.read_csv(ANA_DIR / 'all_stocks.csv')
    panel['filing_anchor_date'] = pd.to_datetime(panel['filing_anchor_date'])

    con = sqlite3.connect(PIT_DB)
    pit = pd.read_sql("SELECT ticker, anchor_term, growth_pit16 FROM pit_buckets16", con)
    con.close()

    events = panel.merge(pit, on=['ticker', 'anchor_term'], how='inner')
    events = events[events['growth_pit16'] == 1].copy()

    con = sqlite3.connect(RET_DB)
    rets = pd.read_sql(
        "SELECT ticker, anchor_term, alpha_12m, alpha_18m FROM forward_returns", con
    )
    con.close()
    events = events.merge(rets, on=['ticker', 'anchor_term'], how='inner')
    return events


def main():
    df = load_pit_growth_panel()

    today = datetime(2026, 7, 22)
    complete_12m_cutoff = today - timedelta(days=366)
    complete_18m_cutoff = today - timedelta(days=549)

    df12 = df[(df['filing_anchor_date'] <= complete_12m_cutoff) & df['alpha_12m'].notna()].copy()
    df18 = df[(df['filing_anchor_date'] <= complete_18m_cutoff) & df['alpha_18m'].notna()].copy()

    base_n   = len(df12)
    base_a12 = df12['alpha_12m'].mean() * 100
    base_a18 = df18['alpha_18m'].mean() * 100
    print(f"PIT growth 이벤트: {df['ticker'].nunique()}종목  전체 {len(df):,}행")
    print(f"12m 완전 구간: {len(df12):,}행 (anchor ≤ {complete_12m_cutoff.date()})")
    print(f"18m 완전 구간: {len(df18):,}행 (anchor ≤ {complete_18m_cutoff.date()})")
    print(f"베이스라인: 12m={base_a12:+.1f}%  18m={base_a18:+.1f}%\n")

    m12 = precompute_masks(df12)
    m18 = precompute_masks(df18)

    # ── 1. 단일 팩터 ─────────────────────────────────────────────────────────
    print("=" * 70)
    print("1. 단일 팩터 (n≥10, 12m alpha 내림차순)")
    print("=" * 70)

    singles = []
    for lbl, fn, axis in FACTORS:
        st = stats(df12, m12[lbl], df18, m18[lbl], base_n)
        if st:
            singles.append((lbl, axis, st))

    singles.sort(key=lambda x: x[2]['a12'], reverse=True)
    for lbl, axis, st in singles:
        marker = '▲' if st['a12'] > base_a12 + 1 else ('▼' if st['a12'] < base_a12 - 1 else ' ')
        print(f"  {marker} [{axis:3s}] {lbl:15s}  {fmt(st)}")

    # ── 2. 2팩터 조합 (축 다르게) ────────────────────────────────────────────
    print()
    print("=" * 70)
    print("2. 2팩터 조합 (서로 다른 축, n≥30, 베이스 +2%p 이상, 12m 내림차순)")
    print("=" * 70)

    factor_labels = [f[0] for f in FACTORS]
    combos2 = []
    for a, b in combinations(factor_labels, 2):
        if FACTOR_AXIS[a] == FACTOR_AXIS[b]:
            continue
        mm12 = m12[a] & m12[b]
        mm18 = m18[a] & m18[b]
        st = stats(df12, mm12, df18, mm18, base_n)
        if st and st['n'] >= 30 and st['a12'] >= base_a12 + 2:
            combos2.append((f'{a} + {b}', st))

    combos2.sort(key=lambda x: x[1]['a12'], reverse=True)
    for lbl, st in combos2[:25]:
        print(f"  ▲ {lbl:40s}  {fmt(st)}")

    # ── 3. 3팩터 조합 (성장+저평가+투자 각 1개) ─────────────────────────────
    print()
    print("=" * 70)
    print("3. 3팩터 조합 (성장+저평가+투자 각 1개, n≥20, 베이스 +3%p 이상)")
    print("=" * 70)

    g_factors = [f[0] for f in FACTORS if f[2] == '성장']
    v_factors = [f[0] for f in FACTORS if f[2] == '저평가']
    i_factors = [f[0] for f in FACTORS if f[2] == '투자']

    combos3 = []
    for g in g_factors:
        for v in v_factors:
            for i in i_factors:
                mm12 = m12[g] & m12[v] & m12[i]
                mm18 = m18[g] & m18[v] & m18[i]
                st = stats(df12, mm12, df18, mm18, base_n)
                if st and st['n'] >= 20 and st['a12'] >= base_a12 + 3:
                    combos3.append((f'{g} + {v} + {i}', st))

    combos3.sort(key=lambda x: x[1]['a12'], reverse=True)
    for lbl, st in combos3[:30]:
        print(f"  ★ {lbl:50s}  {fmt(st)}")

    if not combos3:
        print("  (조건 만족 조합 없음 — n≥20 또는 +3%p 조건 완화 필요)")

    # 현재 프로덕션 신호와 직접 비교
    print()
    print("=" * 70)
    print("4. 현재 프로덕션 신호 직접 검증: rev2y_acc + pop_low + capex_1y↓")
    print("=" * 70)
    mm12 = m12['rev_2y_acc'] & m12['pop_low'] & m12['capex_1y↓']
    mm18 = m18['rev_2y_acc'] & m18['pop_low'] & m18['capex_1y↓']
    st = stats(df12, mm12, df18, mm18, base_n)
    if st:
        print(f"  {fmt(st)}  (베이스 대비 {st['a12']-base_a12:+.1f}%p)")
    else:
        print("  n<10, 통계 불가")


if __name__ == '__main__':
    main()
