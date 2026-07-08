"""
전체 유니버스 분기 재무 데이터 수집 → SQLite 저장
실행: python scripts/collect_financials.py
분기마다 실행 → upsert (있으면 갱신, 없으면 삽입)
"""

import sqlite3
import time
import requests
import pandas as pd
from datetime import datetime, date
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'
DB_PATH  = DATA_DIR / 'stocks.db'
HEADERS  = {'User-Agent': 'hwan@to.nexus (research)'}
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
    conn.commit()


# ── EDGAR ─────────────────────────────────────────────────────────

def fetch_facts(cik: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


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
        # 플로우 지표: YTD 누적값(가장 큰 값) 선택
        df = (df.sort_values("val", ascending=False)
                .drop_duplicates(subset=["period_key"], keep="first"))
    else:
        # 스냅샷 지표(total_assets 등): 단일 분기 기간(가장 짧은 duration) 선택
        df = (df.sort_values("duration_days", ascending=True)
                .drop_duplicates(subset=["period_key"], keep="first"))
    return df


def extract_periods(facts: dict, tags: list[str], label: str, unit: str = "USD",
                    prefer_ytd: bool = True, prefer_earliest_filed: bool = False,
                    fy_end_month: int = 12) -> pd.DataFrame:
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    combined: dict[tuple, float] = {}

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
            k = (row["fiscal_year"], row["quarter"])
            if k not in combined:
                combined[k] = row["val"]

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


def collect_ticker(cik: str, fy_end_month: int = 12) -> pd.DataFrame:
    facts = fetch_facts(cik)
    quarterly_frames = []

    for label, tags, unit in TARGETS:
        prefer_ytd            = label not in SNAPSHOT_COLS
        prefer_earliest_filed = (label == 'shares_diluted')
        df_p = extract_periods(facts, tags, label, unit=unit,
                               prefer_ytd=prefer_ytd,
                               prefer_earliest_filed=prefer_earliest_filed,
                               fy_end_month=fy_end_month)
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

    r = requests.get('https://www.sec.gov/files/company_tickers.json',
                     headers=HEADERS, timeout=30)
    cik_map = {v['ticker'].upper(): str(v['cik_str']).zfill(10)
               for v in r.json().values()}
    print(f'EDGAR CIK 맵: {len(cik_map)}개\n')

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    ok, skipped, failed = 0, 0, []

    for i, ticker in enumerate(tickers, 1):
        cik = cik_map.get(ticker)
        if not cik:
            print(f'[{i:3}/{len(tickers)}] {ticker:8} | CIK 없음 — skip')
            skipped += 1
            continue

        try:
            fy_end = fy_map.get(ticker, 12)
            df_q = collect_ticker(cik, fy_end_month=fy_end)
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
