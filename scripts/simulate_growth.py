#!/usr/bin/env python3
"""
성장 버킷 신호 백테스트
출력: 신호별 alpha_12m / alpha_18m 집계
"""

import math
import sqlite3
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).parent.parent
ANA_DIR  = ROOT / 'data' / 'analytics'
RET_DB   = ROOT / 'data' / 'returns.db'

COMPLETE_12M = '2025Q2'
COMPLETE_18M = '2024Q4'


# ── 신호 로직 (build_dashboard.py 와 동일) ────────────────────────────────────

def _sf(x):
    if x is None or x == '':
        return None
    try:
        f = float(x)
    except (ValueError, TypeError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f

def _v(row, col):    return _sf(row.get(col))
def _neg(row, col):  v = _v(row, col); return v is not None and v < 0
def _acc(row, f, s):
    a, b = _v(row, f), _v(row, s)
    return a is not None and b is not None and a > b

def signal_growth(row) -> str:
    if _neg(row, 'op_geom_1y_mcum') and _neg(row, 'op_geom_2y_mcum') and _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum'):
        return '★★ op역성장+rev가속'
    if _neg(row, 'op_geom_1y_mcum') and _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum'):
        return '★ op역성장+rev가속'
    if _neg(row, 'op_geom_2y_mcum') and _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum'):
        return '○ op2y역성장+rev2y가속'
    return '—'


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    snap = pd.read_csv(ANA_DIR / 'growth_stocks.csv')
    # growth 라벨 포함 종목만 (growth+value 중복 포함)
    snap = snap[snap['bucket'].str.contains('growth')].copy()

    con  = sqlite3.connect(RET_DB)
    rets = pd.read_sql(
        "SELECT ticker, anchor_term, alpha_12m, alpha_18m FROM forward_returns", con
    )
    con.close()

    df = snap.merge(rets, on=['ticker', 'anchor_term'], how='inner')
    df12 = df[df['anchor_term'] <= COMPLETE_12M].copy()
    df18 = df[df['anchor_term'] <= COMPLETE_18M].copy()

    df12['signal'] = df12.apply(signal_growth, axis=1)
    df18['signal'] = df18.apply(signal_growth, axis=1)

    n_tickers = df12['ticker'].nunique()
    print(f"성장 버킷: {n_tickers}종목  관측 12m={len(df12):,}행  18m={len(df18):,}행")
    print(f"앵커 범위: {df12['anchor_term'].min()} ~ {df12['anchor_term'].max()}\n")

    base_a12 = df12['alpha_12m'].mean() * 100
    base_a18 = df18['alpha_18m'].mean() * 100
    print(f"베이스라인 (전체): 12m={base_a12:+.1f}%  18m={base_a18:+.1f}%\n")

    SIG_ORDER = ['★★ op역성장+rev가속', '★ op역성장+rev가속', '○ op2y역성장+rev2y가속', '—']

    print(f"{'신호':30s}  {'n':>5}  {'빈도':>6}  {'12m':>8}  {'18m':>8}")
    print('─' * 70)
    for sig in SIG_ORDER:
        g12 = df12[df12['signal'] == sig]
        g18 = df18[df18['signal'] == sig]
        n     = len(g12)
        freq  = n / len(df12) * 100
        a12   = g12['alpha_12m'].mean() * 100 if n else float('nan')
        a18   = g18['alpha_18m'].mean() * 100 if not g18.empty else float('nan')
        a12s  = f'{a12:+.1f}%' if not math.isnan(a12) else '—'
        a18s  = f'{a18:+.1f}%' if not math.isnan(a18) else '—'
        print(f'{sig:30s}  {n:5d}  {freq:5.1f}%  {a12s:>8}  {a18s:>8}')

    print()
    # 신호별 발화 종목
    print("── 신호별 발화 종목 ──")
    for sig in SIG_ORDER[:-1]:
        g = df12[df12['signal'] == sig]
        tickers = ', '.join(sorted(g['ticker'].unique()))
        print(f"{sig}: [{tickers}]")

    print()
    # 추가: growth+value 중복 종목만 따로
    overlap = df12[df12['bucket'].str.contains('value')]
    pure    = df12[~df12['bucket'].str.contains('value')]
    print(f"── 중복(growth+value) vs 순수 growth ──")
    print(f"순수 growth:  n={len(pure):,}행  {pure['ticker'].nunique()}종목  12m={pure['alpha_12m'].mean()*100:+.1f}%")
    print(f"growth+value: n={len(overlap):,}행  {overlap['ticker'].nunique()}종목  12m={overlap['alpha_12m'].mean()*100:+.1f}%")


if __name__ == '__main__':
    main()
