#!/usr/bin/env python3
"""
전체 종목 정적 HTML 대시보드 생성
출력: docs/index.html
실행: python scripts/build_dashboard.py
"""

import json
import math
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).parent.parent
ANA_DIR  = ROOT / 'data' / 'analytics'
PX_DB    = ROOT / 'data' / 'prices.db'
VAL_DB   = ROOT / 'data' / 'valuation.db'
CUR_VAL  = ROOT / 'data' / 'analytics' / 'valuation_current.json'
OUT      = ROOT / 'docs' / 'index.html'


# ── 데이터 로드 ───────────────────────────────────────────────────────────────

def load_snapshots() -> pd.DataFrame:
    """전체 버킷 최신 스냅샷 (ticker당 마지막 anchor_term)."""
    parts = []
    for bucket in ['cyclical', 'growth', 'value', 'unclassified']:
        path = ANA_DIR / f'{bucket}_stocks.csv'
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df = df.sort_values('anchor_term').groupby('ticker').last().reset_index()
        parts.append(df)
    snap = pd.concat(parts, ignore_index=True)
    # 중복 ticker 제거 — growth+value 등 복수 버킷 종목은 최신 anchor_term 기준 한 행만 유지
    snap = snap.sort_values('anchor_term').groupby('ticker').last().reset_index()

    univ = pd.read_csv(ROOT / 'data' / 'stock_universe.csv', usecols=['ticker', 'company', 'biz_model'])
    snap = snap.merge(univ, on='ticker', how='left')
    snap['company'] = snap['company'].fillna('')
    return snap


def load_current_prices() -> tuple[pd.DataFrame, str]:
    """최신 가격 및 기준 날짜."""
    con = sqlite3.connect(PX_DB)
    latest = con.execute('SELECT MAX(date) FROM daily_prices').fetchone()[0]
    df = pd.read_sql(
        f"SELECT ticker, adj_close AS price FROM daily_prices WHERE date = '{latest}'",
        con,
    )
    con.close()
    return df, latest


def load_shares() -> pd.DataFrame:
    """최신 shares_latest per ticker (valuation.db)."""
    con = sqlite3.connect(VAL_DB)
    df = pd.read_sql(
        'SELECT ticker, anchor_term, shares_latest FROM valuation_multiples', con
    )
    con.close()
    return (
        df.sort_values('anchor_term')
        .groupby('ticker').last()
        .reset_index()[['ticker', 'shares_latest']]
    )


def load_valuation_current() -> pd.DataFrame:
    """현재(오늘 가격 기준) 밸류에이션 캐시 — compute_valuation_current.py 산출물.

    캐시 파일이 없으면 빈 DataFrame(ticker만) 반환 → merge 시 전부 NaN, 대시보드는 '—' 표시.
    """
    cols = ['ticker', 'pe_now', 'ps_now', 'pop_now', 'pfcf_now', 'val_asof']
    if not CUR_VAL.exists():
        return pd.DataFrame(columns=cols)

    data = json.loads(CUR_VAL.read_text())
    rows = [
        {
            'ticker':   ticker,
            'pe_now':   d.get('pe_now'),
            'ps_now':   d.get('ps_now'),
            'pop_now':  d.get('pop_now'),
            'pfcf_now': d.get('pfcf_now'),
            'val_asof': d.get('price_date'),
        }
        for ticker, d in data.items()
    ]
    return pd.DataFrame(rows, columns=cols)


def load_price_perf() -> pd.DataFrame:
    """종목별 1m / 3m / 1y 주가 수익률."""
    con = sqlite3.connect(PX_DB)
    cutoff = (date.today() - timedelta(days=400)).isoformat()
    df = pd.read_sql(
        f"SELECT ticker, date, adj_close FROM daily_prices WHERE date >= '{cutoff}'"
        " ORDER BY ticker, date",
        con,
    )
    con.close()
    df['date'] = pd.to_datetime(df['date'])

    rows = []
    for ticker, sub in df.groupby('ticker'):
        sub = sub.sort_values('date').reset_index(drop=True)
        n = len(sub)
        latest_px = float(sub.iloc[-1]['adj_close'])

        def _ret(n_days, _n=n, _sub=sub, _lx=latest_px):
            idx = max(0, _n - n_days)
            base = float(_sub.iloc[idx]['adj_close'])
            return (_lx / base - 1) * 100 if base > 0 else None

        rows.append({
            'ticker': ticker,
            'ret_1w': _ret(5),
            'ret_1m': _ret(21),
            'ret_3m': _ret(63),
            'ret_1y': _ret(252),
        })
    return pd.DataFrame(rows)


# ── 유틸리티 ──────────────────────────────────────────────────────────────────

def _sf(x, d=None):
    """safe float — None/NaN/invalid → None, 유효하면 d 소수점 반올림."""
    if x is None or x == '':
        return None
    try:
        f = float(x)
    except (ValueError, TypeError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, d) if d is not None else f


def _annualize(q_pct):
    """분기 CAGR (%) → 연 CAGR (%): (1+r/100)^4 - 1."""
    x = _sf(q_pct)
    if x is None:
        return None
    return round(((1 + x / 100) ** 4 - 1) * 100, 1)


# ── 팩터 신호 계산 ────────────────────────────────────────────────────────────

def _v(row, col):
    return _sf(row.get(col))

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


def _high_val(row, cur_key, avg_key, T_HIGH=1.25) -> bool:
    c, a = _v(row, cur_key), _v(row, avg_key)
    return c is not None and a is not None and a > 0 and c > 0 and c / a > T_HIGH


def _sig_prefix(txt: str) -> str:
    for p in ('▲', '★★', '★', '○', '✗'):
        if txt.startswith(p):
            return p
    return ''


def signal_growth(row) -> str:
    """PIT(16분기) 백테스트 결과 ▲ 신호만 베이스 대비 유의미 — 단일 신호로 단순화."""
    rev2y_acc = _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum')
    pop_low   = _low(row, 'pop_20d', 'pop_4y', 0.75)
    capex_cut = _neg(row, 'capex_geom_1y_mcum')

    if rev2y_acc and pop_low and capex_cut:
        return '▲ rev2y가속+pop저평가+capex↓'
    return '—'


def signal_cyclical(row) -> str:
    ctype = str(row.get('cyclical_type', '') or '')
    T = 0.75
    if ctype == 'semiconductor':
        return '★ op2y역성장' if _neg(row, 'op_geom_2y_mcum') else '—'
    if ctype in ('construction', 'aerospace_defense'):
        val = _low(row, 'pop_20d', 'pop_4y', T) and _low(row, 'ps_20d', 'ps_4y', T) and _low(row, 'pe_20d', 'pe_4y', T)
        return '★ val저평가' if val else '—'
    if ctype == 'housing':
        val = _low(row, 'ps_20d', 'ps_4y', T) and _low(row, 'pe_20d', 'pe_4y', T) and _low(row, 'pfcf_20d', 'pfcf_4y', T)
        return '★ val저평가' if val else '—'
    if ctype == 'capital_goods':
        val = _low(row, 'ps_20d', 'ps_4y', T) and _low(row, 'pe_20d', 'pe_4y', T) and _low(row, 'pfcf_20d', 'pfcf_4y', T)
        cap = _neg(row, 'capex_geom_2y_mcum')
        return '★★ val+cap삭감' if (val and cap) else '★ val' if val else '—'
    if ctype == 'leisure':
        val = _low(row, 'ps_20d', 'ps_4y', T) and _low(row, 'pe_20d', 'pe_4y', T) and _low(row, 'pfcf_20d', 'pfcf_4y', T)
        cap = _pos(row, 'capex_geom_1y_mcum') and _pos(row, 'op_geom_1y_mcum')
        return '★★ val+cap확대' if (val and cap) else '★ val' if val else '—'
    if ctype == 'retail':
        val = _low(row, 'pop_20d', 'pop_4y', T) and _low(row, 'pe_20d', 'pe_4y', T) and _low(row, 'pfcf_20d', 'pfcf_4y', T)
        cap = _pos(row, 'capex_geom_1y_mcum') and _pos(row, 'op_geom_1y_mcum')
        return '★★ val+cap확대' if (val and cap) else '★ val' if val else '—'
    if ctype in ('auto', 'energy'):
        return '★ capex 1y삭감' if _neg(row, 'capex_geom_1y_mcum') else '—'
    return '—'


def signal_value(row) -> str:
    """PIT(16분기) 백테스트 결과 ▲ 신호만 베이스 대비 유의미 — 단일 신호로 단순화 (growth와 동일)."""
    rev2y_acc = _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum')
    pop_low   = _low(row, 'pop_20d', 'pop_4y', 0.75)
    capex_cut = _neg(row, 'capex_geom_1y_mcum')
    if rev2y_acc and pop_low and capex_cut:
        return '▲ rev2y가속+pop저평가+capex↓'
    return '—'


def get_signals(row) -> list[tuple[str, str]]:
    """매수 신호 수집 — 성장·가치. [(bucket_label, detail_text), ...]

    사이클 신호는 유니버스 생존편향 재점검 전까지 대시보드에서 제외
    (signal_cyclical 자체는 남겨둠 — 재검증 후 복원). [[project_next_steps]]
    """
    labels = [b.strip() for b in str(row.get('bucket', '')).split(',')]
    out = []
    if 'growth' in labels:
        s = signal_growth(row)
        if s != '—':
            out.append(('성장', s))
    if 'value' in labels:
        s = signal_value(row)
        if s != '—':
            out.append(('가치', s))
    return out


def _sell_prefix(txt: str) -> str:
    for p in ('▼▼', '▼'):
        if txt.startswith(p):
            return p
    return ''


def sell_growth(row) -> str:
    """성장 버킷 매도 신호 — PIT(16분기) 백테스트로 단일 조건으로 통합."""
    rev_dn  = _neg(row, 'rev_geom_1y_mcum')
    pop_h   = _high_val(row, 'pop_20d',  'pop_4y')
    pfcf_h  = _high_val(row, 'pfcf_20d', 'pfcf_4y')
    capex_up = _pos(row, 'capex_geom_1y_mcum')
    capex_acc = _acc(row, 'capex_geom_1y_mcum', 'capex_geom_2y_mcum')
    if rev_dn and ((pop_h and capex_up) or (pfcf_h and capex_acc)):
        return '▼ rev↓+고평가+capex부담'
    return '—'


