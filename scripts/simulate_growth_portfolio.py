#!/usr/bin/env python3
"""
Growth/Value 버킷 포트폴리오 회전 전략 시뮬레이션 (이벤트 기반).

2026-07-03 갱신: PIT(16분기) 보정 + 401종목 확장 유니버스 + 단일조건(▲/▼) 신호로 재작성.
기존 버전은 growth_stocks.csv(현재 시점 기준 static 분류를 전체 과거에 역산 적용 — 생존편향)를
그대로 썼고, 신호도 ★★/★/○ 다단계였음. 이번엔:
  - 이벤트 소스를 pit_buckets16 테이블(각 앵커마다 롤링 재판정된 growth_pit16/value_pit16)로 교체
  - 4개 분류 CSV(growth/value/cyclical/unclassified)를 합쳐 종목의 전체 팩터 히스토리를 복원한 뒤
    PIT 플래그로 필터 (static 분류에서 빠진 과거 적격 구간까지 포함)
  - 신호를 build_dashboard.py의 최종 단일조건(▲ 매수 / ▼ 매도)으로 통일 — growth/value 동일 로직

규칙 (버킷 공통):
  - 최대 10슬롯
  - 매수: 앵커 시점에 ▲ 신호가 뜨면 매수 (빈 슬롯 있을 때)
  - 매도: 매도신호(▼) 뜨면 보유기간 무관 즉시 매도
  - 무신호: 12개월 미만 보유 시 유지, 12개월 이상이면 교체 후보
  - 강제청산: 18개월 도달 시 신호 무관 매도
  - 슬롯이 다 찼는데 새 ▲ 후보 등장 시: 교체 후보(무신호+12개월↑) 중 가장 오래된 것을 매도하고 교체
  - 빈 슬롯(청산 후 대체 종목 없음)은 SPY로 채움

실행: python scripts/simulate_growth_portfolio.py   # growth, value 둘 다 실행
"""

import math
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
ANA_DIR = ROOT / 'data' / 'analytics'
VAL_DB = ROOT / 'data' / 'valuation.db'
PX_DB = ROOT / 'data' / 'prices.db'
PIT_DB = ROOT / 'data' / 'analytics' / 'pit_buckets.db'

T = 0.75
N_SLOTS = 10
MIN_HOLD_MONTHS = 12
MAX_HOLD_MONTHS = 18


# ── 신호 계산 (build_dashboard.py 프로덕션 로직과 동일, growth/value 공용) ──────

