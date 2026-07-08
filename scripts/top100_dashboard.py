"""
시총 상위 100개 종목 현황 대시보드

실행: python scripts/top100_dashboard.py
     python scripts/top100_dashboard.py --top 50
     python scripts/top100_dashboard.py --html   (HTML 파일로 저장)

출력: 콘솔 테이블 + (옵션) docs/top100_dashboard.html
"""

import argparse
from pathlib import Path
import sqlite3
import pandas as pd

ROOT    = Path(__file__).parent.parent
ANA_DIR = ROOT / 'data' / 'analytics'
VAL_DB  = ROOT / 'data' / 'valuation.db'
PX_DB   = ROOT / 'data' / 'prices.db'

# ── 데이터 로드 ───────────────────────────────────────────────────────────────

def load_snapshots() -> pd.DataFrame:
    """전체 버킷 최신 스냅샷 합치기."""
    parts = []
    for bucket in ['cyclical', 'growth', 'value', 'unclassified']:
        path = ANA_DIR / f'{bucket}_stocks.csv'
        if not path.exists():
            continue
        df = pd.read_csv(path)
        parts.append(df.sort_values('anchor_term').groupby('ticker').last().reset_index())
    return pd.concat(parts, ignore_index=True)


def load_mktcap() -> pd.DataFrame:
    conn = sqlite3.connect(VAL_DB)
    val = pd.read_sql('SELECT ticker, anchor_term, shares_latest FROM valuation_multiples', conn)
    conn.close()
    val = val.sort_values('anchor_term').groupby('ticker').last().reset_index()[['ticker', 'shares_latest']]

    conn2 = sqlite3.connect(PX_DB)
    px = pd.read_sql(
        "SELECT ticker, date, adj_close FROM daily_prices WHERE date >= '2026-06-01' ORDER BY date DESC",
        conn2
    )
    conn2.close()
    px = px.groupby('ticker').first().reset_index()[['ticker', 'adj_close']]

    merged = px.merge(val, on='ticker')
    merged['mktcap'] = merged['adj_close'] * merged['shares_latest']
    return merged[['ticker', 'adj_close', 'mktcap']].dropna(subset=['mktcap'])


def load_price_perf() -> pd.DataFrame:
    """종목별 1개월·3개월·1년 주가 수익률."""
    conn = sqlite3.connect(PX_DB)
    df = pd.read_sql(
        "SELECT ticker, date, adj_close FROM daily_prices WHERE date >= '2025-06-01' ORDER BY date",
        conn
    )
    conn.close()
    df['date'] = pd.to_datetime(df['date'])

    rows = []
    for ticker, sub in df.groupby('ticker'):
        sub = sub.sort_values('date')
        latest = sub.iloc[-1]['adj_close']
        def ret(n_days):
            idx = max(0, len(sub) - n_days)
            base = sub.iloc[idx]['adj_close']
            return (latest / base - 1) * 100 if base > 0 else None
        rows.append({'ticker': ticker, 'ret_1m': ret(21), 'ret_3m': ret(63), 'ret_1y': ret(252)})
    return pd.DataFrame(rows)


# ── 팩터 신호 계산 ────────────────────────────────────────────────────────────

def _v(row, col):
    v = row.get(col)
    return None if pd.isna(v) else float(v)

def _low(row, m, ref):
    a, b = _v(row, m), _v(row, ref)
    return a is not None and b is not None and b != 0 and a < b

def _neg(row, col): v = _v(row, col); return v is not None and v < 0
def _pos(row, col): v = _v(row, col); return v is not None and v > 0
def _acc(row, f, s): a, b = _v(row, f), _v(row, s); return a is not None and b is not None and a > b


def get_signal(row) -> str:
    bucket = row.get('bucket', '')
    ctype  = row.get('cyclical_type', '')

    if bucket == 'growth':
        if _neg(row, 'op_geom_1y_mcum') and _neg(row, 'op_geom_2y_mcum') and _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum'):
            return '★★ op역성장+rev가속'
        if _neg(row, 'op_geom_1y_mcum') and _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum'):
            return '★ op역성장+rev가속'
        if _neg(row, 'op_geom_2y_mcum') and _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum'):
            return '○ op2y역성장+rev2y가속'
        return '—'

    if bucket == 'cyclical':
        if ctype == 'semiconductor':
            return '★ op2y역성장' if _neg(row, 'op_geom_2y_mcum') else '—'
        if ctype in ('construction', 'aerospace_defense'):
            val = _low(row,'pop_20d','pop_4y') and _low(row,'ps_20d','ps_4y') and _low(row,'pe_20d','pe_4y')
            return '★ val저평가' if val else '—'
        if ctype == 'housing':
            val = _low(row,'ps_20d','ps_4y') and _low(row,'pe_20d','pe_4y') and _low(row,'pfcf_20d','pfcf_4y')
            return '★ val저평가' if val else '—'
        if ctype == 'capital_goods':
            val = _low(row,'ps_20d','ps_4y') and _low(row,'pe_20d','pe_4y') and _low(row,'pfcf_20d','pfcf_4y')
            cap = _neg(row, 'capex_geom_2y_mcum')
            return ('★★ val+cap삭감' if (val and cap) else '★ val' if val else '—')
        if ctype == 'leisure':
            val = _low(row,'ps_20d','ps_4y') and _low(row,'pe_20d','pe_4y') and _low(row,'pfcf_20d','pfcf_4y')
            cap = _pos(row,'capex_geom_1y_mcum') and _pos(row,'op_geom_1y_mcum')
            return ('★★ val+cap확대' if (val and cap) else '★ val' if val else '—')
        if ctype == 'retail':
            val = _low(row,'pop_20d','pop_4y') and _low(row,'pe_20d','pe_4y') and _low(row,'pfcf_20d','pfcf_4y')
            cap = _pos(row,'capex_geom_1y_mcum') and _pos(row,'op_geom_1y_mcum')
            return ('★★ val+cap확대' if (val and cap) else '★ val' if val else '—')
        return '—'

    if bucket == 'value':
        reasons = []
        if _neg(row, 'rev_geom_2y_mcum'): reasons.append('매출역성장')
        if _low(row,'ps_20d','ps_4y') and _neg(row,'op_geom_1y_mcum'): reasons.append('P/S+역성장')
        if _low(row,'pop_20d','pop_4y') and _neg(row,'op_geom_1y_mcum'): reasons.append('P/OP+역성장')
        return ('✗ ' + '+'.join(reasons)) if reasons else '—'

    return '—'