def sell_cyclical(row) -> str:
    """사이클 버킷 매도 신호 (백테스트 기반)."""
    ctype  = str(row.get('cyclical_type', '') or '')
    pe_h   = _high_val(row, 'pe_20d',   'pe_4y')
    pop_h  = _high_val(row, 'pop_20d',  'pop_4y')
    ps_h   = _high_val(row, 'ps_20d',   'ps_4y')
    pfcf_h = _high_val(row, 'pfcf_20d', 'pfcf_4y')
    rev_acc = _acc(row, 'rev_geom_1y_mcum', 'rev_geom_2y_mcum')
    rev_dn  = _neg(row, 'rev_geom_1y_mcum')
    fcf_dn  = _neg(row, 'fcf_geom_1y_mcum')
    capex_dn= _neg(row, 'capex_geom_1y_mcum')

    # 전업종 공통 — 가장 강한 3팩터 조합 (절대 마이너스)
    if rev_acc and pe_h and (fcf_dn or capex_dn):
        return '▼▼ rev가속+PE고평가+FCF↓'

    # 업종별
    if ctype == 'housing':
        if pe_h or pop_h: return '▼▼ 밸류 고평가'
    if ctype == 'auto':
        if pop_h: return '▼▼ P/OP 고평가'
        if pe_h:  return '▼ P/E 고평가'
    if ctype == 'aerospace_defense':
        if pfcf_h: return '▼▼ P/FCF 고평가'
        if pe_h:   return '▼ P/E 고평가'
    if ctype == 'retail':
        if pop_h or pe_h: return '▼ 밸류 고평가'
    if ctype == 'leisure':
        if ps_h: return '▼ P/S 고평가'
    if ctype == 'construction':
        if pe_h or pop_h: return '▼ 밸류 고평가'
    if ctype == 'semiconductor':
        if pfcf_h: return '▼ P/FCF 고평가'
    if ctype == 'transport':
        if pfcf_h: return '▼ P/FCF 고평가'
    if ctype == 'materials':
        if rev_dn and pe_h: return '▼ rev↓+PE고평가'
    return '—'


def sell_value(row) -> str:
    """가치 버킷 매도 신호 — PIT(16분기) 백테스트로 단일 조건으로 통합 (성장과 동일 로직)."""
    rev_dn   = _neg(row, 'rev_geom_1y_mcum')
    pop_h    = _high_val(row, 'pop_20d',  'pop_4y')
    pfcf_h   = _high_val(row, 'pfcf_20d', 'pfcf_4y')
    capex_up = _pos(row, 'capex_geom_1y_mcum')
    capex_acc = _acc(row, 'capex_geom_1y_mcum', 'capex_geom_2y_mcum')
    if rev_dn and ((pop_h and capex_up) or (pfcf_h and capex_acc)):
        return '▼ rev↓+고평가+capex부담'
    return '—'


def get_sell_signals(row) -> list[tuple[str, str]]:
    """매도 신호 수집 — 성장·가치. [(bucket_label, detail_text), ...]

    사이클 신호는 유니버스 생존편향 재점검 전까지 대시보드에서 제외
    (sell_cyclical 자체는 남겨둠 — 재검증 후 복원). [[project_next_steps]]
    """
    labels = [b.strip() for b in str(row.get('bucket', '')).split(',')]
    out = []
    if 'growth' in labels:
        s = sell_growth(row)
        if s != '—': out.append(('성장', s))
    if 'value' in labels:
        s = sell_value(row)
        if s != '—': out.append(('가치', s))
    return out


def op_trend(row) -> str:
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


def val_undervalued(row) -> str:
    """P/E 우선, 없으면 P/OP 폴백. P/S 제외. 저평가/고평가/—."""
    T_LOW, T_HIGH = 0.75, 1.25
    for cur_key, avg_key, label in [
        ('pe_20d',  'pe_4y',  'P/E'),
        ('pop_20d', 'pop_4y', 'P/OP'),
    ]:
        c = _v(row, cur_key)
        a = _v(row, avg_key)
        if c is None or a is None or a <= 0 or c <= 0:
            continue
        r = c / a
        if r < T_LOW:
            return f'저평가({label})'
        if r > T_HIGH:
            return f'고평가({label})'
        return '—'
    return '—'


# ── 주식 딕셔너리 빌드 ─────────────────────────────────────────────────────────

def build_stocks(
    snap: pd.DataFrame,
    prices: pd.DataFrame,
    shares: pd.DataFrame,
    perf: pd.DataFrame,
    val_now: pd.DataFrame,
) -> list[dict]:
    df = snap.copy()
    df = df.merge(prices,  on='ticker', how='left')
    df = df.merge(shares,  on='ticker', how='left')
    df = df.merge(perf,    on='ticker', how='left')
    df = df.merge(val_now, on='ticker', how='left')
    df['mktcap'] = df['price'] * df['shares_latest']

    stocks = []
    for _, row in df.iterrows():
        d = row.to_dict()
        mktcap = _sf(d.get('mktcap'))
        stocks.append({
            'ticker':        str(d.get('ticker', '')),
            'company':       str(d.get('company', '') or ''),
            'biz_model':     str(d.get('biz_model', '') or ''),
            'bucket':        str(d.get('bucket', '')),
            'cyclical_type': str(d.get('cyclical_type', '') or ''),
            'anchor_term':   str(d.get('anchor_term', '')),
            # 현재가 / 시총
            'price':         _sf(d.get('price'), 2),
            'mktcap_m':      round(mktcap / 1e6) if mktcap else None,
            # 팩터
            'op_trend':      op_trend(d),
            'undervalued':   val_undervalued(d),
            'signal':        ' · '.join(f'{_sig_prefix(txt)} {b}' for b, txt in get_signals(d)) or '—',
            'sig_detail':    [{'b': b, 'txt': txt} for b, txt in get_signals(d)],
            'sell_sig':      ' · '.join(f'{_sell_prefix(txt)} {b}' for b, txt in get_sell_signals(d)) or '—',
            'sell_detail':   [{'b': b, 'txt': txt} for b, txt in get_sell_signals(d)],
            # 밸류에이션
            'pe_20d':        _sf(d.get('pe_20d'),   1),
            'ps_20d':        _sf(d.get('ps_20d'),   2),
            'pop_20d':       _sf(d.get('pop_20d'),  1),
            'pfcf_20d':      _sf(d.get('pfcf_20d'), 1),
            'pe_4y':         _sf(d.get('pe_4y'),    1),
            'ps_4y':         _sf(d.get('ps_4y'),    2),
            'pop_4y':        _sf(d.get('pop_4y'),   1),
            'pfcf_4y':       _sf(d.get('pfcf_4y'),  1),
            # 밸류에이션 — 현재(오늘 가격) 캐시, compute_valuation_current.py
            'pe_now':        _sf(d.get('pe_now'),   1),
            'ps_now':        _sf(d.get('ps_now'),   2),
            'pop_now':       _sf(d.get('pop_now'),  1),
            'pfcf_now':      _sf(d.get('pfcf_now'), 1),
            'val_asof':      str(d.get('val_asof', '') or ''),
            # TTM 주당
            'rev_ps':        _sf(d.get('rev_ps'),   2),
            'op_ps':         _sf(d.get('op_ps'),    2),
            'ni_ps':         _sf(d.get('ni_ps'),    2),
            'cfo_ps':        _sf(d.get('cfo_ps'),   2),
            'fcf_ps':        _sf(d.get('fcf_ps'),   2),
            # 성장률 연환산 (%)
            'rev_1y':        _annualize(d.get('rev_geom_1y_mcum')),
            'rev_2y':        _annualize(d.get('rev_geom_2y_mcum')),
            'rev_4y':        _annualize(d.get('rev_geom_4y_mcum')),
            'op_1y':         _annualize(d.get('op_geom_1y_mcum')),
            'op_2y':         _annualize(d.get('op_geom_2y_mcum')),
            'op_4y':         _annualize(d.get('op_geom_4y_mcum')),
            'ni_1y':         _annualize(d.get('ni_geom_1y_mcum')),
            'ni_2y':         _annualize(d.get('ni_geom_2y_mcum')),
            'ni_4y':         _annualize(d.get('ni_geom_4y_mcum')),
            'fcf_1y':        _annualize(d.get('fcf_geom_1y_mcum')),
            'fcf_2y':        _annualize(d.get('fcf_geom_2y_mcum')),
            'fcf_4y':        _annualize(d.get('fcf_geom_4y_mcum')),
            'capex_1y':      _annualize(d.get('capex_geom_1y_mcum')),
            'capex_2y':      _annualize(d.get('capex_geom_2y_mcum')),
            'capex_4y':      _annualize(d.get('capex_geom_4y_mcum')),
            # 주가 수익률
            'ret_1w':        _sf(d.get('ret_1w'), 1),
            'ret_1m':        _sf(d.get('ret_1m'), 1),
            'ret_3m':        _sf(d.get('ret_3m'), 1),
            'ret_1y':        _sf(d.get('ret_1y'), 1),
        })

    stocks.sort(key=lambda s: s['mktcap_m'] or 0, reverse=True)
    return stocks


