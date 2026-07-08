# DB 구조 개요

## 데이터 흐름

```
SEC EDGAR (XBRL API)
  └─▶ stocks.db / quarterly_financials       ← collect_financials.py
        └─▶ ttm_valuation.db / ttm_financials    ← compute_ttm.py
              └─▶ ttm_growth.db / ttm_growth_series   ← compute_growth.py

yfinance
  └─▶ prices.db / daily_prices               ← collect_prices.py (예정)

ttm_valuation.db + prices.db
  └─▶ valuation.db / valuation_multiples      ← compute_valuation.py
```

## DB 파일 목록

| 파일 | 테이블 | 역할 | 명세 |
|------|--------|------|------|
| `data/stocks.db` | `quarterly_financials` | 분기 원천 재무 (EDGAR) | [data_collection.md](data_collection.md) |
| `data/ttm_valuation.db` | `ttm_financials` | TTM 시계열 | [ttm_computation.md](ttm_computation.md) |
| `data/ttm_growth.db` | `ttm_growth_series` | 성장률 시계열 (1y/2y/4y/8y CAGR) | [growth_computation.md](growth_computation.md) |
| `data/prices.db` | `daily_prices` | 일별 수정주가 (yfinance, 2006~) | — |
| `data/valuation.db` | `valuation_multiples` | 분기별 P/E·P/S·P/FCF·P/OP 배수 | [valuation_computation.md](valuation_computation.md) |

## 종목 범위

- **전체 수집**: S&P 500 구성 종목 (~503개)
- **분석 대상**: `exclude_analysis=False` 종목 (~329개)
- **제외 섹터**: Financial Services, Real Estate, Energy, Basic Materials, Utilities (`config.py`)

## 업데이트 순서 (분기마다)

```bash
python scripts/collect_financials.py   # 1. 분기 재무 수집
python scripts/check_quality.py        # 2. 품질 검증
python scripts/compute_ttm.py          # 3. TTM 재계산
python scripts/compute_growth.py       # 4. 성장률 재계산
python scripts/collect_prices.py       # 5. 주가 업데이트 (증분)
python scripts/compute_valuation.py    # 6. 밸류에이션 재계산
```
