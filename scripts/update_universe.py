"""
유니버스 업데이트 스크립트
분기 재무 데이터 수집 전에 실행

- S&P 500 유니버스: Wikipedia + yfinance + SEC EDGAR → data/stock_universe.csv
"""

import re
import time
import requests
import pandas as pd
import yfinance as yf
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'
HEADERS  = {'User-Agent': 'hwan@to.nexus (research)'}


# ── S&P 500 ────────────────────────────────────────────────────────

def fetch_sp500_tickers() -> list[str]:
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    r   = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    df  = pd.read_html(r.text)[0]
    return df['Symbol'].str.replace('.', '-', regex=False).tolist()  # BRK.B → BRK-B


def fetch_cik_map() -> dict[str, str]:
    """EDGAR 전체 티커→CIK 맵 (10자리 zero-padded)"""
    r = requests.get('https://www.sec.gov/files/company_tickers.json',
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {v['ticker'].upper(): str(v['cik_str']).zfill(10)
            for v in r.json().values()}


def fetch_fiscal_year_end_month(cik: str) -> int | None:
    """EDGAR submissions API에서 회계연도 종료 월 반환"""
    r = requests.get(f'https://data.sec.gov/submissions/CIK{cik}.json',
                     headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return None
    fy = r.json().get('fiscalYearEnd', '')  # 예: "0926" (MMDD)
    if fy and len(fy) >= 2:
        return int(fy[:2])
    return None


def shorten_summary(text: str, max_sentences: int = 2) -> str:
    if not text:
        return ''
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return ' '.join(sentences[:max_sentences])


def fmt_cap(v) -> str:
    if pd.isna(v) or v == 0: return ''
    if v >= 1e12: return f'${v/1e12:.2f}T'
    if v >= 1e9:  return f'${v/1e9:.1f}B'
    return f'${v/1e6:.0f}M'


def build_sp500_universe():
    print('[ S&P 500 유니버스 업데이트 ]')

    tickers = fetch_sp500_tickers()
    print(f'  종목 수: {len(tickers)}개')

    cik_map = fetch_cik_map()
    print(f'  EDGAR CIK 맵: {len(cik_map)}개 로드\n')

    rows, failed = [], []

    for i, ticker in enumerate(tickers, 1):
        try:
            info = yf.Ticker(ticker).info

            # EDGAR에서 회계연도 종료 월 (10 req/s 제한 준수)
            cik          = cik_map.get(ticker)
            fiscal_month = fetch_fiscal_year_end_month(cik) if cik else None
            time.sleep(0.12)  # ~8 req/s

            rows.append({
                'ticker':                ticker,
                'company':               info.get('longName') or info.get('shortName', ''),
                'sector':                info.get('sector', ''),
                'industry':              info.get('industry', ''),
                'country':               info.get('country', ''),
                'market_cap':            info.get('marketCap'),
                'fiscal_year_end_month': fiscal_month,
                'biz_model':             shorten_summary(info.get('longBusinessSummary', '')),
            })

            fy_str = str(fiscal_month).rjust(2) if fiscal_month else ' ?'
            print(f'  [{i:3}/{len(tickers)}] {ticker:8} | FY end month: {fy_str}')

        except Exception as e:
            failed.append(ticker)
            print(f'  [{i:3}/{len(tickers)}] {ticker:8} | ERROR: {e}')

        if i % 20 == 0:
            time.sleep(1)

    df = pd.DataFrame(rows).sort_values('market_cap', ascending=False)
    df['market_cap_str'] = df['market_cap'].apply(fmt_cap)

    path = f'{DATA_DIR}/stock_universe.csv'
    df.to_csv(path, index=False, encoding='utf-8-sig')
    print(f'\n  ✅ 저장: {path}  ({len(df)}개, 실패: {len(failed)}개)')
    if failed:
        print(f'     실패: {failed}')


# ── 실행 ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    build_sp500_universe()