# ── HTML 생성 ─────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>US Stock Dashboard</title>
<style>
:root {
  --bg:#0f1117; --surf:#1a1d27; --surf2:#1e2130;
  --bord:#2a2d3a; --text:#e2e4ec; --muted:#6b7280;
  --green:#34d399; --red:#f87171; --yellow:#fbbf24;
  --blue:#60a5fa; --purple:#a78bfa;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'SF Mono',Consolas,monospace;font-size:12px;padding:28px 24px 20px}
a{color:inherit;text-decoration:none}

/* 헤더 */
.hdr{margin-bottom:22px;padding-bottom:16px;border-bottom:1px solid var(--bord)}
h1{font-size:18px;letter-spacing:.08em;margin-bottom:6px;font-weight:600}
.meta{color:var(--muted);font-size:11px;letter-spacing:.02em}

/* 컨트롤 */
.ctrl{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.cg{display:flex;gap:6px;align-items:center}
.cg-lbl{color:var(--muted);font-size:11px;white-space:nowrap}
.btn{background:var(--surf);border:1px solid var(--bord);color:var(--muted);
     padding:3px 9px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit}
.btn:hover{color:var(--text)}
.btn.on{background:var(--surf2);color:var(--text);border-color:var(--blue)}
.search{background:var(--surf);border:1px solid var(--bord);color:var(--text);
        padding:4px 8px;border-radius:4px;font-family:inherit;font-size:11px;width:130px}
.search:focus{outline:none;border-color:var(--blue)}
#cnt{color:var(--muted);font-size:11px}

/* 테이블 */
.tbl-wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:1020px}
th{background:var(--surf);color:var(--muted);font-weight:500;text-align:left;
   padding:7px 8px;border-bottom:1px solid var(--bord);white-space:nowrap;
   font-size:11px;cursor:pointer;user-select:none}
th:hover{color:var(--text)}
th.asc::after{content:' ↑'}
th.desc::after{content:' ↓'}
th.num-h{text-align:right}
td{padding:7px 8px;border-bottom:1px solid #252838;white-space:nowrap;font-size:11px}
.sr:hover td{background:var(--surf);cursor:pointer}
.sr.open td{background:var(--surf)}
.sr.alt td{background:rgba(255,255,255,0.018)}
.sr.alt:hover td,.sr.alt.open td{background:var(--surf)}

.rk{color:var(--muted);text-align:right;width:36px}
.tk{color:var(--blue);font-weight:600;font-size:12px}
.co{color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis}
.num{text-align:right;color:var(--muted)}
.dim{color:var(--muted)}
.pos{color:var(--green)!important}
.neg{color:var(--red)!important}

.bg{color:var(--green)}
.bc{color:var(--yellow)}
.bv{color:var(--purple)}
.bu{color:var(--muted)}

.sep{padding-left:20px}
.ss{color:var(--green);font-weight:600}
.so{color:#86efac}
.sw{color:var(--red);font-weight:600}
.sw2{color:#fca5a5}

/* 상세 패널 */
.dr{display:none}
.dr td{padding:0;background:var(--surf2)}
.dp{padding:14px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
@media(max-width:900px){.dp{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.dp{grid-template-columns:1fr}}
.ds{background:var(--bg);border:1px solid var(--bord);border-radius:6px;padding:11px}
.dh{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;
    margin-bottom:7px;border-bottom:1px solid var(--bord);padding-bottom:4px}
.dh2{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;
     margin-top:10px;margin-bottom:5px;border-bottom:1px solid var(--bord);padding-bottom:3px}
.drow{display:flex;justify-content:space-between;align-items:baseline;margin:3px 0;gap:8px}
.dl{color:var(--muted);font-size:11px;flex-shrink:0}
.dv{color:var(--text);font-size:11px;font-weight:500;text-align:right}
.gr-hdr{display:grid;grid-template-columns:80px repeat(3,1fr);gap:4px;
        color:var(--muted);font-size:10px;margin:4px 0 2px}
.gr-row{display:grid;grid-template-columns:80px repeat(3,1fr);gap:4px;margin:2px 0;font-size:11px}
.gr-lbl{color:var(--muted)}
.gr-v{text-align:right;font-weight:500}

/* 로직 패널 */
.logic-wrap{display:none;max-width:900px;margin-top:4px}
.lsec{margin-bottom:28px}
.lh1{font-size:12px;font-weight:600;color:var(--text);letter-spacing:.05em;
     border-bottom:1px solid var(--bord);padding-bottom:6px;margin-bottom:12px}
.ltbl{border-collapse:collapse;width:100%;font-size:11px;margin-bottom:0}
.ltbl th{background:var(--surf);color:var(--muted);font-weight:500;
         padding:6px 10px;border-bottom:1px solid var(--bord);text-align:left;white-space:nowrap}
.ltbl td{padding:5px 10px;border-bottom:1px solid #1e2130;vertical-align:top;line-height:1.5}
.ltbl td:first-child{white-space:nowrap}
.lnote{color:var(--muted);font-size:11px;margin-top:8px;line-height:1.6;
       border-left:2px solid var(--bord);padding-left:10px}
.lgrp{margin-bottom:18px}
.lgrp-h{color:var(--blue);font-size:11px;font-weight:600;margin-bottom:8px;letter-spacing:.04em}
.ev{color:var(--green);font-size:11px}
.lind{color:var(--yellow);font-size:11px;font-weight:600;margin:14px 0 6px;letter-spacing:.03em}
.lind.bad{color:var(--red)}
.num{text-align:right;color:var(--muted)}
.lguide{margin-top:10px;padding:8px 10px;border-left:3px solid var(--blue);background:rgba(96,165,250,.08);border-radius:4px;font-size:11px;color:var(--text);line-height:1.6}
</style>
</head>
<body>

<div class="hdr">
  <h1>US Stock Dashboard</h1>
  <p class="meta">가격 기준: __PRICE_DATE__ &nbsp;|&nbsp; 재무 기준: 종목별 최신 anchor_term &nbsp;|&nbsp; <span id="cnt"></span></p>
</div>

<div class="ctrl">
  <div class="cg">
    <span class="cg-lbl">버킷:</span>
    <button class="btn on" data-f="bucket" data-v="all">전체</button>
    <button class="btn" data-f="bucket" data-v="growth">growth</button>
    <button class="btn" data-f="bucket" data-v="value">value</button>
    <button class="btn" data-f="bucket" data-v="cyclical">cyclical</button>
    <button class="btn" data-f="bucket" data-v="unclassified">unclassified</button>
  </div>
  <div class="cg">
    <span class="cg-lbl">매수신호:</span>
    <button class="btn" data-f="sig" data-v="all">전체</button>
    <button class="btn on" data-f="sig" data-v="any">신호 있음</button>
  </div>
  <div class="cg">
    <span class="cg-lbl">매도신호:</span>
    <button class="btn on" data-f="sell" data-v="all">전체</button>
    <button class="btn" data-f="sell" data-v="any">신호 있음</button>
  </div>
  <div class="cg">
    <input type="text" id="search" class="search" placeholder="Ticker 검색…">
  </div>
  <div class="cg" style="margin-left:auto">
    <button class="btn" id="btn-logic" onclick="toggleLogic()">판단 로직</button>
  </div>
</div>

<div class="tbl-wrap">
<table>
<thead>
<tr>
  <th class="num-h" data-col="__rank__">#</th>
  <th data-col="ticker">Ticker</th>
  <th data-col="company">회사명</th>
  <th data-col="bucket">버킷</th>
  <th class="num-h" data-col="mktcap_m">시총 ($M)</th>
  <th class="num-h" data-col="price">가격 ($)</th>
  <th class="num-h" data-col="pe_20d">P/E (20d)</th>
  <th class="num-h" data-col="pe_4y">P/E (4y)</th>
  <th data-col="op_trend">이익 추세</th>
  <th data-col="undervalued">저평가 여부</th>
  <th data-col="signal">매수 신호</th>
  <th data-col="sell_sig">매도 신호</th>
  <th class="num-h" data-col="ret_1w">1w (%)</th>
  <th class="num-h" data-col="ret_1m">1m (%)</th>
  <th class="num-h" data-col="ret_3m">3m (%)</th>
  <th class="num-h" data-col="ret_1y">1y (%)</th>
</tr>
</thead>
<tbody id="tbody"></tbody>
</table>
</div>

<div id="logic" class="logic-wrap">

  <div class="lsec">
    <div class="lh1">버킷 분류 기준</div>
    <table class="ltbl">
      <thead><tr><th>버킷</th><th>분류 조건</th></tr></thead>
      <tbody>
        <tr><td class="bg">growth</td><td>16분기 연속 영업이익 흑자</td></tr>
        <tr><td class="bv">value</td><td>16분기 연속 순이익 흑자</td></tr>
        <tr><td class="bc">cyclical</td><td>수동 지정 — 반도체·자동차·항공방산·건설·자본재·레저·리테일 등 경기민감 업종</td></tr>
      </tbody>
    </table>
  </div>

  <div class="lsec">
    <div class="lh1">이익 추세 판단 — 영업이익 CAGR 기준</div>
    <table class="ltbl">
      <thead><tr><th style="width:130px">라벨</th><th>조건 (연환산 CAGR)</th></tr></thead>
      <tbody>
        <tr><td>▼▼ 2y역성장</td><td>1y CAGR &lt; 0 <em>and</em> 2y CAGR &lt; 0 — 2년 연속 영업이익 감소</td></tr>
        <tr><td>▼ 1y역성장</td><td>1y CAGR &lt; 0 — 최근 1년 영업이익 감소</td></tr>
        <tr><td>▲▲ 가속</td><td>1y CAGR &gt; 0 <em>and</em> 1y CAGR &gt; 2y CAGR — 성장 중이고 속도가 빨라지는 중</td></tr>
        <tr><td>▲ 성장</td><td>1y CAGR &gt; 0 — 영업이익 증가 (속도는 둔화)</td></tr>
        <tr><td>— 보합</td><td>기타 (데이터 부족 등)</td></tr>
      </tbody>
    </table>
    <p class="lnote">CAGR 계산: TTM(직전 4분기 누적) 기준, 분기 단위 기하평균 → 연환산. 1y = 최근 4분기 vs 직전 4분기.</p>
  </div>

  <div class="lsec">
    <div class="lh1">밸류 평가 판단 — 현재 배수 vs 4년 역사 평균</div>
    <table class="ltbl">
      <thead><tr><th style="width:90px">라벨</th><th>조건</th></tr></thead>
      <tbody>
        <tr><td>저평가</td><td>현재(최근 20일 평균) &lt; 4년 평균 × <strong>0.75</strong> — 역사 대비 25% 이상 할인 (백테스트 최적 임계값)</td></tr>
        <tr><td>고평가</td><td>현재(최근 20일 평균) &gt; 4년 평균 × <strong>1.25</strong> — 역사 대비 25% 이상 프리미엄</td></tr>
        <tr><td>혼재</td><td>배수별로 방향이 엇갈림 — ↓ 표기된 배수가 현재 저평가 쪽</td></tr>
        <tr><td>중립</td><td>모든 배수가 ±25% 이내</td></tr>
      </tbody>
    </table>
    <p class="lnote">판정 대상 배수: <strong>P/E · P/S · P/OP · P/FCF</strong> 각각 독립 판정. 예) "저평가 (P/S+P/E)" = P/S와 P/E 현재값이 4년 평균보다 25%+ 낮음. 4년 평균은 과거 16분기 기하평균.</p>
  </div>

  <div class="lsec">
    <p class="lnote"><strong>Growth·Value 공통 방법론:</strong> PIT(point-in-time) 보정 — 16분기 연속 흑자를 각 시점마다 롤링 재판정한 유니버스(2013Q4~2026) 사용. alpha는 평균이 아닌 <strong>중앙값(median)</strong>, 전부 <strong>SPY(S&amp;P 500) 대비 초과수익</strong>. 방법론 상세는 STATUS.md 참조.</p>
  </div>

  <div class="lsec">
    <div class="lh1">Growth 버킷 — 매수 시뮬 / 매도 시뮬</div>

    <div class="lgrp">
      <div class="lgrp-h">▸ 매수 시뮬 (진입 조건)</div>
      <table class="ltbl">
        <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">12m alpha</th><th style="text-align:right;width:90px">18m alpha</th><th style="text-align:right;width:90px">24m alpha</th></tr></thead>
        <tbody>
          <tr>
            <td class="dim">—</td>
            <td>베이스 — 신호 없음, 성장 버킷 전체 중앙값</td>
            <td class="num">100%</td>
            <td class="sw2" style="text-align:right">−1.4%</td>
            <td class="sw2" style="text-align:right">−1.7%</td>
            <td class="sw2" style="text-align:right">−2.1%</td>
          </tr>
          <tr>
            <td class="ss">▲</td>
            <td>매출 2y CAGR &gt; 4y CAGR (가속) <em>and</em> P/OP 저평가 <em>and</em> CAPEX 1y↓</td>
            <td class="num">2.1%</td>
            <td class="ev" style="text-align:right"><strong>+2.6%</strong></td>
            <td class="ev" style="text-align:right">+4.4%</td>
            <td class="ev" style="text-align:right">+2.7%</td>
          </tr>
        </tbody>
      </table>
      <p class="lnote"><strong>▲는 전 구간 우위 유지:</strong> 베이스 대비 12m +4.0%p, 18m +6.1%p, 24m +4.8%p. Energy·소재·유틸 편입 후 베이스 자체가 더 낮아지며(−0.8%→−1.4% 등) 신호의 절대 수익률도 함께 낮아졌지만 격차는 전 구간에서 견고. 이 신호(매출 2y가속 + P/OP 저평가 + CAPEX 삭감) 하나만 매수 기준으로 채택.</p>
    </div>

    <div class="lgrp">
      <div class="lgrp-h">▸ 매도 시뮬 (청산 조건)</div>
      <table class="ltbl">
        <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
        <tbody>
          <tr><td class="dim">—</td><td>베이스 — 신호 없음, 성장 버킷 전체 중앙값</td><td class="num">100%</td><td class="sw2" style="text-align:right">−0.2%</td><td class="sw2" style="text-align:right">−0.6%</td><td class="sw2" style="text-align:right">−1.1%</td></tr>
          <tr><td class="sw">▼</td><td>rev↓ <em>and</em> (P/OP고평가+CAPEX↑ <em>or</em> P/FCF고평가+CAPEX가속)</td><td class="num">4.7%</td><td class="sw" style="text-align:right">−1.8%</td><td class="sw" style="text-align:right">−3.2%</td><td class="sw" style="text-align:right">−5.1%</td></tr>
        </tbody>
      </table>
      <p class="lnote">매출 역성장(rev↓)에 고평가(P/OP 또는 P/FCF)와 CAPEX 부담이 겹칠 때 발동. 베이스 대비 9m 기준 −4.0%p.</p>
    </div>
  </div><!-- /lsec Growth -->

  <div class="lsec">
    <div class="lh1">Value 버킷 — 매수 시뮬 / 매도 시뮬</div>

    <div class="lgrp">
      <div class="lgrp-h">▸ 매수 시뮬 (진입 조건)</div>
      <table class="ltbl">
        <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">12m alpha</th><th style="text-align:right;width:90px">18m alpha</th><th style="text-align:right;width:90px">24m alpha</th></tr></thead>
        <tbody>
          <tr>
            <td class="dim">—</td>
            <td>베이스 — 신호 없음, 가치 버킷 전체 중앙값</td>
            <td class="num">100%</td>
            <td class="sw2" style="text-align:right">−1.2%</td>
            <td class="sw2" style="text-align:right">−1.5%</td>
            <td class="sw2" style="text-align:right">−1.8%</td>
          </tr>
          <tr>
            <td class="ss">▲</td>
            <td>매출 2y CAGR 가속 <em>and</em> P/OP 저평가 <em>and</em> CAPEX 1y↓</td>
            <td class="num">1.8%</td>
            <td class="ev" style="text-align:right"><strong>+7.9%</strong></td>
            <td class="ev" style="text-align:right"><strong>+10.3%</strong></td>
            <td class="ev" style="text-align:right">+7.4%</td>
          </tr>
        </tbody>
      </table>
      <p class="lnote"><strong>▲는 Growth보다 더 강함:</strong> 베이스 대비 12m +9.1%p, 18m +11.8%p, 24m +9.2%p — 전 구간 확대되는 패턴으로 가치 버킷에서 오히려 더 뚜렷한 edge. Energy·소재·유틸 편입 후에도 이 우위는 거의 그대로 유지(원래 +9.2%p/+11.5%p/+8.7%p). 매수 신호는 이 조합 하나로 단순화.</p>
    </div>

    <div class="lgrp">
      <div class="lgrp-h">▸ 매도 시뮬 (청산 조건)</div>
      <table class="ltbl">
        <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
        <tbody>
          <tr><td class="dim">—</td><td>베이스 — 신호 없음, 가치 버킷 전체 중앙값</td><td class="num">100%</td><td class="sw2" style="text-align:right">−0.2%</td><td class="sw2" style="text-align:right">−0.5%</td><td class="sw2" style="text-align:right">−0.9%</td></tr>
          <tr><td class="sw">▼</td><td>rev↓ <em>and</em> (P/OP고평가+CAPEX↑ <em>or</em> P/FCF고평가+CAPEX가속)</td><td class="num">4.7%</td><td class="sw" style="text-align:right">−1.9%</td><td class="sw" style="text-align:right">−3.2%</td><td class="sw" style="text-align:right">−5.1%</td></tr>
        </tbody>
      </table>
      <p class="lnote">Growth와 동일 조건 사용 (가치 버킷에서도 동일하게 유효함을 확인). 베이스 대비 9m 기준 −4.2%p — Growth(−4.0%p)보다 소폭 더 강한 매도 신호.</p>
    </div>
  </div><!-- /lsec Value -->

  <div class="lsec">
    <div class="lh1">정적 신호 검증 — 동적 포트폴리오 시뮬 (Growth/Value)</div>
    <p class="lnote" style="margin-bottom:10px">위 표들은 "신호가 떴을 때 1건의 알파"만 보여줌. 실제로 <strong>10슬롯 포트폴리오</strong>(12m 최소·18m 최대 보유, ▲ 뜨면 매수·▼ 뜨면 즉시 매도·무신호 12개월↑ 중 최고령 교체)를 이 신호로 계속 회전 매매했다면 어떤 결과가 나왔는지 별도 시뮬(`scripts/simulate_growth_portfolio.py`, PIT 이벤트 기준)로 검증.</p>
    <table class="ltbl">
      <thead><tr><th>버킷</th><th style="width:150px">기간</th><th style="text-align:right;width:100px">포트폴리오 CAGR</th><th style="text-align:right;width:90px">SPY CAGR</th><th style="text-align:right;width:80px">초과</th><th style="text-align:right;width:110px">총수익률</th></tr></thead>
      <tbody>
        <tr><td>growth</td><td>12.5년(2013-12~2026-07)</td><td class="ev" style="text-align:right"><strong>+26.69%</strong></td><td class="num" style="text-align:right">+14.05%</td><td class="ev" style="text-align:right">+12.63%p</td><td class="ev" style="text-align:right">+1843.2%</td></tr>
        <tr><td>value</td><td>12.5년(2013-12~2026-07)</td><td class="ev" style="text-align:right"><strong>+25.53%</strong></td><td class="num" style="text-align:right">+14.05%</td><td class="ev" style="text-align:right">+11.48%p</td><td class="ev" style="text-align:right">+1632.1%</td></tr>
      </tbody>
    </table>
    <p class="lguide" style="margin-top:8px"><strong>종합:</strong> 정적 시뮬의 신호를 실제 회전매매에 그대로 적용해도 growth·value 둘 다 SPY 대비 확실한 초과수익 유지. 단, 유니버스 자체가 오늘 기준 생존 종목 위주로 구성돼 있어(인수합병·상장폐지 종목 누락) 절대 수익률은 과장돼 있을 가능성이 있음 — 방법론 상세는 STATUS.md 참조.</p>
  </div><!-- /lsec 동적시뮬 -->

  <div class="lsec">
    <div class="lh1">Cyclical 버킷 — 업종별 매수 시뮬 / 매도 시뮬</div>
    <p class="lnote" style="margin-bottom:12px"><strong>분류 원칙:</strong> 수동 지정 리스트 — 경기 수축기에 이익이 크게 눌리고 Capex·FCF가 경기와 강하게 연동되는 업종. 방산 순수주·농기계(경기순환과 다른 구조적 동인이라 개념적으로 제외)·할인점(GICS상 Consumer Defensive, 다른 카테고리)만 제외.<br>
    <strong>⚠ 2026-07-02 생존편향 수정:</strong> 카지노(LVS/MGM/WYNN)·크루즈(RCL/CCL/NCLH)·의류(RL/TPR)·BBY·SWKS·capital_goods 저성과주(SWK/EMR/MMM/ROK)를 "알파 없음"/"구조적 업황 하락" 등 실적 기반 사유로 빼뒀던 걸 발견해 원복함(상세: STATUS.md).<br>
    <strong>⚠ 2026-07-02 2차 확장:</strong> "이미 growth/value로 잡히니 cyclical에서 빼자"는 로직 자체가 오류(버킷은 비배타적)로 확인 — GICS 산업·섹터 태그가 일치하는데 누락됐던 종목 전부 편입(NVDA/AVGO 등 대형 반도체, CVNA/ORLY 등 자동차, PCAR/VRT 등 산업재, LULU/AMZN 등 리테일). Energy(21)·Materials(17)는 원자재 가격 사이클 업종인데 cyclical_type 자체가 없어 growth/value로만 흘러가던 것을 발견해 신설. "표본이 클수록 신뢰도가 강해진다"는 방침으로 엣지 유무와 무관하게 해당 섹터 전체 편입 — 98→<strong>164종목</strong>.<br>
    <strong>베이스 = 해당 업종 전체 관측 중앙값(median) alpha (vs SPY), 신호 무관.</strong> 신호 프리미엄은 이 베이스 대비 초과수익.</p>

    <p class="lnote" style="margin-bottom:12px"><strong>전업종 공통 매도 신호 (특정 업종 아님, 사이클 전체 164종목 대상):</strong> rev가속 + P/E고평가 + FCF↓ 조합 → 빈도 3.9%, 3m −1.7% / 6m −1.9% / 9m −0.7% (베이스 3m+0.3%/6m+0.4%/9m+0.5%). CAPEX↓ 버전(빈도 3.9%)은 3m −0.6% / 6m −1.3% / 9m −1.3%. 이익 피크아웃+밸류 부담 동시 발생 시 3~6m 내 청산 권장.</p>

    <table class="ltbl">
      <thead><tr><th>업종</th><th style="text-align:right;width:50px">종목수</th><th style="text-align:right;width:90px">베이스 12m</th><th style="text-align:right;width:90px">베이스 18m</th><th style="text-align:right;width:90px">베이스 24m</th></tr></thead>
      <tbody>
        <tr><td>semiconductor</td><td class="num">25</td><td class="ev" style="text-align:right">+5.3%</td><td class="ev" style="text-align:right">+8.2%</td><td class="ev" style="text-align:right">+11.8%</td></tr>
        <tr><td>construction</td><td class="num">10</td><td class="ev" style="text-align:right">+5.5%</td><td class="ev" style="text-align:right">+8.9%</td><td class="ev" style="text-align:right">+11.0%</td></tr>
        <tr><td>housing</td><td class="num">6</td><td class="ev" style="text-align:right">+3.9%</td><td class="ev" style="text-align:right">+8.5%</td><td class="ev" style="text-align:right">+12.0%</td></tr>
        <tr><td>capital_goods</td><td class="num">30</td><td class="ev" style="text-align:right">+1.6%</td><td class="ev" style="text-align:right">+2.1%</td><td class="ev" style="text-align:right">+3.1%</td></tr>
        <tr><td>aerospace_defense</td><td class="num">7</td><td class="ev" style="text-align:right">+5.7%</td><td class="ev" style="text-align:right">+8.2%</td><td class="ev" style="text-align:right">+7.8%</td></tr>
        <tr><td>leisure</td><td class="num">11</td><td class="sw" style="text-align:right">−2.0%</td><td class="sw" style="text-align:right">−3.7%</td><td class="sw" style="text-align:right">−5.4%</td></tr>
        <tr><td>retail</td><td class="num">17</td><td class="ev" style="text-align:right">+1.4%</td><td class="ev" style="text-align:right">+5.0%</td><td class="ev" style="text-align:right">+6.0%</td></tr>
        <tr><td>transport</td><td class="num">12</td><td class="sw" style="text-align:right">−2.2%</td><td class="sw" style="text-align:right">−2.4%</td><td class="sw" style="text-align:right">−4.7%</td></tr>
        <tr><td>auto</td><td class="num">8</td><td class="ev" style="text-align:right">+1.0%</td><td class="dim" style="text-align:right">+0.7%</td><td class="sw2" style="text-align:right">−1.9%</td></tr>
        <tr><td>energy <span class="dim">(신규)</span></td><td class="num">21</td><td class="sw" style="text-align:right">−5.3%</td><td class="sw" style="text-align:right">−9.1%</td><td class="sw" style="text-align:right">−15.5%</td></tr>
        <tr><td>materials <span class="dim">(신규)</span></td><td class="num">17</td><td class="sw" style="text-align:right">−4.0%</td><td class="sw" style="text-align:right">−8.0%</td><td class="sw" style="text-align:right">−9.8%</td></tr>
      </tbody>
    </table>
    <p class="lnote" style="margin-top:6px">업종별 상세(매수·매도 신호)는 아래 각 업종 블록에서 이어서 확인.</p>

    <div class="lind">▹ semiconductor — 재고 사이클</div>
    <p class="lnote" style="margin-bottom:8px"><strong>2026-07-02 갱신:</strong> NVDA·AVGO·TXN·ADI·MPWR 편입(20→25종목). 대형 로직·아날로그주가 더해지며 베이스가 크게 상승(+2.4%→+5.3% 등) — 신호의 절대 프리미엄은 유지되지만 베이스 대비 격차는 다소 축소.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬 (별도 로직: op2y역성장)</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+5.3%</td><td class="ev" style="text-align:right">+8.2%</td><td class="ev" style="text-align:right">+11.8%</td></tr>
        <tr><td class="so">★ op 2y 연속 역성장</td><td class="num">37%</td><td class="ev" style="text-align:right"><strong>+9.7%</strong></td><td class="ev" style="text-align:right"><strong>+15.8%</strong></td><td class="ev" style="text-align:right"><strong>+15.2%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>반도체 역설:</strong> 이익이 2년 연속 역성장 = 재고 사이클 저점. 시장이 과도 할인하는 구간을 역이용. P/OP 저평가(이익 고점)는 오히려 사이클 정점 신호 — 일반 경기순환주와 반대.<br>
    베이스 대비 격차는 12m +4.4%p, 18m +7.6%p, 24m +3.4%p — NVDA 등 대형주 편입으로 베이스 자체가 강해져 예전(+7.5%p/+11.6%p/+7.3%p)보다 좁아졌지만 전 구간 여전히 우위.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, semiconductor 전체 중앙값</td><td class="num">100%</td><td class="ev" style="text-align:right">+1.9%</td><td class="ev" style="text-align:right">+3.7%</td><td class="ev" style="text-align:right">+6.0%</td></tr>
        <tr><td class="sw2">▼</td><td>P/FCF 고평가</td><td class="num">20.2%</td><td class="dim" style="text-align:right">+0.6%</td><td class="dim" style="text-align:right">+1.1%</td><td class="sw2" style="text-align:right">+2.9%</td></tr>
        <tr><td class="sw">▼▼</td><td>rev가속+PE고평가+FCF↓</td><td class="num">8.5%</td><td class="sw" style="text-align:right">−1.7%</td><td class="sw2" style="text-align:right">−0.7%</td><td class="sw2" style="text-align:right">+2.0%</td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>2026-07-02 신규 발견:</strong> 종목 확장 전엔 "신호 미정의"였으나, 표본이 커지며 유의미한 언더퍼폼이 드러남. P/FCF 고평가 9m 기준 베이스 대비 −3.1%p, 전업종 공통 신호(rev가속+PE고평가+FCF↓)는 3m −3.6%p·6m −4.4%p로 더 즉각적.</p>
    <p class="lguide"><strong>종합:</strong> 매수는 여전히 <strong>이익 사이클 방향</strong>이 핵심 — op2y역성장(재고 사이클 저점) 신호가 뜰 때 산다. 다만 매도는 예전과 달리 P/FCF 고평가나 rev가속+PE고평가+FCF↓ 조합이 뜨면 참고할 만한 언더퍼폼 신호로 격상됐다.</p>

    <div class="lind">▹ construction — 착공·인프라 수주 사이클</div>
    <p class="lnote" style="margin-bottom:8px"><strong>2026-07-02 갱신:</strong> 골재·시멘트주 MLM·VMC·CRH(6→9종목)에 이어 엔지니어링 컨설팅 J(Jacobs)까지 편입(→10종목). 베이스는 다소 낮아졌지만(+7.7%→+5.5% 등) ★ 신호는 영향 없이 그대로 유지돼 베이스 대비 격차가 오히려 더 벌어짐.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+5.5%</td><td class="ev" style="text-align:right">+8.9%</td><td class="ev" style="text-align:right">+11.0%</td></tr>
        <tr><td class="so">★ P/OP · P/S · P/E 모두 저평가</td><td class="num">3%</td><td class="ev" style="text-align:right"><strong>+31.9%</strong></td><td class="ev" style="text-align:right"><strong>+38.8%</strong></td><td class="ev" style="text-align:right"><strong>+33.7%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote">착공 감소 시 주가가 이익보다 과도하게 빠지는 구간 포착. 베이스 대비 12m +26.4%p, 18m +29.9%p, 24m +22.7%p(n=17) — J 편입으로 베이스가 낮아지며 격차는 오히려 확대.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, construction 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+1.1%</td><td class="dim" style="text-align:right">+2.4%</td><td class="dim" style="text-align:right">+3.3%</td></tr>
        <tr><td class="sw2">▼</td><td>P/E 고평가</td><td class="num">19.9%</td><td class="sw2" style="text-align:right">−1.5%</td><td class="dim" style="text-align:right">+1.2%</td><td class="dim" style="text-align:right">+1.3%</td></tr>
        <tr><td class="sw2">▼</td><td>rev가속+PE고평가+FCF↓</td><td class="num">6.0%</td><td class="dim" style="text-align:right">+2.3%</td><td class="sw" style="text-align:right">−3.0%</td><td class="sw2" style="text-align:right">−0.6%</td></tr>
      </tbody>
    </table>
    <p class="lnote">P/E 고평가는 9m 기준 베이스 대비 −2.0%p로 다소 약해짐(예전 −3.6%p). 전업종 공통 신호는 6m −5.4%p로 더 뚜렷하나 3m엔 오히려 베이스보다 높아 단기 신호로는 부적합.</p>
    <p class="lguide"><strong>종합:</strong> 기본적으로 <strong>언제 사도 괜찮은 업종</strong>(베이스 자체가 강함). 3중 저평가 매수는 전 구간에서 베이스 대비 뚜렷한 프리미엄. 매도는 P/E 고평가 단독보단 rev가속+PE고평가+FCF↓ 조합(6~9m 관찰)이 더 신뢰할 만함.</p>

    <div class="lind">▹ housing — 주택 착공·모기지 금리 사이클</div>
    <p class="lnote" style="margin-bottom:8px">2026-07-02 감사에서 GICS 산업 매칭 후보 없음 확인 — 6종목 그대로 유지, 수치 변화 없음.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+3.9%</td><td class="ev" style="text-align:right">+8.5%</td><td class="ev" style="text-align:right">+12.0%</td></tr>
        <tr><td class="so">★ P/S · P/E · P/FCF 모두 저평가</td><td class="num">3%</td><td class="ev" style="text-align:right"><strong>+21.8%</strong></td><td class="ev" style="text-align:right"><strong>+31.7%</strong></td><td class="ev" style="text-align:right"><strong>+37.9%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote">세 배수 동시 저평가 = 모기지 급등 시 시장 과매도 구간. <strong>⚠ n=9 소표본</strong>(DHI·LEN 위주)이나, 격차가 전 구간 꾸준히 확대(+17.9%p→+23.2%p→+25.9%p)돼 방향성은 신뢰할 만함.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, housing 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+0.9%</td><td class="dim" style="text-align:right">+1.2%</td><td class="dim" style="text-align:right">+1.4%</td></tr>
        <tr><td class="sw">▼▼</td><td>P/E 또는 P/OP 고평가</td><td class="num">21.8%</td><td class="sw" style="text-align:right">−4.2%</td><td class="sw" style="text-align:right">−5.9%</td><td class="sw" style="text-align:right">−6.5%</td></tr>
      </tbody>
    </table>
    <p class="lnote">금리 민감도가 높아 고평가 시 조정 폭이 크고 길어짐. 9m 기준 베이스 대비 −7.9%p — 중앙값 기준으로도 방향·강도 유지되는 사이클 버킷 최강 매도 신호 중 하나.</p>
    <p class="lguide"><strong>종합:</strong> 사이클 버킷 중 <strong>매수·매도 신호가 가장 깨끗하게 대칭</strong>인 업종. P/S·P/E·P/FCF 모두 저평가일 때 사고(n=9로 작지만 방향 신뢰), P/E 또는 P/OP가 고평가로 돌아서면 판다 — "쌀 때 사고 비쌀 때 판다"는 원칙이 그대로 통함.</p>

    <div class="lind">▹ capital_goods — 기업 설비투자 사이클</div>
    <p class="lnote" style="margin-bottom:8px"><strong>2026-07-02 갱신:</strong> PCAR·VRT·OTIS·XYL·IEX·NDSN·PNR·AOS 편입(22→30종목, Industrials 동일 계열). 베이스가 낮아지며(+2.6%→+1.6% 등) 기존 신호(★/★★)의 절대값은 그대로라 격차는 오히려 커짐.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+1.6%</td><td class="ev" style="text-align:right">+2.1%</td><td class="ev" style="text-align:right">+3.1%</td></tr>
        <tr><td class="so">★ val저평가 (P/S · P/E · P/FCF)</td><td class="num">0.4%</td><td class="ev" style="text-align:right">+8.0%</td><td class="ev" style="text-align:right">+15.5%</td><td class="ev" style="text-align:right">+28.9%</td></tr>
        <tr><td class="ss">★★ val저평가 + CAPEX 2y 삭감</td><td class="num">0.3%</td><td class="ev" style="text-align:right">+7.6%</td><td class="sw" style="text-align:right">+0.1% ⚠</td><td class="ev" style="text-align:right">+9.3%</td></tr>
      </tbody>
    </table>
    <p class="lnote">신규 편입 종목들은 이 3중 저평가 조합을 만족한 이력이 없어 ★/★★ 수치 자체는 불변 — 빈도(%)만 더 낮아짐(모집단 확대). CAPEX 방향은 <strong>삭감</strong>이어야 함. <strong>⚠ ★★ n=4:</strong> 여전히 표본 극소, 18m엔 거의 0%로 붕괴 — ★단독이 더 안정적.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, capital_goods 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+0.4%</td><td class="dim" style="text-align:right">+1.1%</td><td class="dim" style="text-align:right">+1.4%</td></tr>
        <tr><td class="sw2">▼</td><td>P/OP 고평가</td><td class="num">25.3%</td><td class="sw2" style="text-align:right">−0.2%</td><td class="dim" style="text-align:right">+0.3%</td><td class="sw2" style="text-align:right">−0.4%</td></tr>
        <tr><td class="sw2">▼</td><td>rev가속+PE고평가+FCF↓</td><td class="num">7.3%</td><td class="dim" style="text-align:right">+0.1%</td><td class="sw2" style="text-align:right">−0.5%</td><td class="sw" style="text-align:right">−1.8%</td></tr>
      </tbody>
    </table>
    <p class="lnote">P/OP 고평가는 여전히 약한 참고 신호(9m −1.8%p). 전업종 공통 신호가 9m −3.2%p로 더 뚜렷.</p>
    <p class="lguide"><strong>종합:</strong> 매수·매도 둘 다 <strong>신호가 약한 업종</strong>. 3중 저평가(★단독)가 뜰 때만 제한적으로 매수하고 CAPEX삭감 조합(★★)은 표본이 너무 작아 무시. 고평가라고 급하게 팔 근거는 약하니, 확신 있는 저평가 진입 기회가 아니면 관망이 낫다.</p>

    <div class="lind">▹ aerospace_defense — 항공기 납품 백로그 사이클</div>
    <p class="lnote" style="margin-bottom:8px"><strong>2026-07-02 갱신:</strong> AXON 편입(6→7종목, 동일 GICS 산업 — 단 연방 국방예산 직접의존이 아니라 방어적 성격은 약함). 베이스가 크게 상승(+3.7%→+5.7% 등)하고 P/E 고평가 매도 신호는 완전히 반전됨(아래 참조).</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+5.7%</td><td class="ev" style="text-align:right">+8.2%</td><td class="ev" style="text-align:right">+7.8%</td></tr>
        <tr><td class="so">★ P/OP · P/S · P/E 모두 저평가</td><td class="num">1%</td><td class="ev" style="text-align:right"><strong>+53.6%</strong></td><td class="ev" style="text-align:right"><strong>+50.1%</strong></td><td class="ev" style="text-align:right"><strong>+22.4%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote">납품 지연·계약 취소 시 시장 과매도 구간 포착(AXON은 이 신호를 만족한 이력 없어 수치 불변). <strong>⚠ n=4 소표본</strong>(GE·TXT 위주) — 24m엔 절반 가까이 되돌림 — 12~18m 내 회수 권장.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, aerospace_defense 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+0.8%</td><td class="dim" style="text-align:right">+2.4%</td><td class="dim" style="text-align:right">+2.9%</td></tr>
        <tr><td class="sw2">▼</td><td>P/FCF 고평가</td><td class="num">24.0%</td><td class="sw2" style="text-align:right">−0.8%</td><td class="sw" style="text-align:right">−2.1%</td><td class="sw" style="text-align:right">−2.8%</td></tr>
        <tr><td class="dim">—</td><td>P/E 고평가 — 매도 신호 아님, 대조군</td><td class="dim" style="text-align:right">10.9%</td><td class="dim" style="text-align:right">+2.1%</td><td class="dim" style="text-align:right">+3.0%</td><td class="dim" style="text-align:right">+5.1%</td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>P/E 고평가 신호가 완전히 반전됨:</strong> 원래 약한 매도 신호(9m −0.6%p)였는데 AXON 편입 후 오히려 9m +2.2%p 아웃퍼폼으로 뒤집힘 — AXON이 "역사적 평균 대비 고평가"로 잡히는 구간에서도 계속 상승했기 때문(소표본 n=45, AXON 비중 영향 큼). P/FCF 고평가는 여전히 유효한 매도 신호(9m −5.7%p).</p>
    <p class="lguide"><strong>종합:</strong> 3중 저평가 신호가 뜨면 매수 매력은 크지만 n=4로 신뢰하기 어려워 12~18개월 내 회수 우선. 매도는 <strong>P/FCF 고평가만 신뢰</strong> — P/E 고평가는 AXON 편입 후 신호로서 폐기, 보조 참고도 하지 말 것.</p>

    <div class="lind">▹ leisure — 소비자 여행·숙박 사이클</div>
    <p class="lnote" style="margin-bottom:8px">2026-07-02 감사에서 GICS 산업 매칭 후보 없음 확인 — 11종목 그대로 유지, 수치 변화 없음. <strong>⚠ 생존편향 원복 후 결론이 반대로 뒤집힌 업종</strong>(카지노·크루즈 6종목 재편입 — 상세는 STATUS.md).</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="sw" style="text-align:right">−2.0%</td><td class="sw" style="text-align:right">−3.7%</td><td class="sw" style="text-align:right">−5.4%</td></tr>
        <tr><td class="so">★ val저평가 단독</td><td class="num">2%</td><td class="ev" style="text-align:right"><strong>+5.3%</strong></td><td class="ev" style="text-align:right"><strong>+17.1%</strong></td><td class="ev" style="text-align:right">+2.7%</td></tr>
        <tr><td class="sw">★★ val저평가 + CAPEX 확대 + 영업흑자</td><td class="num">4%</td><td class="sw" style="text-align:right">−6.4%</td><td class="sw" style="text-align:right">−6.9%</td><td class="sw" style="text-align:right">−27.3% ⚠</td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>신호 우선순위가 뒤바뀜:</strong> ★단독(저평가만)이 베이스 대비 12m +7.3%p, 18m +20.8%p로 견고한 반면, 기존에 "강한" 신호로 봤던 ★★(CAPEX확대+영업흑자 추가)는 오히려 베이스보다 못하고 24m엔 −27.3%까지 악화.<br>
    <strong>원인:</strong> ★★는 LVS·WYNN 등 카지노주가 마카오 규제·수요 붕괴 국면에서 "저평가+CAPEX확대(신규 리조트 투자 지속)"를 동시 충족했던 경우가 다수 — 반등 없이 손실만 키운 전형적 가치함정.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, leisure 전체 중앙값</td><td class="num">100%</td><td class="sw2" style="text-align:right">−0.2%</td><td class="sw" style="text-align:right">−1.2%</td><td class="sw" style="text-align:right">−1.4%</td></tr>
        <tr><td class="sw">▼</td><td>P/S 고평가</td><td class="num">18.8%</td><td class="sw" style="text-align:right">−1.9%</td><td class="sw" style="text-align:right">−2.9%</td><td class="sw" style="text-align:right">−5.9%</td></tr>
      </tbody>
    </table>
    <p class="lnote">P/S 고평가가 9m 기준 베이스 대비 −4.5%p — 베이스 자체가 이미 마이너스인데 고평가면 한층 더 나쁨.</p>
    <p class="lguide"><strong>종합(수정):</strong> leisure는 <strong>매수 매력이 없는 업종으로 재분류.</strong> 베이스 자체가 마이너스고, ★★ 조합은 가치함정으로 확인돼 신호로서 폐기 — 저평가 단독(★)만 제한적으로 참고할 만함. 보유 중이면 P/S 고평가 종목부터 우선 매도, 신규 진입은 비중 축소 권장.</p>

    <div class="lind">▹ retail — 소비자 임의지출 사이클</div>
    <p class="lnote" style="margin-bottom:8px"><strong>2026-07-02 갱신:</strong> LULU·AMZN·DASH·EBAY·TJX·ROST·CASY·TSCO 편입(9→17종목, GICS Consumer Cyclical 동일 섹터). 베이스가 전 구간 플러스로 전환(예: 12m −1.3%→+1.4%)되고, ★/★★ 신호는 표본이 커지며 극단값이 줄어 더 신뢰할 만한 수준으로 완화됨.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+1.4%</td><td class="ev" style="text-align:right">+5.0%</td><td class="ev" style="text-align:right">+6.0%</td></tr>
        <tr><td class="so">★ val저평가 (P/OP · P/E · P/FCF)</td><td class="num">4%</td><td class="ev" style="text-align:right">+10.6%</td><td class="ev" style="text-align:right">+33.5%</td><td class="ev" style="text-align:right">+49.8%</td></tr>
        <tr><td class="ss">★★ val저평가 + CAPEX 확대 + 영업흑자</td><td class="num">5%</td><td class="ev" style="text-align:right"><strong>+13.8%</strong></td><td class="ev" style="text-align:right"><strong>+15.3%</strong></td><td class="ev" style="text-align:right"><strong>+30.9%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote">베이스가 전 구간 플러스로 전환된 상태에서도 ★★ 신호가 베이스 대비 12m +12.4%p·18m +10.3%p·24m +24.9%p로 여전히 견고 — 재고 투자 재개(CAPEX 확대)가 수요 회복 신호라는 결론 유지. 예전(+25.4%/+30.4%/+56.1%)보다 절대값은 낮아졌지만 표본이 3배 가까이 커져(n=46) 신뢰도는 오히려 상승.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, retail 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+0.2%</td><td class="dim" style="text-align:right">+1.1%</td><td class="dim" style="text-align:right">+1.2%</td></tr>
        <tr><td class="dim">—</td><td>밸류 고평가 — 매도 신호 아님, 대조군</td><td class="dim" style="text-align:right">20.7%</td><td class="dim" style="text-align:right">+0.5%</td><td class="dim" style="text-align:right">+1.3%</td><td class="dim" style="text-align:right">+1.9%</td></tr>
        <tr><td class="sw2">▼</td><td>rev가속+PE고평가+FCF↓</td><td class="num">7.0%</td><td class="sw2" style="text-align:right">−0.6%</td><td class="sw" style="text-align:right">−2.3%</td><td class="sw2" style="text-align:right">−0.8%</td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>고평가 단독은 여전히 매도 근거 없음</strong>(오히려 베이스보다 높음) — 편입 후에도 결론 동일. 다만 전업종 공통 신호(rev가속+PE고평가+FCF↓)는 6m −3.4%p로 새로 유의미해짐.</p>
    <p class="lguide"><strong>종합:</strong> retail은 <strong>매수 신호 위주로만 판단</strong>하는 업종 — 이 결론은 유니버스 확장 후에도 유지됨. ★★(저평가+CAPEX확대+흑자) 조합이 최적 매수 타이밍이고, 고평가 단독으로 파는 근거는 없으나 rev가속+PE고평가+FCF↓ 조합이 뜨면 청산 고려.</p>

    <div class="lind bad">▹ transport — 매수 회피 업종</div>
    <p class="lnote" style="margin-bottom:8px">2026-07-02 갱신: EXPD 편입(11→12종목) — 베이스·신호 모두 사실상 변화 없음, 여전히 구조적 열위 업종.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬 — 신호 없음</div>
    <p class="lnote">베이스 12m −2.2%, 18m −2.4%, 24m −4.7% — 중앙값 기준 베이스 자체가 마이너스, 업종 전체가 구조적으로 SPY 대비 열위. 공통 매수 신호 없음.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, transport 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+0.2%</td><td class="dim" style="text-align:right">−0.4%</td><td class="dim" style="text-align:right">−0.6%</td></tr>
        <tr><td class="sw2">▼</td><td>P/FCF 고평가 (약한 신호)</td><td class="num">15.4%</td><td class="dim" style="text-align:right">−0.3%</td><td class="sw2" style="text-align:right">−0.6%</td><td class="dim" style="text-align:right">−0.6%</td></tr>
      </tbody>
    </table>
    <p class="lnote">베이스 자체가 이미 마이너스라 P/FCF 고평가의 추가 변별력은 약함(9m 기준 거의 동일) — 사실상 "언제 사도 별로인 업종".</p>
    <p class="lguide"><strong>종합:</strong> 저평가 신호가 없고 베이스 자체가 마이너스라 매수 신호를 기다릴 필요 없이 애초에 비중을 낮게 가져가는 게 낫다. 보유 중이라면 P/FCF 고평가 종목부터 우선 정리.</p>

    <div class="lind">▹ auto — 완성차·부품·중고차 사이클</div>
    <p class="lnote" style="margin-bottom:8px"><strong>2026-07-02 대폭 갱신:</strong> CVNA·ORLY·AZO·GPC 편입(4→8종목, GICS Consumer Cyclical 동일 섹터 — "부품 리테일은 방어적"이라는 서사로 뺐던 게 오류로 확인). 완성차(GM/F/TSLA) 4종목뿐이던 예전엔 베이스가 전 구간 뚜렷한 마이너스(−7.4%~−7.8%)였는데, 부품 리테일·중고차를 더하니 베이스가 거의 중립(+1.0%~−1.9%)으로 완전히 바뀜 — <strong>더 이상 일괄 매수 회피 업종이 아님.</strong></p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="ev" style="text-align:right">+1.0%</td><td class="dim" style="text-align:right">+0.7%</td><td class="sw2" style="text-align:right">−1.9%</td></tr>
        <tr><td class="so">★ CAPEX 1y삭감</td><td class="num">32%</td><td class="ev" style="text-align:right"><strong>+7.3%</strong></td><td class="ev" style="text-align:right"><strong>+10.6%</strong></td><td class="ev" style="text-align:right"><strong>+9.4%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>2026-07-02 신규 채택:</strong> CAPEX를 줄이는 시점 = 설비투자 사이클 저점 통과 신호(energy와 동일 로직). 표본이 커서(n=140) 신뢰도 높음 — 베이스 대비 12m +6.4%p, 18m +9.9%p, 24m +11.3%p로 격차가 오히려 확대. 3중 저평가 조합은 표본이 너무 작아(n=3~20) 채택하지 않음.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, auto 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">+0.7%</td><td class="dim" style="text-align:right">−0.2%</td><td class="dim" style="text-align:right">−0.7%</td></tr>
        <tr><td class="sw">▼▼</td><td>P/OP 고평가</td><td class="num">20.5%</td><td class="sw2" style="text-align:right">−1.2%</td><td class="sw" style="text-align:right">−3.8%</td><td class="sw" style="text-align:right">−4.9%</td></tr>
        <tr><td class="dim">—</td><td>P/E 고평가 — 매도 신호 아님, 대조군</td><td class="dim" style="text-align:right">4.7%</td><td class="dim" style="text-align:right">+3.1%</td><td class="dim" style="text-align:right">+7.9%</td><td class="dim" style="text-align:right">+8.0%</td></tr>
        <tr><td class="sw">▼▼</td><td>rev가속+PE고평가+FCF↓</td><td class="num">5.8%</td><td class="sw" style="text-align:right">−5.0%</td><td class="sw" style="text-align:right">−9.5%</td><td class="sw" style="text-align:right">−6.7%</td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>P/E 고평가 신호도 완전히 반전됨</strong>(예전 9m −4.2%p 약한 매도 신호 → 지금 9m +8.7%p 아웃퍼폼) — ORLY·AZO 같은 꾸준한 컴파운더가 "고평가" 구간에서도 계속 올랐기 때문(빈도도 31%→4.7%로 급감, 대부분 희석). P/OP 고평가와 전업종 공통 신호(rev가속+PE고평가+FCF↓)는 여전히 강한 매도 신호로 유효 — 특히 후자가 9m −6.0%p로 auto 최강 매도 신호.</p>
    <p class="lguide"><strong>종합:</strong> auto는 이제 <strong>CAPEX 삭감(저점)에 사고 P/OP 고평가나 rev가속+PE고평가+FCF↓(과열)에 파는 사이클형 업종</strong>으로 성격이 바뀜. P/E 고평가만으론 팔지 말 것 — 컴파운더 비중이 커진 만큼 이 지표는 더 이상 유효하지 않음.</p>

    <div class="lind">▹ energy — 유가 사이클 <span class="dim">(2026-07-02 신설)</span></div>
    <p class="lnote" style="margin-bottom:8px">Oil & Gas E&P·미드스트림·정제·장비서비스·통합 21종목 전체 편입 — 원자재(유가) 가격 사이클의 전형적 업종인데 cyclical_type 자체가 없어 growth/value 자동분류로만 흘러가던 것을 발견해 신설.</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬</div>
    <table class="ltbl">
      <thead><tr><th>신호</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_12m</th><th style="text-align:right;width:90px">alpha_18m</th><th style="text-align:right;width:90px">alpha_24m</th></tr></thead>
      <tbody>
        <tr><td>베이스라인</td><td class="num">100%</td><td class="sw" style="text-align:right">−5.3%</td><td class="sw" style="text-align:right">−9.1%</td><td class="sw" style="text-align:right">−15.5%</td></tr>
        <tr><td class="so">★ CAPEX 1y삭감</td><td class="num">35%</td><td class="ev" style="text-align:right"><strong>+1.7%</strong></td><td class="ev" style="text-align:right"><strong>+1.2%</strong></td><td class="ev" style="text-align:right"><strong>+1.8%</strong></td></tr>
      </tbody>
    </table>
    <p class="lnote"><strong>대형 표본(n=388) 매수 신호:</strong> 시추·개발 투자를 줄이는 시점이 유가 사이클 저점과 겹침 — 절대 수익률은 낮지만(+1~2%) 베이스가 워낙 깊은 마이너스라 격차는 12m +7.0%p, 18m +10.3%p, 24m +17.3%p로 지속 확대. 밸류에이션 기반 3중 저평가 조합(n=13~20)은 더 강하지만(24m +29~49%) 표본이 작아 참고만.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬 — 신호 없음</div>
    <p class="lnote">고평가 필터(P/E·P/S·P/OP·P/FCF)를 테스트했으나 <strong>매도 신호로서 유효하지 않음</strong> — 오히려 P/E 고평가군이 베이스보다 9m +3.7%p 아웃퍼폼(freq 18.6%). 밸류에이션이 비싸 보이는 구간이 실제로는 유가 상승 사이클 초입인 경우가 많아 "고평가=매도"가 성립하지 않는 것으로 추정.</p>
    <p class="lguide"><strong>종합:</strong> 사이클 버킷 중 <strong>구조적으로 가장 부진한 업종</strong>(보유 기간이 길수록 SPY 대비 열위 확대)이지만, CAPEX 삭감 시점에는 표본 큰 매수 근거가 있음. 매도는 밸류에이션 대신 유가·업황 자체를 봐야 함 — 이 패널의 팩터로는 매도 타이밍을 못 잡음.</p>

    <div class="lind bad">▹ materials — 원자재 가격 사이클 <span class="dim">(2026-07-02 신설)</span></div>
    <p class="lnote" style="margin-bottom:8px">비료(MOS/CTVA/CF)·화학(DOW/ALB/IFF/DD/LYB/LIN/APD/ECL/SHW/PPG)·구리(FCX)·금(NEM)·철강(NUE/STLD) 17종목 편입 — energy와 같은 이유로 신설. 건설자재 MLM/VMC/CRH는 construction에 이미 있어 중복 등재하지 않음(비배타적 버킷이지만 코드가 종목당 cyclical_type 1개만 저장).</p>
    <div class="lgrp-h" style="margin-top:6px">매수 시뮬 — 신호 없음</div>
    <p class="lnote">베이스라인 12m −4.0%, 18m −8.0%, 24m −9.8%. 3중 저평가 조합을 테스트했으나 <strong>오히려 베이스보다 더 나쁨</strong>(12m 갭 −10%p 이상) — "싸다"가 아니라 가치함정에 가까움. CAPEX 삭감(energy·auto에서 통했던 로직)도 여기선 효과 없음(갭 거의 0). 현재까지 유의미한 매수 신호 없음.</p>
    <div class="lgrp-h" style="margin-top:10px">매도 시뮬</div>
    <table class="ltbl">
      <thead><tr><th style="width:36px">신호</th><th>조건</th><th style="text-align:right;width:55px">빈도</th><th style="text-align:right;width:90px">alpha_3m</th><th style="text-align:right;width:90px">alpha_6m</th><th style="text-align:right;width:90px">alpha_9m</th></tr></thead>
      <tbody>
        <tr><td class="dim">—</td><td>베이스 — 신호 없음, materials 전체 중앙값</td><td class="num">100%</td><td class="dim" style="text-align:right">−1.0%</td><td class="sw2" style="text-align:right">−2.0%</td><td class="sw2" style="text-align:right">−3.4%</td></tr>
        <tr><td class="sw2">▼</td><td>rev↓+PE고평가</td><td class="num">11.9%</td><td class="sw2" style="text-align:right">−2.1%</td><td class="sw" style="text-align:right">−3.6%</td><td class="sw" style="text-align:right">−5.7%</td></tr>
      </tbody>
    </table>
    <p class="lnote">rev↓+PE고평가 조합이 9m 기준 베이스 대비 −2.4%p — 강하진 않지만 표본이 크고(n=111) 방향이 일관됨. 개별 고평가 팩터 단독으로는 변별력 없음.</p>
    <p class="lguide"><strong>종합:</strong> energy와 유사하게 <strong>구조적으로 부진한 업종</strong>이며, 여기선 매수 신호를 아직 못 찾음(저평가가 오히려 가치함정). 매도는 rev↓+PE고평가 조합을 참고 신호로 활용.</p>
  </div><!-- /lsec Cyclical -->

</div><!-- /logic -->

<script>
const STOCKS = __STOCKS_JSON__;

let sCol = 'mktcap_m', sDir = -1;
let fBucket = 'all', fSig = 'any', fSell = 'all', fTicker = '';
let expanded = null;

function toggleLogic() {
  const panel = document.getElementById('logic');
  const wrap  = document.querySelector('.tbl-wrap');
  const ctrl  = document.querySelector('.ctrl');
  const btn   = document.getElementById('btn-logic');
  const show  = panel.style.display !== 'block';
  panel.style.display = show ? 'block' : 'none';
  wrap.style.display  = show ? 'none'  : '';
  ctrl.style.opacity  = show ? '0.4'   : '';
  btn.classList.toggle('on', show);
}

function fmt(v, d) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  if (d === 0) return Math.round(n).toLocaleString('en-US');
  return n.toFixed(d !== undefined ? d : 1);
}

function fmtPct(v, d) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(d !== undefined ? d : 1) + '%';
}

function pcls(v) {
  if (v === null || v === undefined) return '';
  return Number(v) >= 0 ? 'pos' : 'neg';
}

function uvCls(v) {
  if (!v || v === '—') return '';
  if (v.startsWith('저평가')) return 'pos';
  if (v.startsWith('고평가')) return 'neg';
  return '';
}

function sigRank(s) {
  if (s.includes('▲'))  return 3;
  if (s.includes('★★')) return 3;
  if (s.includes('★'))  return 2;
  if (s.includes('○'))  return 1;
  if (s.includes('✗'))  return -1;
  return 0;
}
function sellCls(v) {
  if (!v || v === '—') return '';
  return 'sw';
}

function getPrimary(bucket) {
  const lbls = bucket.split(',');
  if (lbls.some(l => l.startsWith('cyclical'))) return 'cyclical';
  if (lbls.includes('growth'))                   return 'growth';
  if (lbls.includes('value'))                    return 'value';
  return 'unclassified';
}
function getFiltered() {
  return STOCKS.filter(s => {
    if (fBucket !== 'all') {
      const lbls = s.bucket.split(',');
      const hit = fBucket === 'cyclical'
        ? lbls.some(l => l.startsWith('cyclical'))
        : lbls.includes(fBucket);
      if (!hit) return false;
    }
    if (fSig === 'any' && s.signal === '—') return false;
    if (fSell === 'any' && s.sell_sig === '—') return false;
    if (fTicker && !s.ticker.toLowerCase().includes(fTicker.toLowerCase())) return false;
    return true;
  }).sort((a, b) => {
    let av = sCol === 'signal' ? sigRank(a.signal) : a[sCol];
    let bv = sCol === 'signal' ? sigRank(b.signal) : b[sCol];
    if (typeof av === 'string' && typeof bv === 'string') {
      return av.localeCompare(bv) * sDir;
    }
    if (av === null || av === undefined) av = -Infinity;
    if (bv === null || bv === undefined) bv = -Infinity;
    return (av < bv ? -1 : av > bv ? 1 : 0) * sDir;
  });
}

function buildDetail(s) {
  const r = (lbl, val) =>
    `<div class="drow"><span class="dl">${lbl}</span><span class="dv">${val}</span></div>`;

  const bktFull = s.bucket + (s.cyclical_type ? '/' + s.cyclical_type : '');

  const gHdr = `<div class="gr-hdr"><div></div><div style="text-align:right">1y</div><div style="text-align:right">2y</div><div style="text-align:right">4y</div></div>`;
  const gRow = (lbl, y1, y2, y4) =>
    `<div class="gr-row">
      <div class="gr-lbl">${lbl}</div>
      <div class="gr-v ${pcls(y1)}">${fmtPct(y1)}</div>
      <div class="gr-v ${pcls(y2)}">${fmtPct(y2)}</div>
      <div class="gr-v ${pcls(y4)}">${fmtPct(y4)}</div>
    </div>`;

  return `<div class="dp">
    <div class="ds">
      <div class="dh">기본 정보</div>
      ${r('Ticker', '<strong>' + s.ticker + '</strong>')}
      ${r('회사명', s.company)}
      ${s.biz_model ? r('사업 개요', '<span style="white-space:normal;line-height:1.5">' + s.biz_model + '</span>') : ''}
      ${r('버킷', bktFull)}
      ${r('앵커', s.anchor_term)}
      ${r('현재가 ($)', fmt(s.price, 2))}
      ${s.val_asof ? r('밸류에이션 기준일', s.val_asof) : ''}
      ${r('시총 ($M)', fmt(s.mktcap_m, 0))}
      ${r('이익 추세', s.op_trend)}
      ${r('저평가 여부', s.undervalued)}
      ${s.sig_detail.length
          ? s.sig_detail.map(d => r('매수(' + d.b + ')', d.txt)).join('')
          : r('매수 신호', '—')}
      ${s.sell_detail.length
          ? s.sell_detail.map(d => r('매도(' + d.b + ')', '<span class="' + sellCls(d.txt) + '">' + d.txt + '</span>')).join('')
          : r('매도 신호', '—')}
    </div>
    <div class="ds">
      <div class="dh">밸류에이션 — 현재 / 20d / 4y 평균</div>
      ${r('P/E',   fmt(s.pe_now,   1) + ' / ' + fmt(s.pe_20d,   1) + ' / ' + fmt(s.pe_4y,   1))}
      ${r('P/S',   fmt(s.ps_now,   2) + ' / ' + fmt(s.ps_20d,   2) + ' / ' + fmt(s.ps_4y,   2))}
      ${r('P/OP',  fmt(s.pop_now,  1) + ' / ' + fmt(s.pop_20d,  1) + ' / ' + fmt(s.pop_4y,  1))}
      ${r('P/FCF', fmt(s.pfcf_now, 1) + ' / ' + fmt(s.pfcf_20d, 1) + ' / ' + fmt(s.pfcf_4y, 1))}
      <div class="dh2">TTM 재무 (주당, $)</div>
      ${r('매출',    fmt(s.rev_ps, 2))}
      ${r('영업이익', fmt(s.op_ps,  2))}
      ${r('순이익',  fmt(s.ni_ps,  2))}
      ${r('CFO',    fmt(s.cfo_ps, 2))}
      ${r('FCF',    fmt(s.fcf_ps, 2))}
    </div>
    <div class="ds">
      <div class="dh">성장률 CAGR — 연환산 (%)</div>
      ${gHdr}
      ${gRow('매출',    s.rev_1y,   s.rev_2y,   s.rev_4y)}
      ${gRow('영업이익', s.op_1y,   s.op_2y,   s.op_4y)}
      ${gRow('순이익',  s.ni_1y,   s.ni_2y,   s.ni_4y)}
      ${gRow('FCF',    s.fcf_1y,  s.fcf_2y,  s.fcf_4y)}
      ${gRow('CAPEX',  s.capex_1y, s.capex_2y, s.capex_4y)}
      <div class="dh2">주가 수익률</div>
      ${r('1w', '<span class="' + pcls(s.ret_1w) + '">' + fmtPct(s.ret_1w) + '</span>')}
      ${r('1m', '<span class="' + pcls(s.ret_1m) + '">' + fmtPct(s.ret_1m) + '</span>')}
      ${r('3m', '<span class="' + pcls(s.ret_3m) + '">' + fmtPct(s.ret_3m) + '</span>')}
      ${r('1y', '<span class="' + pcls(s.ret_1y) + '">' + fmtPct(s.ret_1y) + '</span>')}
    </div>
  </div>`;
}

function renderTable() {
  const stocks = getFiltered();
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';

  stocks.forEach((s, idx) => {
    const pri  = getPrimary(s.bucket);
    const bCls = pri === 'growth' ? 'bg' : pri === 'cyclical' ? 'bc'
               : pri === 'value'  ? 'bv' : 'bu';
    const sCls = (s.signal.includes('▲') || s.signal.includes('★★')) ? 'ss'
               : (s.signal.includes('★') || s.signal.includes('○')) ? 'so'
               : s.signal.includes('✗') ? 'sw' : '';
    const bktLbl = s.bucket;

    const rc = v => `<span class="${pcls(v)}">${fmtPct(v)}</span>`;

    const tr = document.createElement('tr');
    tr.className = idx % 2 === 1 ? 'sr alt' : 'sr';
    tr.dataset.ticker = s.ticker;
    tr.onclick = () => toggle(s.ticker);
    tr.innerHTML =
      `<td class="rk">${idx + 1}</td>` +
      `<td class="tk">${s.ticker}</td>` +
      `<td class="co">${s.company}</td>` +
      `<td class="${bCls}">${bktLbl}</td>` +
      `<td class="num">${fmt(s.mktcap_m, 0)}</td>` +
      `<td class="num">${fmt(s.price, 2)}</td>` +
      `<td class="num">${fmt(s.pe_20d, 1)}</td>` +
      `<td class="num">${fmt(s.pe_4y, 1)}</td>` +
      `<td class="sep">${s.op_trend}</td>` +
      `<td class="${uvCls(s.undervalued)}">${s.undervalued}</td>` +
      `<td class="${sCls}">${s.signal}</td>` +
      `<td class="${sellCls(s.sell_sig)}">${s.sell_sig}</td>` +
      `<td class="num">${rc(s.ret_1w)}</td>` +
      `<td class="num">${rc(s.ret_1m)}</td>` +
      `<td class="num">${rc(s.ret_3m)}</td>` +
      `<td class="num">${rc(s.ret_1y)}</td>`;
    tbody.appendChild(tr);

    const dr = document.createElement('tr');
    dr.id = 'dr-' + s.ticker;
    dr.className = 'dr';
    dr.innerHTML = `<td colspan="16">${buildDetail(s)}</td>`;
    tbody.appendChild(dr);
  });

  if (expanded) {
    const el = document.getElementById('dr-' + expanded);
    if (el) {
      el.style.display = 'table-row';
      el.previousElementSibling.classList.add('open');
    } else {
      expanded = null;
    }
  }

  document.getElementById('cnt').textContent = stocks.length + '종목';

  document.querySelectorAll('th[data-col]').forEach(th => {
    th.classList.remove('asc', 'desc');
    if (th.dataset.col === sCol) th.classList.add(sDir === 1 ? 'asc' : 'desc');
  });
}

function toggle(ticker) {
  if (expanded === ticker) {
    const el = document.getElementById('dr-' + ticker);
    if (el) { el.style.display = 'none'; el.previousElementSibling.classList.remove('open'); }
    expanded = null;
    return;
  }
  if (expanded) {
    const prev = document.getElementById('dr-' + expanded);
    if (prev) { prev.style.display = 'none'; prev.previousElementSibling.classList.remove('open'); }
  }
  const el = document.getElementById('dr-' + ticker);
  if (el) { el.style.display = 'table-row'; el.previousElementSibling.classList.add('open'); }
  expanded = ticker;
}

// 이벤트 바인딩
document.querySelectorAll('.btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const f = btn.dataset.f, v = btn.dataset.v;
    document.querySelectorAll(`.btn[data-f="${f}"]`).forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    if (f === 'bucket') fBucket = v;
    else if (f === 'sig')  fSig  = v;
    else if (f === 'sell') fSell = v;
    renderTable();
  });
});

document.getElementById('search').addEventListener('input', e => {
  fTicker = e.target.value.trim();
  renderTable();
});

document.querySelectorAll('th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (col === '__rank__') return;
    if (sCol === col) {
      sDir *= -1;
    } else {
      sCol = col;
      sDir = ['ticker', 'bucket', 'anchor_term', 'op_trend', 'signal'].includes(col) ? 1 : -1;
    }
    renderTable();
  });
});

renderTable();
</script>
</body>
</html>
"""


def generate_html(stocks: list[dict], price_date: str) -> str:
    data_json = json.dumps(stocks, ensure_ascii=False, separators=(',', ':'))
    return (
        HTML_TEMPLATE
        .replace('__STOCKS_JSON__', data_json)
        .replace('__PRICE_DATE__', price_date)
    )


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print('데이터 로딩 중…')
    snap           = load_snapshots()
    prices, px_dt  = load_current_prices()
    shares         = load_shares()
    perf           = load_price_perf()
    val_now        = load_valuation_current()

    print(f'  스냅샷 {len(snap)}행, 가격 {len(prices)}종목, 수익률 {len(perf)}종목, 현재 밸류에이션 {len(val_now)}종목')

    stocks = build_stocks(snap, prices, shares, perf, val_now)
    print(f'  최종 {len(stocks)}종목 (시총 순 정렬)')

    html = generate_html(stocks, px_dt)
    OUT.write_text(html, encoding='utf-8')
    size_kb = OUT.stat().st_size / 1024
    print(f'→ {OUT.relative_to(ROOT)} 저장 완료 ({size_kb:.0f} KB)')


if __name__ == '__main__':
    main()