def op_trend(row) -> str:
    """영업이익 방향 요약."""
    v1 = _v(row, 'op_geom_1y_mcum')
    v2 = _v(row, 'op_geom_2y_mcum')
    if v1 is None and v2 is None:
        return 'n/a'
    if v1 is not None and v1 < 0 and v2 is not None and v2 < 0:
        return '▼▼ 2y역성장'
    if v1 is not None and v1 < 0:
        return '▼ 1y역성장'
    if v1 is not None and v2 is not None and v1 > 0 and v1 > v2:
        return '▲▲ 가속'
    if v1 is not None and v1 > 0:
        return '▲ 성장'
    return '— 보합'


def val_position(row) -> str:
    """주요 배수 vs 4y 평균 요약."""
    cheap = []
    exp   = []
    checks = [('P/S', 'ps_20d', 'ps_4y'), ('P/E', 'pe_20d', 'pe_4y'),
              ('P/OP', 'pop_20d', 'pop_4y'), ('P/FCF', 'pfcf_20d', 'pfcf_4y')]
    for label, m, ref in checks:
        a, b = _v(row, m), _v(row, ref)
        if a is None or b is None or b == 0:
            continue
        ratio = a / b
        if ratio < 0.9:
            cheap.append(label)
        elif ratio > 1.1:
            exp.append(label)
    if cheap and not exp:
        return '저평가 (' + '+'.join(cheap) + ')'
    if exp and not cheap:
        return '고평가 (' + '+'.join(exp) + ')'
    if cheap:
        return '혼재 (↓' + '+'.join(cheap) + ')'
    return '중립'


# ── 메인 ─────────────────────────────────────────────────────────────────────

def fmt_pct(v, decimals=1):
    if v is None or pd.isna(v):
        return 'n/a'
    return f'{float(v):+.{decimals}f}%'

def fmt_mktcap(v):
    if v is None or pd.isna(v):
        return 'n/a'
    t = float(v)
    if t >= 1e12:
        return f'{t/1e12:.1f}T'
    if t >= 1e9:
        return f'{t/1e9:.0f}B'
    return f'{t/1e6:.0f}M'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--top', type=int, default=100)
    parser.add_argument('--html', action='store_true')
    args = parser.parse_args()

    snap    = load_snapshots()
    mktcap  = load_mktcap()
    perf    = load_price_perf()

    # GOOG/GOOGL 중복 제거 (시총 작은 쪽 제거)
    dupes = mktcap[mktcap['ticker'].isin(['GOOG','GOOGL'])].sort_values('mktcap', ascending=False)
    if len(dupes) > 1:
        mktcap = mktcap[mktcap['ticker'] != dupes.iloc[1]['ticker']]

    top_tickers = mktcap.sort_values('mktcap', ascending=False).head(args.top)['ticker'].tolist()

    snap_top = snap[snap['ticker'].isin(top_tickers)].copy()
    snap_top = snap_top.merge(mktcap[['ticker','adj_close','mktcap']], on='ticker', how='left')
    snap_top = snap_top.merge(perf, on='ticker', how='left')

    # 팩터 계산
    snap_top['signal']       = snap_top.apply(get_signal, axis=1)
    snap_top['op_trend_str'] = snap_top.apply(op_trend, axis=1)
    snap_top['val_pos']      = snap_top.apply(val_position, axis=1)

    # 버킷 표시
    def bucket_label(row):
        if row['bucket'] == 'cyclical' and row.get('cyclical_type'):
            return f"cyclical/{row['cyclical_type']}"
        return row['bucket']
    snap_top['bucket_label'] = snap_top.apply(bucket_label, axis=1)

    # 시총 순 정렬
    snap_top = snap_top.merge(
        mktcap[['ticker','mktcap']].rename(columns={'mktcap':'mktcap_sort'}),
        on='ticker', how='left'
    ).sort_values('mktcap_sort', ascending=False)

    # ── 콘솔 출력 ─────────────────────────────────────────────────────────────
    header = (f"{'#':>3} {'Ticker':<7} {'시총':>6} {'앵커':>7} {'버킷':<22} "
              f"{'이익방향':<14} {'밸류에이션':<22} {'팩터신호':<22} "
              f"{'1m':>6} {'3m':>7} {'1y':>7}")
    print()
    print(header)
    print('─' * len(header))

    rank = 0
    for _, row in snap_top.iterrows():
        rank += 1
        print(
            f"{rank:>3} "
            f"{row['ticker']:<7} "
            f"{fmt_mktcap(row.get('mktcap_sort')):>6} "
            f"{str(row.get('anchor_term','?')):>7} "
            f"{str(row['bucket_label']):<22} "
            f"{str(row['op_trend_str']):<14} "
            f"{str(row['val_pos']):<22} "
            f"{str(row['signal']):<22} "
            f"{fmt_pct(row.get('ret_1m')):>6} "
            f"{fmt_pct(row.get('ret_3m')):>7} "
            f"{fmt_pct(row.get('ret_1y')):>7}"
        )

    print()
    print(f'총 {rank}개 종목 (시총 상위 {args.top} 기준, GOOG/GOOGL 중복 제거)')

    # ── HTML 저장 ─────────────────────────────────────────────────────────────
    if args.html:
        _save_html(snap_top, rank)


