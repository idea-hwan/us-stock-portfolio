"""
종목 분류 (독립 라벨, 중복 허용) → data/analytics/ 스냅샷 CSV

실행: python scripts/classify_stocks.py
     python scripts/classify_stocks.py --as-of 2026Q2
     python scripts/classify_stocks.py --list

분류 기준 (독립 조건, 중복 허용):
  cyclical:    data/cyclical_universe.txt 수동 리스트
  growth:      최근 16분기 연속 op_income > 0
  value:       최근 16분기 연속 net_income > 0
  unclassified: 위 세 조건 모두 미해당

  예) GOOGL → growth + value 동시 해당
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

ROOT         = Path(__file__).parent.parent
TTM_DB       = ROOT / 'data' / 'ttm_valuation.db'
GROWTH_DB    = ROOT / 'data' / 'ttm_growth.db'
VAL_DB       = ROOT / 'data' / 'valuation.db'
PX_DB        = ROOT / 'data' / 'prices.db'
CYCLICAL_TXT = ROOT / 'data' / 'cyclical_universe.txt'
OUT_DIR      = ROOT / 'data' / 'analytics'

MIN_Q        = 16   # 연속 흑자 최소 분기 수 (4년) — PIT 백테스트 검증: 32분기는 검증기간이 너무 짧아짐(2018Q3~)
FWD_MONTHS   = [12, 15, 18]

GROWTH_COLS = [
    'rev_geom_1y_mcum', 'rev_geom_2y_mcum', 'rev_geom_4y_mcum',
    'op_geom_1y_mcum',  'op_geom_2y_mcum',  'op_geom_4y_mcum',
    'ni_geom_1y_mcum',  'ni_geom_2y_mcum',  'ni_geom_4y_mcum',
    'cfo_geom_1y_mcum', 'cfo_geom_2y_mcum', 'cfo_geom_4y_mcum',
    'capex_geom_1y_mcum','capex_geom_2y_mcum','capex_geom_4y_mcum',
    'fcf_geom_1y_mcum', 'fcf_geom_2y_mcum', 'fcf_geom_4y_mcum',
]

SNAPSHOT_COLS = [
    'ticker', 'bucket', 'cyclical_type', 'anchor_term', 'filing_anchor_date',
    'adj_close_anchor',
    'rev_ps', 'op_ps', 'ni_ps', 'cfo_ps', 'capex_ps', 'fcf_ps',
    'pe_20d', 'pe_4y', 'ps_20d', 'ps_4y',
    'pfcf_20d', 'pfcf_4y', 'pop_20d', 'pop_4y',
    *GROWTH_COLS,
    'ret_12m', 'ret_15m', 'ret_18m',
]


# ── 유틸 ───────────────────────────────────────────────────────────────────────

def load_cyclical() -> dict[str, str]:
    """ticker → cyclical_type 매핑 반환. [섹션명] 헤더로 타입 구분."""
    result: dict[str, str] = {}
    current_type = 'cyclical'
    for line in CYCLICAL_TXT.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            current_type = stripped[1:-1]
            continue
        t = stripped.split('#')[0].strip()
        if t:
            result[t] = current_type
    return result


def _last_n_positive(series: pd.Series, col: str, n: int) -> bool:
    """anchor_term 오름차순 정렬된 시리즈에서 마지막 n개가 모두 양수인지."""
    vals = series[col].dropna()
    if len(vals) < n:
        return False
    return bool((vals.iloc[-n:] > 0).all())


# ── 분류 ───────────────────────────────────────────────────────────────────────

def classify(df_ttm: pd.DataFrame, df_growth: pd.DataFrame,
             cyclical_map: dict[str, str], as_of: str | None = None) -> dict[str, tuple[list[str], str]]:
    """ticker → (labels, cyclical_type) 매핑. labels는 복수 허용 (예: ['growth','value']).
    as_of 지정 시 해당 분기까지의 데이터만 사용; None이면 종목별 최신 anchor_term 기준.
    """
    tickers = sorted(df_ttm['ticker'].unique())
    result: dict[str, tuple[list[str], str]] = {}

    for ticker in tickers:
        labels: list[str] = []
        ctype = ''

        if ticker in cyclical_map:
            ctype = cyclical_map[ticker]
            labels.append(f'cyclical_{ctype}' if ctype else 'cyclical')

        rows = df_ttm[df_ttm['ticker'] == ticker].copy()
        if as_of:
            rows = rows[rows['anchor_term'] <= as_of]
        rows = rows.sort_values('anchor_term')

        if _last_n_positive(rows, 'ttm_op_income', MIN_Q):
            labels.append('growth')

        if _last_n_positive(rows, 'ttm_net_income', MIN_Q):
            labels.append('value')

        if not labels:
            labels = ['unclassified']

        result[ticker] = (labels, ctype)

    return result


# ── 선행 수익률 ────────────────────────────────────────────────────────────────

def _forward_returns(px: pd.DataFrame, anchor_d: pd.Timestamp) -> dict[str, float | None]:
    out = {}
    sub = px[px['date'] <= anchor_d]
    if sub.empty:
        return {f'ret_{m}m': None for m in FWD_MONTHS}
    entry_px = float(sub.iloc[-1]['adj_close'])
    for m in FWD_MONTHS:
        target = anchor_d + pd.DateOffset(months=m)
        future = px[px['date'] <= target]
        if future.empty or float(future.iloc[-1]['adj_close']) <= 0 or entry_px <= 0:
            out[f'ret_{m}m'] = None
        else:
            out[f'ret_{m}m'] = float(future.iloc[-1]['adj_close']) / entry_px - 1.0
    return out


# ── 스냅샷 빌드 ────────────────────────────────────────────────────────────────

def build_snapshot(
    ticker: str,
    bucket: str,
    cyclical_type: str,
    df_ttm: pd.DataFrame,
    df_growth: pd.DataFrame,
    df_val: pd.DataFrame,
    df_px: pd.DataFrame,
) -> pd.DataFrame:
    t = df_ttm[df_ttm['ticker'] == ticker].sort_values('anchor_term')
    v = df_val[df_val['ticker'] == ticker].set_index('anchor_term')
    g = df_growth[df_growth['ticker'] == ticker].set_index('anchor_term')
    p = df_px[df_px['ticker'] == ticker].sort_values('date').reset_index(drop=True)
    p['date'] = pd.to_datetime(p['date'])

    rows = []
    for _, tr in t.iterrows():
        term    = tr['anchor_term']
        vr      = v.loc[term] if term in v.index else pd.Series(dtype=float)
        gr      = g.loc[term] if term in g.index else pd.Series(dtype=float)

        shares  = vr.get('shares_latest') if not vr.empty else None
        anchor_d = pd.Timestamp(vr['filing_anchor_date']) if (not vr.empty and pd.notna(vr.get('filing_anchor_date'))) else None

        def ps(col):
            v_ = tr.get(col)
            if pd.isna(v_) or shares is None or shares == 0:
                return None
            return float(v_) / float(shares)

        # 앵커일 이전 20거래일 평균가
        if anchor_d is not None:
            px20 = p[p['date'] <= anchor_d].tail(20)
            adj_close_anchor = float(px20['adj_close'].mean()) if not px20.empty else None
        else:
            adj_close_anchor = None

        rets = _forward_returns(p, anchor_d) if anchor_d is not None else {f'ret_{m}m': None for m in FWD_MONTHS}

        rec = {
            'ticker':             ticker,
            'bucket':             bucket,
            'cyclical_type':      cyclical_type,
            'anchor_term':        term,
            'filing_anchor_date': vr.get('filing_anchor_date') if not vr.empty else None,
            'adj_close_anchor':   adj_close_anchor,
            'rev_ps':             ps('ttm_revenue'),
            'op_ps':              ps('ttm_op_income'),
            'ni_ps':              ps('ttm_net_income'),
            'cfo_ps':             ps('ttm_cfo'),
            'capex_ps':           ps('ttm_capex'),
            'fcf_ps':             ps('ttm_fcf'),
        }
        for col in ['pe_20d','pe_4y','ps_20d','ps_4y','pfcf_20d','pfcf_4y','pop_20d','pop_4y']:
            rec[col] = vr.get(col) if not vr.empty else None
        for col in GROWTH_COLS:
            rec[col] = gr.get(col) if not gr.empty else None
        rec.update(rets)
        rows.append(rec)

    df = pd.DataFrame(rows)
    if not df.empty:
        missing = [c for c in SNAPSHOT_COLS if c not in df.columns]
        for c in missing:
            df[c] = None
        df = df[SNAPSHOT_COLS]
    return df


# ── 메인 ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='종목 분류 → data/analytics/ CSV')
    parser.add_argument('--as-of', default=None,
                        help='분류 기준 분기 (기본: 각 종목 최신 anchor_term 공통 최솟값)')
    parser.add_argument('--list', action='store_true', help='분류 결과만 출력, CSV 미저장')
    args = parser.parse_args()

    print("데이터 로드 중...")
    ttm_conn = sqlite3.connect(TTM_DB)
    df_ttm   = pd.read_sql("SELECT * FROM ttm_financials", ttm_conn)
    ttm_conn.close()

    g_conn    = sqlite3.connect(GROWTH_DB)
    df_growth = pd.read_sql(f"SELECT ticker, anchor_term, {', '.join(GROWTH_COLS)} FROM ttm_growth_series", g_conn)
    g_conn.close()

    v_conn  = sqlite3.connect(VAL_DB)
    df_val  = pd.read_sql("SELECT * FROM valuation_multiples", v_conn)
    v_conn.close()

    px_conn = sqlite3.connect(PX_DB)
    df_px   = pd.read_sql("SELECT ticker, date, adj_close FROM daily_prices", px_conn)
    px_conn.close()

    cyclical_map = load_cyclical()

    as_of = args.as_of or None
    label = as_of if as_of else '종목별 최신 기준'
    print(f"분류 기준: as_of={label}, MIN_Q={MIN_Q}\n")

    bucket_map = classify(df_ttm, df_growth, cyclical_map, as_of)

    # 집계 출력
    from collections import Counter
    label_cnt: Counter = Counter()
    for labels, _ in bucket_map.values():
        for lb in labels:
            label_cnt[lb] += 1

    cyc_cnt = sum(v for k, v in label_cnt.items() if k.startswith('cyclical_'))
    print(f"  {'cyclical':15}: {cyc_cnt:3}개")
    for lb in sorted(k for k in label_cnt if k.startswith('cyclical_')):
        print(f"    └ {lb:20}: {label_cnt[lb]:3}개")
    for b in ['growth', 'value', 'unclassified']:
        print(f"  {b:15}: {label_cnt.get(b, 0):3}개")

    overlap = sum(1 for labels, _ in bucket_map.values() if len(labels) > 1)
    if overlap:
        print(f"  {'(중복)':15}: {overlap:3}개")
    print()

    if args.list:
        cyc_labels = sorted(set(lb for labels, _ in bucket_map.values() for lb in labels if lb.startswith('cyclical_')))
        for b in cyc_labels + ['growth', 'value', 'unclassified']:
            names = sorted(t for t, (labels, _) in bucket_map.items() if b in labels)
            print(f"── {b.upper()} ──")
            print('  ' + '  '.join(names))
            print()
        return

    # 스냅샷 CSV 저장 — 종목은 여러 버킷에 중복 포함 가능
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tickers_all = sorted(df_ttm['ticker'].unique())
    n = len(tickers_all)

    parts: dict[str, list[pd.DataFrame]] = {b: [] for b in ['cyclical','growth','value','unclassified']}

    for i, ticker in enumerate(tickers_all, 1):
        labels, ctype = bucket_map.get(ticker, (['unclassified'], ''))
        bucket_str = ','.join(labels)          # e.g. "growth,value" or "cyclical_auto,growth"
        snap = build_snapshot(ticker, bucket_str, ctype, df_ttm, df_growth, df_val, df_px)
        if not snap.empty:
            for lb in labels:
                key = 'cyclical' if lb.startswith('cyclical') else lb
                parts[key].append(snap)
        print(f"[{i:3}/{n}] {ticker:8} → {bucket_str}")

    print()
    for bucket, dfs in parts.items():
        if not dfs:
            continue
        merged = pd.concat(dfs, ignore_index=True)
        out_path = OUT_DIR / f'{bucket}_stocks.csv'
        merged.to_csv(out_path, index=False)
        print(f"  {bucket:15}: {len(merged):,}행 → {out_path.relative_to(ROOT)}")

    print("\n완료")


if __name__ == '__main__':
    main()
