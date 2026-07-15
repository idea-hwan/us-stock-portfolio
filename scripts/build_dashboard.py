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


def signal_value(row) -> str:
    """PIT(16분기) 백테스트 결과 ▲ 신호만 베이스 대비 유의미 — 단일 신호로 단순화 (growth와 동일)."""
    rev2y_acc = _acc(row, 'rev_geom_2y_mcum', 'rev_geom_4y_mcum')
    pop_low   = _low(row, 'pop_20d', 'pop_4y', 0.75)
    capex_cut = _neg(row, 'capex_geom_1y_mcum')
    if rev2y_acc and pop_low and capex_cut:
        return '▲ rev2y가속+pop저평가+capex↓'
    return '—'


def get_signals(row) -> list[tuple[str, str]]:
    """매수 신호 수집 — 성장·가치.

    Cyclical 버킷은 가격→팩터 역방향 재검증 결과 반도체(MU/AMAT) 외엔 타이밍 신호로
    쓸 수 없다는 결론이 나 매수/매도 신호 자체를 폐기함. 상세: docs/cyclical_classification_summary.md
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
    """매도 신호 수집 — 성장·가치.

    Cyclical 버킷은 가격→팩터 역방향 재검증 결과 반도체(MU/AMAT) 외엔 타이밍 신호로
    쓸 수 없다는 결론이 나 매수/매도 신호 자체를 폐기함. 상세: docs/cyclical_classification_summary.md
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
.logic-wrap{display:none;max-width:920px;margin-top:4px;font-size:13px;line-height:1.6}
.lsec{margin-bottom:32px}
.lh1{font-size:14px;font-weight:700;color:var(--text);letter-spacing:.02em;
     border-bottom:1px solid var(--bord);padding-bottom:8px;margin-bottom:14px}
.lsub{color:var(--muted);font-size:12px;margin:-8px 0 14px;line-height:1.6}
.ltbl{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:0}
.ltbl th{background:var(--surf);color:var(--muted);font-weight:500;
         padding:7px 10px;border-bottom:1px solid var(--bord);text-align:left;white-space:nowrap}
