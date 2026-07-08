"""
분기 재무 데이터 품질 체크
수집 후 실행: python scripts/check_quality.py

이상 없으면 OK 출력, 이상 있으면 경고 목록 출력.
"""

import sqlite3
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import EXCLUDED_SECTORS

ROOT      = Path(__file__).parent.parent
DB_PATH   = ROOT / "data" / "stocks.db"
UNIV_PATH = ROOT / "data" / "stock_universe.csv"

# NULL 허용 임계값 (제외 섹터 빠진 후 기준)
NULL_THRESHOLD = {
    "revenue":          0.08,
    "operating_income": 0.12,
    "net_income":       0.06,
    "cfo":              0.06,
    "capex":            0.20,
    "total_assets":     0.05,
    "total_equity":     0.05,
    "shares_diluted":   0.05,
}

JUMP_EXCLUDED = EXCLUDED_SECTORS

FLOW_COLS     = ["revenue", "operating_income", "net_income", "cfo", "capex"]
SNAPSHOT_COLS = ["total_assets", "total_equity", "shares_diluted"]
ALL_COLS      = FLOW_COLS + SNAPSHOT_COLS


def filed_terms(df: pd.DataFrame, coverage_min: float = 0.7) -> list[str]:
    """전체 종목의 coverage_min 이상이 데이터를 가진 분기만 반환 (미신고 분기 제외)"""
    total_tickers = df["ticker"].nunique()
    by_term = (
        df.groupby("term")["net_income"]
        .apply(lambda s: s.notna().sum() / total_tickers)
    )
    return sorted(by_term[by_term >= coverage_min].index.tolist())


def recent_filed(df: pd.DataFrame, n: int) -> list[str]:
    return filed_terms(df)[-n:]


def check_null_rates(df: pd.DataFrame, univ: pd.DataFrame) -> list[str]:
    warnings = []
    rec = recent_filed(df, n=2)
    if not rec:
        return ["  [경고] 충분히 신고된 분기 없음 — 수집 확인 필요"]

    df_rec = df[df["term"].isin(rec)].merge(univ[["ticker", "sector"]], on="ticker", how="left")
    df_ok  = df_rec[~df_rec["sector"].isin(EXCLUDED_SECTORS)]
    total  = len(df_ok)

    for col, threshold in NULL_THRESHOLD.items():
        n_null = df_ok[col].isna().sum()
        rate = n_null / total if total else 0
        if rate > threshold:
            warnings.append(
                f"  [NULL 과다] {col}: {rate:.1%} ({n_null}/{total}) "
                f"— 임계값 {threshold:.0%} 초과 (기준 분기: {', '.join(rec)})"
            )
    return warnings


def check_zero_values(df: pd.DataFrame) -> list[str]:
    """total_assets, shares_diluted 에 0이 있으면 오류 (전체 기간 체크)"""
    warnings = []
    for col in ["total_assets", "shares_diluted"]:
        zeros = df[(df[col].notna()) & (df[col] == 0)]
        if not zeros.empty:
            info = zeros[["ticker", "term"]].values.tolist()
            warnings.append(f"  [0값 오류] {col} = 0: {info}")
    return warnings


def check_sudden_jumps(df: pd.DataFrame, univ: pd.DataFrame) -> list[str]:
    """전분기 대비 50배 이상 급변 (양수값끼리, 절댓값 $500M 이상)"""
    warnings = []
    sector_map = dict(zip(univ["ticker"], univ["sector"]))
    fy_map     = dict(zip(univ["ticker"], univ["fiscal_year_end_month"].fillna(12).astype(int)))

    def sort_key(term: str, fy_end: int) -> int:
        y, q = int(term[:4]), int(term[5])
        m = fy_end - (4 - q) * 3
        if m <= 0:
            m += 12
        cal_y = y - 1 if m > fy_end else y
        return cal_y * 12 + m

    for col in ["revenue", "net_income", "shares_diluted"]:
        for ticker, grp in df[df[col].notna()].groupby("ticker"):
            if sector_map.get(ticker) in JUMP_EXCLUDED:
                continue
            fy_end = fy_map.get(ticker, 12)
            grp = grp.copy()
            grp["_sk"] = grp["term"].apply(lambda t: sort_key(t, fy_end))
            grp = grp.sort_values("_sk")
            vals  = grp[col].tolist()
            terms = grp["term"].tolist()
            for i in range(1, len(vals)):
                prev, curr = vals[i - 1], vals[i]
                # 부호 다르면 비율 의미 없음, 절댓값 작으면 노이즈
                if prev <= 0 or curr <= 0:
                    continue
                if max(abs(prev), abs(curr)) < 500_000_000:
                    continue
                ratio = curr / prev
                if ratio >= 50 or ratio <= 0.02:
                    warnings.append(
                        f"  [급변] {ticker} {col}: "
                        f"{terms[i-1]}={prev/1e9:.2f}B → {terms[i]}={curr/1e9:.2f}B "
                        f"(x{ratio:.1f})"
                    )
    return warnings


def check_missing_tickers(df: pd.DataFrame, univ: pd.DataFrame) -> list[str]:
    """유니버스에 있지만 DB에 데이터가 전혀 없는 종목"""
    in_db = set(df["ticker"].unique())
    missing = univ[~univ["ticker"].isin(in_db)][["ticker", "company"]]
    if missing.empty:
        return []
    return [f"  [수집 누락] {r['ticker']} ({r.get('company','')})" for _, r in missing.iterrows()]


def main():
    conn = sqlite3.connect(DB_PATH)
    df   = pd.read_sql("SELECT * FROM quarterly_financials", conn)
    conn.close()
    univ = pd.read_csv(UNIV_PATH)

    print(f"DB 전체: {len(df):,}행  /  {df['ticker'].nunique()}종목")

    rec2 = recent_filed(df, n=2)
    rec4 = recent_filed(df, n=4)
    print(f"충분히 신고된 최근 분기: {rec2} (NULL 체크 기준)\n")

    all_warnings = []
    all_warnings += check_null_rates(df, univ)
    all_warnings += check_zero_values(df)
    all_warnings += check_sudden_jumps(df, univ)
    all_warnings += check_missing_tickers(df, univ)

    if not all_warnings:
        print("✓ 이상 없음 — 분석 진행 가능")
    else:
        print(f"⚠  경고 {len(all_warnings)}건:")
        for w in all_warnings:
            print(w)

    # ── 최근 2분기 NULL 현황 (참고용) ─────────────────────
    df_rec = df[df["term"].isin(rec2)].merge(univ[["ticker", "sector"]], on="ticker", how="left")
    df_ok  = df_rec[~df_rec["sector"].isin(EXCLUDED_SECTORS)]
    total  = len(df_ok)
    print(f"\n최근 2분기({', '.join(rec2)}) NULL 현황 (Financial/REIT 제외, {total}행):")
    for col in ALL_COLS:
        n    = df_ok[col].isna().sum()
        flag = " ← 확인" if total and n / total > NULL_THRESHOLD.get(col, 0.1) else ""
        print(f"  {col:<20} {n:>4}건 ({n/total:.1%}){flag}")


if __name__ == "__main__":
    main()
