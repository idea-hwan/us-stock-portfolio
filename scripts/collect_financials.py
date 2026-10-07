"""
전체 유니버스 분기 재무 데이터 수집 → SQLite 저장
실행: python scripts/collect_financials.py
분기마다 실행 → upsert (있으면 갱신, 없으면 삽입)
"""

import sqlite3
import time
import requests
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'
DB_PATH  = DATA_DIR / 'stocks.db'
from config import sec_headers, sec_get
from edgar_xbrl_fallback import patch_missing_filings
HEADERS  = sec_headers()
CUTOFF_YEAR = 2010

TARGETS = [
    ("revenue",          ["RevenueFromContractWithCustomerExcludingAssessedTax",
                          "SalesRevenueNet", "Revenues",
                          "RevenueFromContractWithCustomerIncludingAssessedTax",          # Including 버전 (US는 차이 미미)
                          "SalesRevenueGoodsNet",                                         # 제조업 일부
                          "NetRevenues",
                          "OilAndGasRevenue",                                             # E&P (EQT 등)
                          "GasGatheringTransportationMarketingAndProcessingRevenue",      # 미드스트림 (TRGP 등)
                          "RegulatedAndUnregulatedOperatingRevenue"],                     # 규제 유틸리티 (DTE, ATO, XEL 등)
                                                                                   "USD"),
    ("operating_income", ["OperatingIncomeLoss",
                          # 금융·에너지·헬스케어 등 OperatingIncomeLoss 미사용 기업 → 세전이익 근사치
                          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                          "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"], # 주택업체 (NVR, PHM 등)
                                                                                   "USD"),
    ("net_income",       ["NetIncomeLoss",
                          "ProfitLoss",                                            # FCX, ITW, MNST 등 대형사 다수
                          "NetIncomeLossAvailableToCommonStockholdersBasic"],      # EW, BKNG, SYY, ROL, PAYX 등
                                                                                   "USD"),
    ("cfo",              ["NetCashProvidedByUsedInOperatingActivities",
                          "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],       "USD"),
    ("capex",            ["PaymentsToAcquirePropertyPlantAndEquipment",
                          "PaymentsToAcquireProductiveAssets",
                          "PaymentsToAcquireOtherPropertyPlantAndEquipment",      # ADP 등 일부
                          "PaymentsToAcquireOilAndGasPropertyAndEquipment",       # E&P (APA, FANG 등)
                          "PaymentsToAcquireOilAndGasEquipment"],                  "USD"),
    ("total_assets",     ["Assets"],                                                               "USD"),
    ("total_equity",     ["StockholdersEquity",
                          "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "USD"),
    ("shares_diluted",   ["WeightedAverageNumberOfDilutedSharesOutstanding",
                          "WeightedAverageNumberOfSharesOutstandingBasic",
                          "CommonStockSharesOutstanding"],                                         "shares"),
]

SNAPSHOT_COLS = {"total_assets", "total_equity", "shares_diluted"}
FP_TO_Q = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}


# ── DB ────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quarterly_financials (
            ticker                TEXT,
            term                  TEXT,
            fiscal_year_end_month INTEGER,
            revenue               INTEGER,
            operating_income      INTEGER,
            net_income            INTEGER,
            cfo                   INTEGER,
            capex                 INTEGER,
            total_assets          INTEGER,
            total_equity          INTEGER,
            shares_diluted        INTEGER,
            updated_at            TEXT,
            PRIMARY KEY (ticker, term)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filing_meta (
            ticker              TEXT PRIMARY KEY,
            latest_filed        TEXT,
            latest_form         TEXT,
            latest_8k_202_filed TEXT,
            updated_at          TEXT
        )
    """)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(filing_meta)")}
    if "latest_8k_202_filed" not in cols:
        conn.execute("ALTER TABLE filing_meta ADD COLUMN latest_8k_202_filed TEXT")
    conn.commit()


# ── EDGAR ─────────────────────────────────────────────────────────

def fetch_facts(cik: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return sec_get(url, HEADERS).json()


def fetch_submissions(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return sec_get(url, HEADERS).json()


def latest_8k_202(submissions: dict) -> str | None:
    """가장 최근 8-K Item 2.02(실적 발표 프레스릴리즈) 제출일 — 정식 10-Q/10-K 전 '잠정' 신호."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms  = recent.get("form", [])
    items  = recent.get("items", [])
    dates  = recent.get("filingDate", [])
    best = None
    for form, item, filed in zip(forms, items, dates):
        if form != "8-K" or "2.02" not in item.split(","):
            continue
        if filed and (best is None or filed > best):
            best = filed
    return best


def latest_filing(facts: dict) -> tuple[str | None, str | None]:
    """이미 받아온 companyfacts 안에서 가장 최근 10-Q/10-K 제출일 찾기 (추가 API 호출 없음)."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    best_filed, best_form = None, None
    for entry in usgaap.values():
        for unit_rows in entry.get("units", {}).values():
            for r in unit_rows:
                if r.get("form") not in ("10-Q", "10-K") or r.get("dimensions"):
                    continue
                filed = r.get("filed", "")
                if filed and (best_filed is None or filed > best_filed):
                    best_filed, best_form = filed, r["form"]
    return best_filed, best_form


def _best_record_per_period(records: list[dict], prefer_ytd: bool = True,
                            prefer_earliest_filed: bool = False) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df = (df.sort_values("filed", ascending=False)
            .drop_duplicates(subset=["period_key", "end", "val"], keep="first"))
    if prefer_earliest_filed:
        # shares_diluted: 가장 먼저 신고된 값 사용 (스플릿 소급 조정값 회피)
        # filed 동일 시 end 날짜가 늦은 것 우선 (파산 재상장 Predecessor 기간 데이터 배제)
        df = (df.sort_values(["filed", "end"], ascending=[True, False])
                .drop_duplicates(subset=["period_key"], keep="first"))
    elif prefer_ytd:
        # 플로우 지표: YTD 누적값 선택 — 같은 (연도, 분기)의 레코드 중 기간(duration)이 가장 긴 것.
        # (2026-10-06 수정: 이전엔 '가장 큰 값'을 골랐는데, 적자·부호 혼재 구간에서 3개월 값이
        #  누적값 대신 뽑혀 이후 분기 차감이 틀어졌다. 예: INCY 2024Q2~Q4 순이익)
        # 기간이 같으면 최근 제출분 우선.
        df = (df.sort_values(["duration_days", "filed"], ascending=[False, False])
                .drop_duplicates(subset=["period_key"], keep="first"))
    else:
        # 스냅샷 지표(total_assets 등): 단일 분기 기간(가장 짧은 duration) 선택
        df = (df.sort_values("duration_days", ascending=True)
                .drop_duplicates(subset=["period_key"], keep="first"))
    return df


# ── 종목별·시대별 매출 태그 (scripts/build_revenue_tag_map.py 가 손익계산서 최상단 행에서 추출) ──
# 매핑에서 1순위로 쓸 수 있는 표준 총매출 태그. 손익계산서 최상단 행이라도 ElectricUtilityRevenue·
# PassengerRevenue·ClearingFeesRevenue 같은 하위 항목 태그나 SalesRevenueServicesNet(서비스만)·
# SalesRevenueGoodsNet(제품만 — UNH·INCY·BIIB에서 하위 줄이 잡혀 오히려 틀림)은 총매출이 아닐 수 있어
# 제외하고 기본 우선순위에 맡긴다.
REV_TAG_WHITELIST = {
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "RegulatedAndUnregulatedOperatingRevenue",
}


def _load_revenue_tag_map() -> dict:
    import json
    path = DATA_DIR / 'revenue_tag_map.json'
    if not path.exists():
        return {}
    out = {}
    for t, by_year in json.loads(path.read_text()).items():
        ok = {y: tag for y, tag in by_year.items() if tag in REV_TAG_WHITELIST}
        if ok:
            out[t] = ok
    return out


REV_TAG_MAP = _load_revenue_tag_map()


def _era_tag(era_tags: dict | None, year: int) -> str | None:
    """era_tags {'2014': 태그, ...}: 해당 연도 이후 첫 샘플의 태그, 없으면 가장 최근 샘플의 태그."""
    if not era_tags:
        return None
    ys = sorted(int(y) for y in era_tags)
    for y in ys:
        if y >= year:
            return era_tags[str(y)]
    return era_tags[str(ys[-1])]


def _pick(per_tag: dict, order: list[str], key: tuple, era_tags: dict | None):
    """태그별 값(per_tag)에서 key 기간의 값 선택: 그 시대 정답 태그 → 기본 우선순위.
    먼저 찾은 값이 정확히 0이고 뒤 순위 태그에 0이 아닌 값이 있으면 후자 (예: BKR NetIncomeLoss=0)."""
    pref = _era_tag(era_tags, key[0])
    seq = ([pref] if pref in per_tag else []) + [t for t in order if t != pref]
    chosen = None
    for t in seq:
        v = per_tag.get(t, {}).get(key)
        if v is None:
            continue
        if chosen is None:
            chosen = v
        if chosen != 0:
            break
        if v != 0:
            chosen = v
            break
    return chosen


def extract_periods(facts: dict, tags: list[str], label: str, unit: str = "USD",
                    prefer_ytd: bool = True, prefer_earliest_filed: bool = False,
                    fy_end_month: int = 12, era_tags: dict | None = None) -> pd.DataFrame:
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    per_tag: dict[str, dict[tuple, float]] = {}

    for tag in tags:
        entry = usgaap.get(tag)
        if not entry:
            continue
        rows = entry.get("units", {}).get(unit, [])
        if not rows:
            continue

        records = []
        for r in rows:
            fp = r.get("fp", "")
            if fp not in FP_TO_Q:
                continue
            form = r.get("form", "")
            if fp == "FY" and form != "10-K":
                continue
            if fp != "FY" and form != "10-Q":
                continue
            if r.get("dimensions"):
                continue
            start_date = r.get("start", "")
            end_date = r.get("end", "")
            end_year  = int(end_date[:4]) if end_date else 0
            end_month = int(end_date[5:7]) if end_date else 0
            if fp == "FY":
                year = end_year
            else:
                year = end_year + 1 if end_month > fy_end_month else end_year
            if year < CUTOFF_YEAR:
                continue
            q = FP_TO_Q[fp]
            try:
                duration_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days if start_date and end_date else 9999
            except ValueError:
                duration_days = 9999
            # fp별 최대 허용 기간 초과 시 제외 (AMZN처럼 TTM이 Q1 fp로 신고되는 케이스)
            fp_max = {"Q1": 130, "Q2": 220, "Q3": 310}.get(fp)
            if fp_max and duration_days > fp_max:
                continue
            records.append({
                "period_key":    (year, q),
                "fiscal_year":   year,
                "quarter":       q,
                "end":           end_date,
                "filed":         r.get("filed", ""),
                "val":           r["val"],
                "duration_days": duration_days,
            })

        if not records:
            continue
        df_tag = _best_record_per_period(records, prefer_ytd=prefer_ytd,
                                         prefer_earliest_filed=prefer_earliest_filed)
        for _, row in df_tag.iterrows():
            per_tag.setdefault(tag, {})[(row["fiscal_year"], row["quarter"])] = row["val"]

    combined: dict[tuple, float] = {}
    for k in {k for d in per_tag.values() for k in d}:
        v = _pick(per_tag, tags, k, era_tags)
        if v is not None:
            combined[k] = v

    if not combined:
        return pd.DataFrame()

    idx = pd.MultiIndex.from_tuples(sorted(combined.keys()), names=["year", "quarter"])
    return pd.Series(combined, name=label).reindex(idx).to_frame()


def ytd_to_single_quarter(df_ytd: pd.DataFrame, label: str) -> pd.Series:
    out = {}
    col = df_ytd[label]
    for y in sorted(col.index.get_level_values("year").unique()):
        q1 = col.get((y, 1))
        q2 = col.get((y, 2))
        q3 = col.get((y, 3))
        fy = col.get((y, 4))
        out[f"{y}Q1"] = q1
        out[f"{y}Q2"] = (q2 - q1) if (pd.notna(q2) and pd.notna(q1)) else None
        out[f"{y}Q3"] = (q3 - q2) if (pd.notna(q3) and pd.notna(q2)) else None
        out[f"{y}Q4"] = (fy - q3) if (pd.notna(fy) and pd.notna(q3)) else None
    return pd.Series(out, name=label)


# 손익 항목은 10-Q에 3개월 값이 직접 보고된다. YTD 누적끼리 빼면(Q3 = 9개월 − 6개월) 두 값의
# 보고 시점이 달라(소급 재작성) 어느 공시에도 없는 값이 나오는 경우가 있어, Q1~Q3는 직접 보고된
# 3개월 값을 우선 쓴다. 현금흐름(cfo·capex)은 3개월 값이 없어 차감 방식을 유지한다.
DIRECT_QUARTER_LABELS = {"revenue", "operating_income", "net_income"}


def direct_quarters(facts: dict, tags: list[str], unit: str = "USD",
                    fy_end_month: int = 12, era_tags: dict | None = None) -> dict[str, float]:
    """10-Q에 직접 보고된 3개월(80~100일) 값 → {'2024Q2': 값}. 태그는 우선순위대로 먼저 값이 있는 쪽 사용,
    같은 기간의 중복 보고는 가장 최근 제출분."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    per_tag: dict[str, dict[tuple, float]] = {}
    for tag in tags:
        rows = usgaap.get(tag, {}).get("units", {}).get(unit, [])
        best: dict[tuple, tuple] = {}
        for r in rows:
            if r.get("form") != "10-Q" or r.get("dimensions"):
                continue
            start, end = r.get("start", ""), r.get("end", "")
            if not start or not end:
                continue
            try:
                end_d = date.fromisoformat(end)
                dur = (end_d - date.fromisoformat(start)).days
            except ValueError:
                continue
            if not 80 <= dur <= 100:
                continue
            # 분기는 fp가 아니라 기간 종료일로 판정한다 — 3분기 10-Q에는 2분기에 끝난 3개월 값도
            # fp=Q3으로 실려 있어 fp로는 엉뚱한 분기에 들어간다. 52/53주 회계의 종료일 흔들림(±며칠)은
            # 종료일에서 10일을 뺀 달 기준으로 흡수한다.
            adj = end_d - timedelta(days=10)
            k = (adj.month - fy_end_month) % 12          # 회계연도 말 이후 경과 개월 (0이면 연말)
            q = 4 if k == 0 else (k + 2) // 3
            if q == 4:
                continue                                   # 4분기 3개월 값은 10-Q에 없음
            year = adj.year + 1 if adj.month > fy_end_month else adj.year
            if year < CUTOFF_YEAR:
                continue
            key = (year, q)
            filed = r.get("filed", "")
            if key not in best or filed > best[key][0]:
                best[key] = (filed, r["val"])
        for key, (_, val) in sorted(best.items()):
            # 같은 태그에서 직전 분기와 값이 정확히 같으면 SEC 원본 오류로 본다 (예: AEP 2022Q3
            # NetIncomeLoss가 2분기 값 520.8을 반복) → 이 태그의 값은 버리고 다음 태그로 채운다.
            prev = best.get((key[0], key[1] - 1))
            if prev is not None and prev[1] == val and val != 0:
                continue
            per_tag.setdefault(tag, {})[key] = val
    out: dict[tuple, float] = {}
    for key in {k for d in per_tag.values() for k in d}:
        v = _pick(per_tag, tags, key, era_tags)
        if v is not None:
            out[key] = v
    return {f"{y}Q{q}": v for (y, q), v in out.items()}


def normalize_shares(s: pd.Series) -> pd.Series:
    """단위 불일치 정규화: EDGAR 신고가 thousands/millions 단위로 기입된 경우 양방향 보정.
    중앙값 대비 100배 이상 차이나는 값을 가장 가까운 10의 3승 배수(1000, 1000000 …)로 보정.
    """
    import math

    vals = s.dropna()
    if vals.empty:
        return s
    median = vals.median()
    if median < 1:
        return s

    def nearest_power_of_1000(x: float) -> int:
        """100, 500, 100000 … → 가장 가까운 10^(3k) 반환 (1000, 1000000 …)"""
        exp = round(math.log10(x) / 3) * 3
        return max(3, exp)  # 최소 1000배

    def fix(v):
        if pd.isna(v) or v < 0:
            return v
        if v == 0:
            return float('nan')  # 0주는 항상 무효값
        ratio = median / v
        if ratio > 100:
            # 값이 너무 작음 → 올림
            factor = 10 ** nearest_power_of_1000(ratio)
            return v * factor
        if ratio < 1 / 100:
            # 값이 너무 큼 → 내림
            factor = 10 ** nearest_power_of_1000(1 / ratio)
            return v / factor
        return v

    return s.apply(fix)


def collect_ticker(facts: dict, fy_end_month: int = 12, rev_era_tags: dict | None = None) -> pd.DataFrame:
    quarterly_frames = []

    for label, tags, unit in TARGETS:
        prefer_ytd            = label not in SNAPSHOT_COLS
        prefer_earliest_filed = (label == 'shares_diluted')
        era = rev_era_tags if label == "revenue" else None
        df_p = extract_periods(facts, tags, label, unit=unit,
                               prefer_ytd=prefer_ytd,
                               prefer_earliest_filed=prefer_earliest_filed,
                               fy_end_month=fy_end_month, era_tags=era)
        if df_p.empty:
            continue
        if label in SNAPSHOT_COLS:
            s = df_p[label].copy()
            s.index = [f"{y}Q{q}" for y, q in s.index]
            s = s.rename(label)
            if label == 'shares_diluted':
                s = normalize_shares(s)
            quarterly_frames.append(s)
        else:
            s = ytd_to_single_quarter(df_p, label)
            if label in DIRECT_QUARTER_LABELS:
                direct = direct_quarters(facts, tags, unit, fy_end_month, era_tags=era)
                s = s.astype(float)
                for term, val in direct.items():
                    s[term] = val            # Q1~Q3: 직접 보고된 3개월 값 우선
                for y in sorted({int(t[:4]) for t in s.index}):
                    fy_val = df_p[label].get((y, 4))
                    qs = [s.get(f"{y}Q{q}") for q in (1, 2, 3)]
                    if pd.notna(fy_val) and all(pd.notna(v) for v in qs):
                        s[f"{y}Q4"] = fy_val - sum(qs)   # 4분기 = 연간 − (Q1+Q2+Q3): 합계가 연간과 일치
            quarterly_frames.append(s)

    if not quarterly_frames:
        return pd.DataFrame()

    df_q = pd.concat(quarterly_frames, axis=1).sort_index()
    df_q.index.name = "term"

    # revenue·capex 는 항상 양수여야 함 — 음수는 YTD 뺄셈 artifact
    for col in ("revenue", "capex"):
        if col in df_q.columns:
            df_q.loc[df_q[col] < 0, col] = None

    return df_q.dropna(how='all')


def upsert(conn: sqlite3.Connection, ticker: str, df_q: pd.DataFrame, fy_end_month: int):
    now = datetime.utcnow().isoformat()
    cols = ["revenue", "operating_income", "net_income", "cfo", "capex",
            "total_assets", "total_equity", "shares_diluted"]
    rows = []
    for term, row in df_q.iterrows():
        vals = [int(row[c]) if pd.notna(row.get(c)) else None for c in cols]
        rows.append((ticker, term, fy_end_month, *vals, now))

    conn.executemany("""
        INSERT INTO quarterly_financials
            (ticker, term, fiscal_year_end_month,
             revenue, operating_income, net_income, cfo, capex,
             total_assets, total_equity, shares_diluted, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, term) DO UPDATE SET
            fiscal_year_end_month = excluded.fiscal_year_end_month,
            revenue          = excluded.revenue,
            operating_income = excluded.operating_income,
            net_income       = excluded.net_income,
            cfo              = excluded.cfo,
            capex            = excluded.capex,
            total_assets     = excluded.total_assets,
            total_equity     = excluded.total_equity,
            shares_diluted   = COALESCE(excluded.shares_diluted, quarterly_financials.shares_diluted),
            updated_at       = excluded.updated_at
    """, rows)
    conn.commit()


def upsert_filing_meta(conn: sqlite3.Connection, ticker: str, filed: str | None, form: str | None,
                        latest_8k: str | None, now: str):
    if not filed and not latest_8k:
        return
    conn.execute("""
        INSERT INTO filing_meta (ticker, latest_filed, latest_form, latest_8k_202_filed, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            latest_filed        = excluded.latest_filed,
            latest_form         = excluded.latest_form,
            latest_8k_202_filed = excluded.latest_8k_202_filed,
            updated_at          = excluded.updated_at
    """, (ticker, filed, form, latest_8k, now))
    conn.commit()


# ── 실행 ──────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='시총 상위 N개만 수집')
    parser.add_argument('--ticker', action='append', default=None, help='특정 종목만 수집 (반복 가능)')
    args = parser.parse_args()

    universe = pd.read_csv(f'{DATA_DIR}/stock_universe.csv')
    fy_map   = dict(zip(universe['ticker'], universe['fiscal_year_end_month'].fillna(12).astype(int)))
    tickers  = universe['ticker'].tolist()
    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    elif args.limit:
        tickers = tickers[:args.limit]
    print(f'유니버스: {len(tickers)}개 종목\n')

    r = sec_get('https://www.sec.gov/files/company_tickers.json', HEADERS)
    cik_map = {v['ticker'].upper(): str(v['cik_str']).zfill(10)
               for v in r.json().values()}
    print(f'EDGAR CIK 맵: {len(cik_map)}개\n')

    # company_tickers.json에서 구조적으로 못 찾는 종목 수동 보정.
    # SATS(EchoStar): SEC 자체에 등록된 티커가 "ECHO"라 실거래 티커로는 영영 안 잡힘.
    # AEP: 회사·CIK 정상인데 SEC 벌크 파일에서만 일시 누락(2026-08 2주째, XOM/FDXF가 겪었던 것과 같은 유형).
    CIK_OVERRIDES = {
        'SATS': '0001415404',
        'AEP':  '0000004904',
    }

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    ok, skipped, failed = 0, 0, []

    for i, ticker in enumerate(tickers, 1):
        cik = cik_map.get(ticker) or CIK_OVERRIDES.get(ticker)
        if not cik:
            print(f'[{i:3}/{len(tickers)}] {ticker:8} | CIK 없음 — skip')
            skipped += 1
            continue

        try:
            fy_end = fy_map.get(ticker, 12)
            facts = fetch_facts(cik)
            filed, form = latest_filing(facts)

            time.sleep(0.12)  # EDGAR ~8 req/s — 티커당 2번째 호출
            submissions = fetch_submissions(cik)
            latest_8k = latest_8k_202(submissions)

            # companyfacts 갱신이 멈춘 종목은 10-Q/10-K 원본 XBRL에서 직접 보충
            patched = patch_missing_filings(facts, submissions, int(cik), TARGETS, HEADERS)
            if patched:
                print(f'[{i:3}/{len(tickers)}] {ticker:8} | companyfacts 누락 {len(patched)}건 보충: {patched}')
                filed, form = latest_filing(facts)

            upsert_filing_meta(conn, ticker, filed, form, latest_8k, now=datetime.utcnow().isoformat())

            df_q = collect_ticker(facts, fy_end_month=fy_end, rev_era_tags=REV_TAG_MAP.get(ticker.upper()))
            if df_q.empty:
                print(f'[{i:3}/{len(tickers)}] {ticker:8} | 데이터 없음 — skip')
                skipped += 1
            else:
                upsert(conn, ticker, df_q, fy_end_month=fy_end)
                print(f'[{i:3}/{len(tickers)}] {ticker:8} | {len(df_q)}개 분기 저장')
                ok += 1
        except Exception as e:
            failed.append(ticker)
            print(f'[{i:3}/{len(tickers)}] {ticker:8} | ERROR: {e}')

        time.sleep(0.12)  # EDGAR ~8 req/s

    conn.close()
    print(f'\n완료  성공 {ok}  /  스킵 {skipped}  /  실패 {len(failed)}')
    if failed:
        print(f'실패 목록: {failed}')


if __name__ == '__main__':
    main()
