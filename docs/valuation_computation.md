# 밸류에이션 멀티플 계산 명세

## 1. 개요

`ttm_valuation.db`의 TTM 시계열과 `prices.db`의 일별 수정주가를 결합해 분기별 밸류에이션 배수를 계산해 `valuation.db`에 저장한다.

- **입력**: `data/ttm_valuation.db` → `ttm_financials`
- **입력**: `data/prices.db` → `daily_prices`
- **출력**: `data/valuation.db` → `valuation_multiples`
- **스크립트**: `scripts/compute_valuation.py`
- **대상**: `stock_universe.csv`의 `exclude_analysis=False` 종목 (약 329개)


## 2. 계산 지표

| 접두사 | 분모 컬럼 | 설명 |
|--------|-----------|------|
| `pe`   | `ttm_net_income`  | 주가 / TTM 순이익 per share |
| `ps`   | `ttm_revenue`     | 주가 / TTM 매출 per share |
| `pfcf` | `ttm_fcf`         | 주가 / TTM 잉여현금흐름 per share |
| `pop`  | `ttm_op_income`   | 주가 / TTM 영업이익 per share |

분모가 0 이하이면 해당 배수는 NULL (적자 P/E 제외 원칙).


## 3. 핵심 설계: 주식 분할 처리

US 주식은 EDGAR `shares_diluted`가 분할 소급 적용이 아닌 보고 당시 실수치인 반면, yfinance `adj_close`는 분할을 소급 적용해 과거 가격을 낮춘다.

**해결책**: 가장 최신 `shares_diluted` (latest_shares)를 전 기간에 동일하게 사용한다.

```
market_cap_t = adj_close_t × latest_shares
```

adj_close는 분할 비율만큼 ÷, latest_shares는 분할 비율만큼 × → 상쇄되어 실제 시총 복원.

> **한계**: 자사주 매입(buyback)은 분할이 아니므로 완전 상쇄되지 않는다. 최근 4년 창에서는 영향이 미미하나 10년 이상 장기 시계열에서는 헤비 바이백 기업(AAPL 등)의 역사적 배수가 소폭 과소평가될 수 있다.


## 4. 공시 앵커일

분기 배수는 해당 분기 실적이 시장에 공개된 시점 이후를 기준으로 계산한다.

| 보고서 | 분기 | 앵커일 |
|--------|------|--------|
| 10-Q | Q1 / Q2 / Q3 | 분기말 + 45일 |
| 10-K | Q4 (연간) | 분기말 + 60일 |

분기말은 회계연도 종료월(`fiscal_year_end_month`)에서 역산한다.

```
m = fy_end_month - (4 - q) × 3
```

m ≤ 0이면 +12 보정, 달력 연도는 m > fy_end_month이면 전년도.

예시 (MSFT, fy_end=6):

| 분기 | 분기말 | 앵커일 |
|------|--------|--------|
| Q1   | 9월 30일 | 11월 14일 |
| Q2   | 12월 31일 | 2월 14일 |
| Q3   | 3월 31일 | 5월 15일 |
| Q4   | 6월 30일 | 8월 29일 |

앵커일이 오늘(실행일)보다 미래이면 today로 캡 처리한다.


## 5. 배수 계산 방법

### 5-1. 20일 평균 배수 (`{prefix}_20d`)

앵커일(또는 캡일) 이전 최근 20거래일의 adj_close 평균가를 주당 TTM 분모로 나눈다.

```
ps_20d = mean(adj_close[-20:]) / (ttm_revenue / latest_shares)
```

20일 평균을 쓰는 이유: 공시 직후 단기 노이즈를 완화하고 해당 분기 실적이 반영된 시장 가격의 대표값을 얻기 위함.

### 5-2. 4년 평균 배수 (`{prefix}_4y`)

`merge_asof`로 일별 주가에 공시 앵커일 기준 step-function 분모를 결합한 뒤, 앵커일 이전 4년 창의 일별 배수를 평균한다.

```
daily_ratio_t = adj_close_t / (ttm_value_at_last_filing / latest_shares)
ps_4y = mean(daily_ratio over [anchor_d - 4y, anchor_d])
```

step-function: 새 분기 공시 이전까지는 직전 공시의 분모값을 유지한다. 이는 시장이 가장 최신으로 알고 있는 실적 기준의 일별 배수를 산출한다.


## 6. DB 스키마 (`data/valuation.db`)

`valuation_multiples` 테이블 — PK: `(ticker, anchor_term)`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| ticker | TEXT | 종목 티커 |
| anchor_term | TEXT | 분기 레이블 (예: 2026Q2) |
| filing_anchor_date | TEXT | 공시 앵커일 (YYYY-MM-DD) |
| shares_latest | INTEGER | 최신 희석 주식수 (전 기간 공통 사용) |
| pe_20d | REAL | P/E (20일 평균가 기준) |
| pe_4y | REAL | P/E (4년 일별 평균) |
| ps_20d | REAL | P/S (20일) |
| ps_4y | REAL | P/S (4년) |
| pfcf_20d | REAL | P/FCF (20일) |
| pfcf_4y | REAL | P/FCF (4년) |
| pop_20d | REAL | P/OP (20일) |
| pop_4y | REAL | P/OP (4년) |
| computed_at | TEXT | 계산 일시 (UTC) |


## 7. 실행 방법

```bash
# 분석 대상 전체 (exclude_analysis=False, 기본값)
python scripts/compute_valuation.py

# 특정 종목만
python scripts/compute_valuation.py --ticker AAPL --ticker MSFT

# 제외 섹터 포함 전체
python scripts/compute_valuation.py --all
```

TTM 재계산 또는 주가 업데이트 후에는 재실행 (upsert 방식).


## 8. 데이터 현황 (2026-06-19 기준)

| 항목 | 값 |
|------|----|
| 총 행수 | 18,925 |
| 종목수 | 328 |
| anchor_term 범위 | 2010Q4 ~ 2027Q1 |
| skip 종목 | STZ (shares_diluted 전체 NULL) |

### NULL 비율 (20d 기준)

| 배수 | NULL 비율 | 주요 원인 |
|------|-----------|-----------|
| pe   | 6.8% | 적자 분기 (순손실) |
| ps   | 4.9% | 매출 NULL |
| pfcf | 11.1% | FCF 음수 (capex > CFO) |
| pop  | 7.2% | 적자 분기 (영업손실) |


## 9. 스크리닝 활용 예시

```sql
-- 최신 분기 기준 저평가 종목 (P/E 20d < 4년 평균의 80%, 흑자)
SELECT ticker, anchor_term,
       round(pe_20d, 1) as pe_20d,
       round(pe_4y,  1) as pe_4y,
       round(pe_20d / pe_4y, 2) as pe_ratio
FROM valuation_multiples
WHERE anchor_term = '2026Q2'
  AND pe_20d IS NOT NULL
  AND pe_4y  IS NOT NULL
  AND pe_20d / pe_4y < 0.8
ORDER BY pe_ratio ASC;
```