.ltbl td{padding:7px 10px;border-bottom:1px solid #1e2130;vertical-align:top;line-height:1.6}
.ltbl td:first-child{white-space:nowrap}
.lnote{color:var(--muted);font-size:12px;margin-top:8px;line-height:1.7;
       border-left:2px solid var(--bord);padding-left:10px}
.lgrp{margin-bottom:20px;padding:14px 16px;background:var(--surf);border:1px solid var(--bord);border-radius:8px}
.lgrp-h{color:var(--blue);font-size:12px;font-weight:700;margin-bottom:10px;letter-spacing:.02em}
.ev{color:var(--green);font-size:12px}
.lind{color:var(--yellow);font-size:12px;font-weight:600;margin:14px 0 6px;letter-spacing:.03em}
.lind.bad{color:var(--red)}
.num{text-align:right;color:var(--muted)}
.lguide{margin-top:10px;padding:10px 12px;border-left:3px solid var(--blue);background:rgba(96,165,250,.08);border-radius:4px;font-size:12px;color:var(--text);line-height:1.7}

/* 잘 몰라도 되는 용어 설명 */
abbr.term{border-bottom:1px dotted var(--muted);text-decoration:none;cursor:help;color:inherit}

/* 인트로 4단계 흐름 */
.lflow{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:10px}
@media(max-width:760px){.lflow{grid-template-columns:1fr 1fr}}
.lstep{background:var(--surf);border:1px solid var(--bord);border-radius:8px;padding:12px 14px;position:relative}
.lstep-num{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;
           border-radius:50%;background:var(--blue);color:#0f1117;font-size:11px;font-weight:700;margin-bottom:8px}
.lstep-title{font-size:12.5px;font-weight:700;color:var(--text);margin-bottom:4px}
.lstep-body{font-size:11.5px;color:var(--muted);line-height:1.55}
.lflow-arrow{display:none}
@media(min-width:761px){
  .lstep:not(:last-child)::after{content:'→';position:absolute;right:-16px;top:50%;transform:translateY(-50%);
    color:var(--muted);font-size:14px;z-index:1}
}

/* 용어 사전 */
.gloss{display:flex;flex-wrap:wrap;gap:8px 10px;margin-bottom:6px}
.gloss-item{background:var(--surf);border:1px solid var(--bord);border-radius:6px;padding:6px 10px;font-size:11.5px}
.gloss-term{color:var(--blue);font-weight:700;margin-right:5px}
.gloss-def{color:var(--muted)}

/* 버킷/판단 라벨 카드 */
.lcard-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
@media(max-width:760px){.lcard-grid{grid-template-columns:1fr}}
.lcard{background:var(--surf);border:1px solid var(--bord);border-radius:8px;padding:12px 14px}
.lcard-h{font-size:12.5px;font-weight:700;margin-bottom:4px}
.lcard-b{font-size:11.5px;color:var(--muted);line-height:1.55}

.lbadge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;
        white-space:nowrap}
.lbadge.up2{background:rgba(52,211,153,.15);color:var(--green)}
.lbadge.up1{background:rgba(52,211,153,.1);color:#86efac}
.lbadge.dn2{background:rgba(248,113,113,.15);color:var(--red)}
.lbadge.dn1{background:rgba(248,113,113,.1);color:#fca5a5}
.lbadge.flat{background:rgba(107,114,128,.15);color:var(--muted)}
.lbadge.cheap{background:rgba(52,211,153,.15);color:var(--green)}
.lbadge.rich{background:rgba(248,113,113,.15);color:var(--red)}
.lbadge.mix{background:rgba(251,191,36,.15);color:var(--yellow)}
.lbadge.neu{background:rgba(107,114,128,.15);color:var(--muted)}

/* 조건문 — 쉬운 말 + 원래 조건식 */
.cond-plain{color:var(--text);font-size:12.5px;line-height:1.6}
.cond-tech{color:var(--muted);font-size:11px;margin-top:2px}

/* 신호 발동 빈도/카드 헤더 */
.sig-hd{display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap}
.sig-freq{color:var(--muted);font-size:11px;background:var(--bg);border:1px solid var(--bord);
          border-radius:4px;padding:1px 7px}

/* 12m/18m/24m 비교 미니 막대 (베이스 vs 신호) */
.dbar-block{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:10px 0 4px}
@media(max-width:640px){.dbar-block{grid-template-columns:1fr}}
.dbar-col{background:var(--bg);border:1px solid var(--bord);border-radius:6px;padding:8px 10px}
.dbar-h{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.dbar-track{position:relative;height:26px;margin-bottom:4px}
.dbar-mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--bord)}
.dbar{position:absolute;height:7px;border-radius:3px}
.dbar.base{top:2px;background:var(--muted);opacity:.55}
.dbar.sig{top:14px}
.dbar.pos{background:var(--green)}
.dbar.neg{background:var(--red)}
.dbar-legend{display:flex;justify-content:space-between;font-size:11px}
.dbar-legend .l-base{color:var(--muted)}
.dbar-legend .l-sig.pos{color:var(--green);font-weight:700}
.dbar-legend .l-sig.neg{color:var(--red);font-weight:700}

/* 최종 검증 스탯 타일 */
.stat-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:8px}
@media(max-width:640px){.stat-grid{grid-template-columns:1fr}}
.stat-tile{background:var(--surf);border:1px solid var(--bord);border-radius:8px;padding:14px 16px}
.stat-tile-h{font-size:12px;color:var(--muted);margin-bottom:10px}
.stat-tile-h .bg{font-weight:700}
.stat-tile-h .bv{font-weight:700}
.stat-row{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.stat-num{font-size:22px;font-weight:800;color:var(--green)}
.stat-vs{font-size:11px;color:var(--muted)}
.stat-vs strong{color:var(--text);font-weight:700}
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
    <div class="lh1">이 대시보드는 이렇게 판단합니다</div>
    <div class="lflow">
      <div class="lstep">
        <div class="lstep-num">1</div>
        <div class="lstep-title">종목을 3그룹으로 나눈다</div>
        <div class="lstep-body">실적 성격이 다른 종목을 <b>growth(성장)·value(가치)·cyclical(경기민감)</b>로 나눠 따로 비교한다.</div>
      </div>
      <div class="lstep">
        <div class="lstep-num">2</div>
        <div class="lstep-title">이익 추세 + 주가 수준을 본다</div>
        <div class="lstep-body">회사가 버는 돈(영업이익)이 늘고 있는지, 지금 주가가 이 회사의 평소 벌이 대비 싼지 비싼지를 확인한다.</div>
      </div>
      <div class="lstep">
        <div class="lstep-num">3</div>
        <div class="lstep-title">겹치는 조건을 신호로 표시</div>
        <div class="lstep-body">"이익 잘 나옴 + 주가 쌈"이 겹치면 매수(▲), "이익 줄어듦 + 주가 비쌈"이 겹치면 매도(▼) 신호를 띄운다.</div>
      </div>
      <div class="lstep">
        <div class="lstep-num">4</div>
        <div class="lstep-title">실제로 통했는지 검증</div>
        <div class="lstep-body">2013~2026년 데이터로, 이 신호대로 매매했다면 S&amp;P500 지수보다 얼마나 더/덜 벌었을지 미리 계산해봤다.</div>
      </div>
    </div>
    <p class="lsub" style="margin-top:2px">아래는 각 단계의 세부 기준과 실제 검증 결과. 낯선 용어는 아래 <b>용어 설명</b>을 참고하거나, 점선 밑줄 위에 마우스를 올리면 바로 설명이 뜬다.</p>
  </div>

  <div class="lsec">
    <div class="lh1">용어 설명</div>
    <div class="gloss">
      <span class="gloss-item"><span class="gloss-term">CAGR</span><span class="gloss-def">연평균 성장 속도 — 이익이 1년 동안 몇 %씩 늘었는지</span></span>
      <span class="gloss-item"><span class="gloss-term">alpha(초과수익)</span><span class="gloss-def">S&amp;P500 지수보다 얼마나 더(혹은 덜) 벌었는지의 차이</span></span>
      <span class="gloss-item"><span class="gloss-term">CAPEX(설비투자)</span><span class="gloss-def">공장·장비 등에 쓰는 돈 — 늘리면 미래에 배팅, 줄이면 방어적</span></span>
      <span class="gloss-item"><span class="gloss-term">P/E·P/S·P/OP·P/FCF</span><span class="gloss-def">주가가 이익·매출·영업이익·현금흐름 대비 몇 배인지 — 낮을수록 저평가</span></span>
      <span class="gloss-item"><span class="gloss-term">PIT 검증</span><span class="gloss-def">미래 정보를 미리 알고 계산한 게 아니라, 그 당시 알 수 있었던 정보만으로 재현한 백테스트</span></span>
    </div>
  </div>

  <div class="lsec">
    <div class="lh1">1단계 — 버킷 분류 기준</div>
    <div class="lcard-grid">
      <div class="lcard"><div class="lcard-h bg">growth</div><div class="lcard-b">16분기(4년) 연속 <b>영업이익 흑자</b> — 꾸준히 돈을 버는 성장주</div></div>
      <div class="lcard"><div class="lcard-h bv">value</div><div class="lcard-b">16분기(4년) 연속 <b>순이익 흑자</b> — 이익 안정성이 검증된 가치주</div></div>
      <div class="lcard"><div class="lcard-h bc">cyclical</div><div class="lcard-b">반도체·자동차·항공방산·건설·자본재·레저·리테일 등 경기 흐름에 민감한 업종. 분류용 라벨일 뿐 <b>매수/매도 신호는 없음</b></div></div>
    </div>
    <p class="lnote" style="margin-top:10px">cyclical은 가격→팩터 역방향 재검증 결과 반도체 외엔 타이밍 신호로 쓸 수 없다는 결론이 확정돼, 신호는 대시보드에서 제거했다. 개별 업종 국면 판단은 참고 문서로: <a href="https://github.com/idea-hwan/us-stock-portfolio/blob/main/docs/cyclical_classification_summary.md" target="_blank">종합분류</a> · <a href="https://github.com/idea-hwan/us-stock-portfolio/blob/main/docs/cyclical_semiconductor_analysis.md" target="_blank">반도체</a> · <a href="https://github.com/idea-hwan/us-stock-portfolio/blob/main/docs/cyclical_energy_materials_analysis.md" target="_blank">에너지·소재</a> · <a href="https://github.com/idea-hwan/us-stock-portfolio/blob/main/docs/cyclical_construction_analysis.md" target="_blank">건설</a> · <a href="https://github.com/idea-hwan/us-stock-portfolio/blob/main/docs/cyclical_leisure_retail_capital_transport_analysis.md" target="_blank">레저·리테일·자본재·항공방산·운송</a></p>
  </div>

  <div class="lsec">
    <div class="lh1">2단계 — 이익 추세 판단</div>
    <p class="lsub">영업이익 <abbr class="term" title="연평균 성장 속도 — 1년간 몇 %씩 늘었는지">CAGR</abbr> 기준. 좋은 순서대로 정렬.</p>
    <div class="lcard-grid" style="grid-template-columns:repeat(5,1fr)">
      <div class="lcard"><span class="lbadge up2">▲▲ 가속</span><div class="lcard-b" style="margin-top:8px">이익이 늘고 있고, 그 <b>속도까지 빨라지는 중</b> — 가장 좋은 신호</div></div>
      <div class="lcard"><span class="lbadge up1">▲ 성장</span><div class="lcard-b" style="margin-top:8px">최근 1년간 영업이익이 늘었다 (다만 속도는 둔화)</div></div>
      <div class="lcard"><span class="lbadge flat">— 보합</span><div class="lcard-b" style="margin-top:8px">뚜렷한 추세 없음 (데이터 부족 등)</div></div>
      <div class="lcard"><span class="lbadge dn1">▼ 1년 감소</span><div class="lcard-b" style="margin-top:8px">최근 1년간 영업이익이 줄었다</div></div>
      <div class="lcard"><span class="lbadge dn2">▼▼ 2년 감소</span><div class="lcard-b" style="margin-top:8px">최근 1년, 그 이전 1년 모두 감소 — <b>실적이 계속 나빠지는 중</b></div></div>
    </div>
    <p class="lnote">계산 방식: TTM(직전 4분기 누적) 기준으로 분기 단위 기하평균 → 연환산. "1년 CAGR"은 최근 4분기를 그 직전 4분기와 비교.</p>
  </div>

  <div class="lsec">
    <div class="lh1">2단계 — 밸류(주가 수준) 판단</div>
    <p class="lsub">지금 주가 배수(<abbr class="term" title="주가가 이익·매출·영업이익·현금흐름 대비 몇 배인지">P/E·P/S·P/OP·P/FCF</abbr>)를 최근 4년 평균과 비교.</p>
    <div class="lcard-grid">
      <div class="lcard"><span class="lbadge cheap">저평가</span><div class="lcard-b" style="margin-top:8px">지금 주가가 4년 평균보다 <b>25% 이상 싸다</b> — 살 만한 가격일 가능성 (백테스트로 찾은 최적 임계값)</div></div>
      <div class="lcard"><span class="lbadge rich">고평가</span><div class="lcard-b" style="margin-top:8px">지금 주가가 4년 평균보다 <b>25% 이상 비싸다</b></div></div>
      <div class="lcard"><span class="lbadge mix">혼재</span><div class="lcard-b" style="margin-top:8px">배수마다 판단이 엇갈림 — 일부는 싸고 일부는 비쌈</div></div>
      <div class="lcard"><span class="lbadge neu">중립</span><div class="lcard-b" style="margin-top:8px">모든 배수가 평균 대비 ±25% 이내 — 특별히 싸지도 비싸지도 않음</div></div>
    </div>
    <p class="lnote">4개 배수(P/E·P/S·P/OP·P/FCF)를 각각 독립적으로 판정한다. 예) "저평가(P/S+P/E)" = 그 두 배수만 4년 평균보다 25%+ 낮다는 뜻. 4년 평균은 과거 16분기 기하평균, 현재값은 최근 20일 평균.</p>
  </div>

  <div class="lsec">
    <p class="lnote"><b>Growth·Value 공통 방법론:</b> <abbr class="term" title="미래 정보를 미리 알고 계산한 게 아니라, 그 당시 알 수 있었던 정보만으로 재현한 백테스트">PIT(그 시점 기준) 검증</abbr> — 16분기 연속 흑자 여부를 각 시점마다 그때 기준으로 다시 판정한 유니버스(2013Q4~2026)를 사용했다. 아래 alpha는 평균이 아닌 <b>중앙값</b>, 전부 <b>S&amp;P500 대비 초과수익</b>. 방법론 상세는 STATUS.md 참조.</p>
  </div>

  <div class="lsec">
    <div class="lh1">3단계 — Growth 버킷 매수/매도 신호</div>

    <div class="lgrp">
      <div class="sig-hd"><span class="lbadge up2">▲ 매수 신호</span><span class="sig-freq">성장주 전체의 2.1%에서만 발생</span></div>
      <p class="cond-plain">최근 2년간 매출 성장 속도가 더 빨라지고 있고, 이익 대비 주가는 저평가 상태이며, 설비투자는 줄이고 있다.</p>
      <p class="cond-tech">조건식: 매출 2y CAGR &gt; 4y CAGR(가속) <em>and</em> P/OP 저평가 <em>and</em> CAPEX 1y↓</p>
      <div class="dbar-block">
        <div class="dbar-col">
          <div class="dbar-h">12개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:12.7%"></div>
            <div class="dbar sig pos" style="left:50%;width:23.6%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −1.4%</span><span class="l-sig pos">신호 있음 +2.6%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">18개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:15.5%"></div>
            <div class="dbar sig pos" style="left:50%;width:40%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −1.7%</span><span class="l-sig pos">신호 있음 +4.4%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">24개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:19.1%"></div>
            <div class="dbar sig pos" style="left:50%;width:24.5%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −2.1%</span><span class="l-sig pos">신호 있음 +2.7%</span></div>
        </div>
      </div>
      <p class="lnote">회색 막대(신호 없이 그냥 들고 있었을 때)보다 초록 막대(신호가 떴을 때)가 전 구간에서 확실히 낫다 — 격차는 12개월 +4.0%p, 18개월 +6.1%p, 24개월 +4.8%p. 이 조합(매출 가속+P/OP 저평가+CAPEX 삭감) 하나만 매수 기준으로 채택했다.</p>
    </div>

    <div class="lgrp">
      <div class="sig-hd"><span class="lbadge dn2">▼ 매도 신호</span><span class="sig-freq">성장주 전체의 4.7%에서 발생</span></div>
      <p class="cond-plain">매출이 줄어드는데, 주가는 여전히 비싸고(고평가) 설비투자 부담까지 늘고 있다.</p>
      <p class="cond-tech">조건식: 매출↓ <em>and</em> (P/OP고평가+CAPEX↑ <em>or</em> P/FCF고평가+CAPEX가속)</p>
      <div class="dbar-block">
        <div class="dbar-col">
          <div class="dbar-h">3개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:1.8%"></div>
            <div class="dbar sig neg" style="right:50%;width:16.4%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −0.2%</span><span class="l-sig neg">신호 있음 −1.8%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">6개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:5.5%"></div>
            <div class="dbar sig neg" style="right:50%;width:29.1%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −0.6%</span><span class="l-sig neg">신호 있음 −3.2%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">9개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:10%"></div>
            <div class="dbar sig neg" style="right:50%;width:46.4%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −1.1%</span><span class="l-sig neg">신호 있음 −5.1%</span></div>
        </div>
      </div>
      <p class="lnote">빨간 막대가 회색 막대보다 훨씬 길다 — 이 신호가 뜨면 그냥 들고 있는 것보다 손실이 더 크게 난다는 뜻(9개월 기준 격차 −4.0%p). 매출 역성장에 고평가+CAPEX 부담이 겹칠 때 발동한다.</p>
    </div>
  </div><!-- /lsec Growth -->

  <div class="lsec">
    <div class="lh1">3단계 — Value 버킷 매수/매도 신호</div>

    <div class="lgrp">
      <div class="sig-hd"><span class="lbadge up2">▲ 매수 신호</span><span class="sig-freq">가치주 전체의 1.8%에서만 발생</span></div>
      <p class="cond-plain">최근 2년간 매출 성장 속도가 더 빨라지고 있고, 이익 대비 주가는 저평가 상태이며, 설비투자는 줄이고 있다. (Growth와 동일 조건)</p>
      <p class="cond-tech">조건식: 매출 2y CAGR 가속 <em>and</em> P/OP 저평가 <em>and</em> CAPEX 1y↓</p>
      <div class="dbar-block">
        <div class="dbar-col">
          <div class="dbar-h">12개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:10.9%"></div>
            <div class="dbar sig pos" style="left:50%;width:71.8%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −1.2%</span><span class="l-sig pos">신호 있음 +7.9%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">18개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:13.6%"></div>
            <div class="dbar sig pos" style="left:50%;width:93.6%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −1.5%</span><span class="l-sig pos">신호 있음 +10.3%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">24개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:16.4%"></div>
            <div class="dbar sig pos" style="left:50%;width:67.3%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −1.8%</span><span class="l-sig pos">신호 있음 +7.4%</span></div>
        </div>
      </div>
      <p class="lnote"><b>Growth보다 더 강한 신호:</b> 격차가 12개월 +9.1%p, 18개월 +11.8%p, 24개월 +9.2%p로, 전 구간에서 오히려 더 뚜렷하다. 매수 신호는 이 조합 하나로 단순화했다.</p>
    </div>

    <div class="lgrp">
      <div class="sig-hd"><span class="lbadge dn2">▼ 매도 신호</span><span class="sig-freq">가치주 전체의 4.7%에서 발생</span></div>
      <p class="cond-plain">매출이 줄어드는데, 주가는 여전히 비싸고(고평가) 설비투자 부담까지 늘고 있다. (Growth와 동일 조건)</p>
      <p class="cond-tech">조건식: 매출↓ <em>and</em> (P/OP고평가+CAPEX↑ <em>or</em> P/FCF고평가+CAPEX가속)</p>
      <div class="dbar-block">
        <div class="dbar-col">
          <div class="dbar-h">3개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:1.8%"></div>
            <div class="dbar sig neg" style="right:50%;width:17.3%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −0.2%</span><span class="l-sig neg">신호 있음 −1.9%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">6개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:4.5%"></div>
            <div class="dbar sig neg" style="right:50%;width:29.1%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −0.5%</span><span class="l-sig neg">신호 있음 −3.2%</span></div>
        </div>
        <div class="dbar-col">
          <div class="dbar-h">9개월 후</div>
          <div class="dbar-track"><div class="dbar-mid"></div>
            <div class="dbar base" style="right:50%;width:8.2%"></div>
            <div class="dbar sig neg" style="right:50%;width:46.4%"></div>
          </div>
          <div class="dbar-legend"><span class="l-base">신호 없음 −0.9%</span><span class="l-sig neg">신호 있음 −5.1%</span></div>
        </div>
      </div>
      <p class="lnote">Growth와 동일 조건인데, 가치 버킷에서도 똑같이 유효함을 확인했다 (9개월 기준 격차 −4.2%p로 Growth보다 소폭 더 강함).</p>
    </div>
  </div><!-- /lsec Value -->

  <div class="lsec">
    <div class="lh1">4단계 — 실제로 매매했다면? (동적 포트폴리오 검증)</div>
    <p class="lsub" style="margin-bottom:10px">위 막대그래프는 "신호가 떴을 때 한 번 사서 계속 들고 있었다면"의 결과다. 실제로 <b>10슬롯 포트폴리오</b>(최소 12개월·최대 18개월 보유, ▲가 뜨면 매수·▼가 뜨면 즉시 매도, 신호 없이 12개월 넘은 것 중 가장 오래된 것부터 교체)를 이 신호로 계속 회전매매했다면 어떤 결과가 나왔는지 별도 시뮬로 검증했다.</p>
    <div class="stat-grid">
      <div class="stat-tile">
        <div class="stat-tile-h"><span class="bg">growth</span> 버킷 · 12.5년 (2013.12 ~ 2026.07)</div>
        <div class="stat-row">
          <span class="stat-num">+26.69%</span>
          <span class="stat-vs">연평균 수익률 · S&amp;P500 <strong>+14.05%</strong> 대비 <strong>+12.63%p</strong> 초과 · 누적 총수익률 <strong>+1843.2%</strong></span>
        </div>
      </div>
      <div class="stat-tile">
        <div class="stat-tile-h"><span class="bv">value</span> 버킷 · 12.5년 (2013.12 ~ 2026.07)</div>
        <div class="stat-row">
          <span class="stat-num">+25.53%</span>
          <span class="stat-vs">연평균 수익률 · S&amp;P500 <strong>+14.05%</strong> 대비 <strong>+11.48%p</strong> 초과 · 누적 총수익률 <strong>+1632.1%</strong></span>
        </div>
      </div>
    </div>
    <p class="lguide"><b>종합:</b> 정적 시뮬의 신호를 실제 회전매매에 그대로 적용해도 growth·value 둘 다 S&amp;P500 대비 확실한 초과수익을 유지한다. 다만 유니버스 자체가 오늘 기준 생존 종목 위주로 구성돼 있어(인수합병·상장폐지 종목 누락) 절대 수익률은 과장돼 있을 가능성이 있다 — 방법론 상세는 STATUS.md 참조.</p>
  </div><!-- /lsec 동적시뮬 -->

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
