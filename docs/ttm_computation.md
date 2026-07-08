# TTM 계산 명세

## 1. 개요

`quarterly_financials`(분기 원본)에서 TTM(Trailing Twelve Months) 시계열을 계산해 `ttm_valuation.db`에 저장한다.

- **대상**: `stock_universe.csv`의 `exclude_analysis=False` 종목만 (약 329개)
- **스크립트**: `scripts/compute_ttm.py`
- **조회 스크립트**: `scripts/show_ttm.py <TICKER>`


## 2. TTM 계산 로직

### 슬라이딩 윈도우

분기를 **회계연도 기준 시간순**으로 정렬 후, 4분기 슬라이딩 윈도우를 이동하며 anchor 분기마다 TTM을 계산한다.

```python
def sort_key(term, fy_end):
    y, q = int(term[:4]), int(term[5])
    m = fy_end - (4 - q) * 3
    if m <= 0: m += 12
    cy = y - 1 if m > fy_end else y
    return cy * 12 + m
```

- 12월 결산 외 회사(AAPL 9월, MSFT 6월 등)도 캘린더 시간순으로 정렬
- anchor_term = 윈도우에서 가장 최근 분기

### 지표별 계산 방식

| 유형 | 항목 | 계산 | NULL 처리 |
|---|---|---|---|
| Flow | revenue, op_income, net_income, cfo, capex | 4분기 합산 | 윈도우 내 1개라도 NULL이면 TTM = NULL |
| Derived | fcf | cfo - capex | 어느 하나라도 NULL이면 NULL |
| Snapshot | total_assets, total_equity, shares_diluted | 윈도우 내 가장 최근 non-null 값 | 전부 NULL이면 NULL |


## 3. DB 스키마 (`data/ttm_valuation.db`)

`ttm_financials` 테이블:

| 컬럼 | 타입 | 설명 |
|---|---|---|
| ticker | TEXT | 종목 티커 |
| anchor_term | TEXT | TTM 기준 분기 (예: 2026Q1) |
| q1_term ~ q4_term | TEXT | 윈도우 구성 분기 (오래된 순) |
| ttm_revenue | INTEGER | TTM 매출 (USD) |
| ttm_op_income | INTEGER | TTM 영업이익 |
| ttm_net_income | INTEGER | TTM 순이익 |
| ttm_cfo | INTEGER | TTM 영업현금흐름 |
| ttm_capex | INTEGER | TTM 자본적지출 |
| ttm_fcf | INTEGER | TTM 잉여현금흐름 (cfo - capex) |
| total_assets | INTEGER | 총자산 (윈도우 내 최근값) |
| total_equity | INTEGER | 총자본 (윈도우 내 최근값) |
| shares_diluted | INTEGER | 희석 주식수 (윈도우 내 최근값) |
| computed_at | TEXT | 계산 일시 (UTC) |
| PRIMARY KEY | (ticker, anchor_term) | |


## 4. 실행 방법

```bash
# 분석 대상 전체 (exclude_analysis=False, 기본값)
python scripts/compute_ttm.py

# 특정 종목만
python scripts/compute_ttm.py --ticker AAPL --ticker MSFT

# 제외 섹터 포함 전체
python scripts/compute_ttm.py --all
```

분기 데이터 재수집 후에는 재실행 (upsert 방식이므로 중복 없음).


## 5. 데이터 현황 (2026-06-18 기준)

| 항목 | 값 |
|---|---|
| 총 행수 | 18,988 |
| 종목수 | 329 |
| anchor_term 범위 | 2010Q4 ~ 2027Q1 |

### NULL 현황

| 컬럼 | NULL 건수 | 비율 |
|---|---|---|
| ttm_revenue | 877 | 4.6% |
| ttm_op_income | 389 | 2.0% |
| ttm_net_income | 220 | 1.2% |
| ttm_cfo | 284 | 1.5% |
| ttm_capex | 1,054 | 5.6% |
| ttm_fcf | 1,061 | 5.6% |
| total_assets | 189 | 1.0% |
| total_equity | 117 | 0.6% |
| shares_diluted | 164 | 0.9% |

ttm_capex/fcf NULL이 높은 이유: 원본 quarterly_financials에서 capex 수집률 자체가 낮음 (일부 기업 XBRL 태그 미사용).


## 6. 알려진 NULL 갭 구간

4분기 윈도우 안에 NULL 분기가 하나라도 포함되면 해당 anchor의 flow TTM은 NULL이 된다. 대표 사례:

| 종목 | NULL 갭 구간 | 이유 |
|---|---|---|
| SATS | 2021Q4 ~ 2023Q3 | 2021Q4·2022Q4 이상값 NULL 처리 (아래 참조) |
| 초기 상장사 | 상장 후 첫 3분기 | 4분기 윈도우 미충족 |
| 일부 2010~2012 | 해당 구간 | XBRL 초기 태그 미신고 |


## 7. 데이터 이상값 수정 이력

전수 조사 결과 다음 종목의 Q4 연간 매출이 분기값에 혼입된 것을 확인하고 NULL 처리했다.

### 수정 내용

| 종목 | 분기 | 수정 컬럼 | 이상값 | 정상 분기 수준 |
|---|---|---|---|---|
| SATS | 2021Q4, 2022Q4 | revenue, operating_income, net_income, cfo, capex | 17~18B | ~500M |
| CHRW | 2016Q4 | revenue | 11.4B | ~570M |
| JCI | 2014Q4, 2015Q4 | revenue | 29~31B | ~2.5B |

### 이상값 원인

SEC EDGAR XBRL 연간 파일링(10-K)의 FY 누적 매출이 Q4 단일 분기값으로 수집되는 아티팩트. `ytd_to_single_quarter()` 변환 시 해당 분기의 Q3 YTD가 단분기값(누적 아님)으로 저장되어 있어 Q4 = FY - Q3_단분기 ≈ FY 전체가 되는 구조.

### 탐지 방법

```python
# Q4 revenue가 같은 FY Q1~Q3 평균의 10배 이상인 경우
ratio = q4_revenue / avg(q1~q3_revenue)
if ratio >= 10: anomaly
```

향후 분기 재수집 시 동일 방법으로 검증 권장.


## 8. total_equity 음수 종목

약 70개 종목에서 total_equity가 음수로 나타난다. 이는 데이터 오류가 아니라 **공격적 자사주 매입**으로 누적 손실이 자본을 초과한 실제 회계 현실이다.

대표 종목: AZO, VRSN, HCA, PM, DPZ, TDG, MCD, SBUX, YUM, MAR, HLT, BA

이 종목들의 부채비율(D/E), ROE 계산 시 주의 필요.


## 9. shares_diluted 불연속 구간

주식분할 시점에 shares_diluted가 급등하는 불연속이 발생한다. 이는 `prefer_earliest_filed=True` 설계상 소급조정을 적용하지 않기 때문으로 정상 동작이다.

| 종목 | 분할 시점 | 배율 |
|---|---|---|
| AAPL | 2014Q3, 2020Q4 | 7:1, 4:1 |
| AMZN | 2022Q2 | 20:1 |
| GOOGL/GOOG | 2022Q4 | 20:1 |
| NVDA | 2022Q2, 2025Q2 | 4:1, 10:1 |
| CMG | 2024Q2 | 50:1 |

EPS·주당 FCF 등 per-share 지표를 시계열로 비교할 때 분할 전후 불연속 주의.