def _sf(x):
    if x is None or x == '':
        return None
    try:
        f = float(x)
    except (ValueError, TypeError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f

def _v(row, col): return _sf(row.get(col))
def _low(row, m, ref, t=1.0):
    a, b = _v(row, m), _v(row, ref)
    return a is not None and b is not None and b != 0 and a < b * t
def _neg(row, col):
    v = _v(row, col)
    return v is not None and v < 0
def _pos(row, col):
    v = _v(row, col)
    return v is not None and v > 0
def _acc(row, f, s):
    a, b = _v(row, f), _v(row, s)
    return a is not None and b is not None and a > b
def _high_val(row, cur, avg, T_HIGH=1.25):
    c, a = _v(row, cur), _v(row, avg)
    return c is not None and a is not None and a > 0 and c > 0 and c / a > T_HIGH


def signal_buy(row) -> str:
    """단일조건 매수 신호 (growth/value 공용, build_dashboard.py와 동일)."""
    rev2y_acc = _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum')
    pop_low   = _low(row, 'pop_20d', 'pop_4y', T)
    capex_cut = _neg(row, 'capex_geom_1y_mcum')
    if rev2y_acc and pop_low and capex_cut:
        return '▲'
    return '—'


def signal_sell(row) -> str:
    """단일조건 매도 신호 (growth/value 공용, build_dashboard.py와 동일)."""
    rev_dn   = _neg(row, 'rev_geom_1y_mcum')
    pop_h    = _high_val(row, 'pop_20d', 'pop_4y')
    pfcf_h   = _high_val(row, 'pfcf_20d', 'pfcf_4y')
    capex_up = _pos(row, 'capex_geom_1y_mcum')
    capex_acc = _acc(row, 'capex_geom_1y_mcum', 'capex_geom_2y_mcum')
    if rev_dn and ((pop_h and capex_up) or (pfcf_h and capex_acc)):
        return '▼'
    return '—'


# ── 데이터 로드 ────────────────────────────────────────────────────────────

def load_full_factor_panel() -> pd.DataFrame:
    """4개 분류 CSV(growth/value/cyclical/unclassified)를 합쳐 종목의 전체 팩터
    히스토리를 복원. 각 CSV는 '현재 시점 기준' 분류라 어떤 종목이 지금은 growth가
    아니어도 과거 특정 분기엔 growth_pit16=True였을 수 있어, 개별 CSV만 쓰면
    그 구간이 누락된다(2026-07-03 확인: growth 1,189개 PIT 이벤트 누락)."""
    frames = [pd.read_csv(ANA_DIR / f'{name}_stocks.csv')
              for name in ('growth', 'value', 'cyclical', 'unclassified')]
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.drop_duplicates(subset=['ticker', 'anchor_term'])
    panel['filing_anchor_date'] = pd.to_datetime(panel['filing_anchor_date'])
    return panel


def load_events(bucket: str) -> pd.DataFrame:
    """bucket: 'growth' 또는 'value'. pit_buckets16의 {bucket}_pit16=True인
    (ticker, anchor_term)만 이벤트로 사용."""
    panel = load_full_factor_panel()

    con = sqlite3.connect(PIT_DB)
    pit = pd.read_sql(f"SELECT ticker, anchor_term, {bucket}_pit16 FROM pit_buckets16", con)
    con.close()

    events = panel.merge(pit, on=['ticker', 'anchor_term'], how='inner')
    events = events[events[f'{bucket}_pit16'] == 1].copy()

    con = sqlite3.connect(VAL_DB)
    shares = pd.read_sql(
        "SELECT ticker, anchor_term, shares_latest FROM valuation_multiples", con
    )
    con.close()
    events = events.merge(shares, on=['ticker', 'anchor_term'], how='left')
    events['mktcap_approx'] = events['adj_close_anchor'] * events['shares_latest']

    events['buy_sig'] = events.apply(signal_buy, axis=1)
    events['sell_sig'] = events.apply(signal_sell, axis=1)
    events = events.sort_values('filing_anchor_date').reset_index(drop=True)
    return events


def load_prices(tickers):
    con = sqlite3.connect(PX_DB)
    placeholders = ','.join('?' * len(tickers))
    prices = pd.read_sql(
        f"SELECT ticker, date, adj_close FROM daily_prices WHERE ticker IN ({placeholders})",
        con, params=list(tickers)
    )
    con.close()
    prices['date'] = pd.to_datetime(prices['date'])
    lookup = {}
    for tk, g in prices.groupby('ticker'):
        lookup[tk] = g.set_index('date')['adj_close'].sort_index()
    return lookup


def price_on_or_before(lookup, ticker, date):
    s = lookup.get(ticker)
    if s is None or s.empty:
        return None
    s2 = s[s.index <= date]
    if s2.empty:
        return None
    return float(s2.iloc[-1])


# ── 시뮬레이션 ─────────────────────────────────────────────────────────────

class Slot:
    __slots__ = ('asset', 'entry_date', 'entry_price', 'last_signal', 'multiplier')
    def __init__(self, asset, entry_date, entry_price):
        self.asset = asset
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.last_signal = None
        self.multiplier = 1.0


def run_simulation(bucket: str):
    print(f"\n{'='*60}\n{bucket.upper()} 버킷 시뮬레이션\n{'='*60}")
    print("데이터 로딩 중...")
    events = load_events(bucket)
    tickers = sorted(events['ticker'].unique().tolist())
    price_lookup = load_prices(tickers + ['SPY'])
    print(f"PIT 이벤트 수: {len(events):,}  종목 수: {len(tickers)}")

    sim_start = events['filing_anchor_date'].min()
    sim_end = max(s.index.max() for s in price_lookup.values())
    print(f"시뮬레이션 기간: {sim_start.date()} ~ {sim_end.date()}")

    spy_start_price = price_on_or_before(price_lookup, 'SPY', sim_start)
    slots = [Slot('SPY', sim_start, spy_start_price) for _ in range(N_SLOTS)]

    def close_slot(i, close_date):
        s = slots[i]
        exit_price = price_on_or_before(price_lookup, s.asset, close_date)
        if s.entry_price and exit_price:
            s.multiplier *= exit_price / s.entry_price
        return exit_price

    def open_slot(i, asset, open_date, open_price, signal=None):
        s = slots[i]
        s.asset = asset
        s.entry_date = open_date
        s.entry_price = open_price
        s.last_signal = signal

    trades = []
    missed_opportunities = 0

    for ev in events.itertuples():
        D = ev.filing_anchor_date
        T_ticker = ev.ticker

        # 1. 전역 하우스키핑: 18개월 강제청산
        for i, s in enumerate(slots):
            if s.asset != 'SPY':
                held_months = (D - s.entry_date).days / 30.44
                if held_months >= MAX_HOLD_MONTHS:
                    exit_price = close_slot(i, D)
                    trades.append(('FORCE_EXIT_18M', s.asset, s.entry_date, D, exit_price))
                    spy_p = price_on_or_before(price_lookup, 'SPY', D)
                    open_slot(i, 'SPY', D, spy_p)

        # 2. 보유 중인 T_ticker 슬롯 있으면 매도신호 체크
        held_idx = next((i for i, s in enumerate(slots) if s.asset == T_ticker), None)
        sold_this_event = False
        if held_idx is not None:
            if ev.sell_sig != '—':
                exit_price = close_slot(held_idx, D)
                trades.append(('SELL_SIGNAL', T_ticker, slots[held_idx].entry_date, D, exit_price))
                spy_p = price_on_or_before(price_lookup, 'SPY', D)
                open_slot(held_idx, 'SPY', D, spy_p)
                sold_this_event = True
            else:
                slots[held_idx].last_signal = ev.buy_sig

        # 3. 매수 후보 체크
        if not sold_this_event and held_idx is None and ev.buy_sig == '▲':
            price_t = price_on_or_before(price_lookup, T_ticker, D)
            if price_t is None:
                continue
            open_idx = next((i for i, s in enumerate(slots) if s.asset == 'SPY'), None)
            if open_idx is not None:
                close_slot(open_idx, D)
                open_slot(open_idx, T_ticker, D, price_t, ev.buy_sig)
                trades.append(('BUY_OPEN_SLOT', T_ticker, D, None, price_t))
            else:
                candidates = [
                    i for i, s in enumerate(slots)
                    if s.asset != 'SPY'
                    and s.last_signal != '▲'
                    and (D - s.entry_date).days / 30.44 >= MIN_HOLD_MONTHS
                ]
                if candidates:
                    oldest = min(candidates, key=lambda i: slots[i].entry_date)
                    old_ticker = slots[oldest].asset
                    old_entry = slots[oldest].entry_date
                    exit_price = close_slot(oldest, D)
                    trades.append(('ROTATE_OUT', old_ticker, old_entry, D, exit_price))
                    open_slot(oldest, T_ticker, D, price_t, ev.buy_sig)
                    trades.append(('ROTATE_IN', T_ticker, D, None, price_t))
                else:
                    missed_opportunities += 1

    # 종료 시점 전량 정산
    for i, s in enumerate(slots):
        close_slot(i, sim_end)

    portfolio_multiplier = sum(s.multiplier for s in slots) / N_SLOTS
    spy_end_price = price_on_or_before(price_lookup, 'SPY', sim_end)
    spy_multiplier = spy_end_price / spy_start_price

    years = (sim_end - sim_start).days / 365.25
    port_cagr = portfolio_multiplier ** (1 / years) - 1
    spy_cagr = spy_multiplier ** (1 / years) - 1

    print("\n결과")
    print("-" * 60)
    print(f"기간: {years:.1f}년 ({sim_start.date()} ~ {sim_end.date()})")
    print(f"포트폴리오 총수익률: {(portfolio_multiplier-1)*100:+.1f}%   CAGR: {port_cagr*100:+.2f}%")
    print(f"SPY 총수익률:        {(spy_multiplier-1)*100:+.1f}%   CAGR: {spy_cagr*100:+.2f}%")
    print(f"초과 CAGR: {(port_cagr-spy_cagr)*100:+.2f}%p")
    print(f"\n총 매매 건수: {len([t for t in trades if t[0] in ('SELL_SIGNAL','FORCE_EXIT_18M','ROTATE_OUT')])}")
    print(f"신호 있었지만 슬롯 없어서 놓친 기회: {missed_opportunities}")

    trade_counts = pd.Series([t[0] for t in trades]).value_counts()
    print("\n거래 유형별 건수:")
    print(trade_counts)

    return {
        'bucket': bucket, 'years': years, 'sim_start': sim_start, 'sim_end': sim_end,
        'port_multiplier': portfolio_multiplier, 'spy_multiplier': spy_multiplier,
        'port_cagr': port_cagr, 'spy_cagr': spy_cagr,
        'trades': trades, 'slots': slots, 'missed_opportunities': missed_opportunities,
    }


if __name__ == '__main__':
    results = {b: run_simulation(b) for b in ('growth', 'value')}

    print(f"\n{'='*60}\n요약 비교\n{'='*60}")
    for b, r in results.items():
        print(f"{b:8s}  포트폴리오 CAGR {r['port_cagr']*100:+6.2f}%   "
              f"SPY CAGR {r['spy_cagr']*100:+6.2f}%   "
              f"초과 {(r['port_cagr']-r['spy_cagr'])*100:+6.2f}%p")
