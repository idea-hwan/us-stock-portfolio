# 성장률 계산 명세

## 1. 개요

`ttm_valuation.db`의 TTM 시계열을 읽어 지표별 분기 성장률과 1y/2y/4y/8y 누적 CAGR을 계산해 `ttm_growth.db`에 저장한다.

- **입력**: `data/ttm_valuation.db` → `ttm_financials`
- **출력**: `data/ttm_growth.db` → `ttm_growth_series`
- **스크립트**: `scripts/compute_growth.py`
- **대상**: `stock_universe.csv`의 `exclude_analysis=False` 종목 (약 329개)


## 2. 계산 지표

| 접두사 | 원천 컬럼 | 설명 |
|--------|-----------|------|
| `rev` | `ttm_revenue` | TTM 매출 |
| `op` | `ttm_op_income` | TTM 영업이익 |
| `ni` | `ttm_net_income` | TTM 순이익 |
| `cfo` | `ttm_cfo` | TTM 영업현금흐름 |
| `capex` | `ttm_capex` | TTM 자본적지출 |
| `fcf` | `ttm_fcf` | TTM 잉여현금흐름 |


## 3. 성장률 계산 로직

### 3-1. 분기성장률 (`{prefix}_cum_geom_pct`)

TTM 시계열을 anchor_term 오름차순으로 정렬 후, 직전 양수 앵커 기준 기하평균 성장률을 계산한다.

- 값이 양수일 때만 앵커를 갱신한다.
- 0 이하 / NULL 구간은 성장률을 NULL로 두고 앵커를 유지한다 (흑자 복귀를 기다림).
- 흑자 복귀 시: `(현재값 / 앵커값)^(1/span) - 1`
- 연속 양수 구간(span=1): 단순 QoQ% = `TTM(t) / TTM(t-1) - 1`

```
예시 (BA 영업이익):
  2021Q3: 1,269M  → 앵커 설정
  2021Q4 ~ 2025Q3: 적자  → 성장률 NULL, 앵커 유지
  2025Q4: 4,281M  → span=17, pct=(4281/1269)^(1/17)-1 = 7.41%
```

`{prefix}_span_q`: 앵커에서 현재까지 분기 수.

### 3-2. 분기성장률과 TTM YoY의 관계

연속 양수 구간에서 4분기 QoQ가 텔레스코핑(telescoping)되면:

```
1y 창 product = TTM(t) / TTM(t-4)
```

즉 `1y_mcum ≈ (TTM 현재 / TTM 1년 전)^(1/4) - 1` — 분기당 CAGR 형태.

### 3-3. 창 누적 CAGR (`{prefix}_geom_{창}_mcum`)

| 창 이름 | 분기 수 (k) |
|---------|-------------|
| `1y` | 4 |
| `2y` | 8 |
| `4y` | 16 |
| `8y` | 32 |

각 anchor_term i에 대해:

1. 창 `[i-k+1, i]`에서 분기성장률을 가져온다. 데이터 범위 밖(인덱스 < 0)은 g=0으로 처리.
2. 데이터 범위 내 분기성장률이 **전부 NULL**이면 → NULL.
3. `product = ∏(1 + g_t)`. NULL인 분기는 g=0으로 대입.
4. product ≤ 0이면 → NULL.
5. `mcum = (product^(1/k) - 1) × 100` — k는 항상 고정 (4/8/16/32).

### 3-4. 보조 카운트

| 컬럼 패턴 | 의미 |
|-----------|------|
| `{prefix}_{창}_q_empty` | 창 안에서 분기성장률이 NULL인 분기 수 |
| `{prefix}_{창}_q_minus` | 창 안에서 TTM 원시값이 음수인 분기 수 |

스크리닝 시 신뢰도 필터로 사용 (`q_minus`가 많으면 성장률 해석 주의).


## 4. DB 스키마 (`data/ttm_growth.db`)

`ttm_growth_series` 테이블 — PK: `(ticker, anchor_term)`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| ticker | TEXT | 종목 티커 |
| anchor_term | TEXT | TTM 기준 분기 (예: 2026Q1) |
| computed_at | TEXT | 계산 일시 (UTC) |
| `{prefix}_cum_geom_pct` | REAL | 분기 성장률 (%) |
| `{prefix}_span_q` | INTEGER | 앵커~현재 분기 수 |
| `{prefix}_geom_1y_mcum` | REAL | 1y (4분기) 창 CAGR (%) |
| `{prefix}_1y_q_empty` | INTEGER | 1y 창 내 NULL 분기 수 |
| `{prefix}_1y_q_minus` | INTEGER | 1y 창 내 음수 분기 수 |
| `{prefix}_geom_2y_mcum` | REAL | 2y (8분기) 창 CAGR (%) |
| … | … | (4y·8y 동일 패턴) |

`{prefix}` = `rev` / `op` / `ni` / `cfo` / `capex` / `fcf`


## 5. 실행 방법

```bash
# 분석 대상 전체 (exclude_analysis=False, 기본값)
python scripts/compute_growth.py

# 특정 종목만
python scripts/compute_growth.py --ticker AAPL --ticker MSFT

# 제외 섹터 포함 전체
python scripts/compute_growth.py --all
```

TTM 재계산 후에는 재실행 (upsert 방식).


## 6. 데이터 현황 (2026-06-19 기준)

| 항목 | 값 |
|------|----|
| 총 행수 | 18,988 |
| 종목수 | 329 |
| anchor_term 범위 | 2010Q4 ~ 2027Q1 |

### NULL 비율 (분기성장률 기준)

| 지표 | NULL 비율 | 주요 원인 |
|------|-----------|-----------|
| rev | 6.4% | 종목별 최초 행 (앵커 없음) + 매출 NULL |
| op | 8.7% | 적자 구간 (영업손실) |
| ni | 8.3% | 적자 구간 (순손실) |
| cfo | 5.8% | CFO NULL |
| capex | 7.2% | capex NULL 원본 비율 자체가 높음 |
| fcf | 12.5% | FCF 음수 비율 높음 (capex > CFO 기업) |

**FCF NULL이 높은 이유**: TTM FCF 원시값이 음수인 행이 ~5% (성장 투자 기업 등 capex > CFO). 음수 구간은 앵커에서 제외되므로 성장률 NULL이 누적됨.


## 7. 스크리닝 활용 예시

```sql
-- 최신 분기 기준 영업이익 성장 가속 종목 (1y > 2y > 4y, 모두 양수)
SELECT ticker, anchor_term,
       op_geom_1y_mcum, op_geom_2y_mcum, op_geom_4y_mcum
FROM ttm_growth_series
WHERE anchor_term = '2026Q2'
  AND op_geom_1y_mcum > 0
  AND op_geom_2y_mcum > 0
  AND op_geom_4y_mcum > 0
  AND op_geom_1y_mcum > op_geom_2y_mcum
  AND op_geom_2y_mcum > op_geom_4y_mcum
  AND op_1y_q_minus = 0
ORDER BY op_geom_1y_mcum DESC;
```