def _save_html(df: pd.DataFrame, total: int):
    rows_html = ''
    rank = 0
    for _, row in df.iterrows():
        rank += 1
        signal = str(row['signal'])
        sig_class = ('sig-strong' if '★★' in signal else
                     'sig-ok'     if '★' in signal or '○' in signal else
                     'sig-warn'   if '✗' in signal else '')
        bucket = str(row['bucket_label'])
        bkt_class = ('bkt-growth'   if 'growth'   in bucket else
                     'bkt-cyclical' if 'cyclical'  in bucket else
                     'bkt-value'    if 'value'     in bucket else '')

        def td(v, cls=''):
            return f'<td class="{cls}">{v}</td>'

        rows_html += (
            f'<tr>'
            f'{td(rank, "rank")}'
            f'{td(row["ticker"], "ticker")}'
            f'{td(fmt_mktcap(row.get("mktcap_sort")), "num")}'
            f'{td(row.get("anchor_term",""), "num")}'
            f'{td(bucket, bkt_class)}'
            f'{td(row["op_trend_str"])}'
            f'{td(row["val_pos"])}'
            f'{td(signal, sig_class)}'
            f'{td(fmt_pct(row.get("ret_1m")), "num")}'
            f'{td(fmt_pct(row.get("ret_3m")), "num")}'
            f'{td(fmt_pct(row.get("ret_1y")), "num")}'
            f'</tr>\n'
        )

    html = f"""<title>Top 100 Dashboard</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
    --text: #e2e4ec; --muted: #6b7280;
    --green: #34d399; --red: #f87171; --yellow: #fbbf24;
    --blue: #60a5fa; --purple: #a78bfa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; padding: 24px; }}
  h1 {{ font-size: 16px; font-weight: 600; color: var(--text); margin-bottom: 4px; letter-spacing: 0.05em; }}
  .sub {{ color: var(--muted); font-size: 11px; margin-bottom: 20px; }}
  .wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; min-width: 960px; }}
  th {{ background: var(--surface); color: var(--muted); font-weight: 500; text-align: left;
        padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; font-size: 11px; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #1e2130; white-space: nowrap; }}
  tr:hover td {{ background: var(--surface); }}
  .rank {{ color: var(--muted); text-align: right; }}
  .ticker {{ color: var(--blue); font-weight: 600; }}
  .num {{ text-align: right; color: var(--muted); }}
  .bkt-growth   {{ color: var(--green); }}
  .bkt-cyclical {{ color: var(--yellow); }}
  .bkt-value    {{ color: var(--purple); }}
  .sig-strong {{ color: var(--green); font-weight: 600; }}
  .sig-ok     {{ color: #86efac; }}
  .sig-warn   {{ color: var(--red); }}
</style>
<h1>시총 상위 100 종목 현황</h1>
<p class="sub">기준: 종목별 최신 재무 앵커 | 팩터: docs/cyclical_classification.md, docs/bucket_factor_analysis.md | {total}개 종목</p>
<div class="wrap">
<table>
<thead>
<tr>
  <th>#</th><th>Ticker</th><th>시총</th><th>앵커</th><th>버킷</th>
  <th>이익 방향</th><th>밸류에이션</th><th>팩터 신호</th>
  <th>1m</th><th>3m</th><th>1y</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>"""

    out = ROOT / 'docs' / 'top100_dashboard.html'
    out.write_text(html, encoding='utf-8')
    print(f'→ {out.relative_to(ROOT)} 저장 완료')


if __name__ == '__main__':
    main()
