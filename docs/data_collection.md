# 데이터 수집 명세

## 1. 유니버스 정의

### S&P 500 유니버스
- **소스**: Wikipedia S&P 500 구성 종목 (또는 동등한 공개 소스)
- **파일**: `stock_universe.csv`
- **업데이트 주기**: 연 1회 (구성 종목 변경 반영)


## 2. 종목 마스터 (`stock_universe.csv`)

| 컬럼 | 설명 | 소스 |
|---|---|---|
| ticker | 티커 심볼 | - |
| company | 회사명 | yfinance |
| sector | 섹터 | yfinance |
| industry | 산업군 | yfinance |
| country | 국가 | yfinance |
| market_cap | 시가총액 (USD) | yfinance |
| market_cap_str | 시가총액 포맷 문자열 | 가공 |
| fiscal_year_end_month | 회계연도 종료 월 (1~12) | SEC EDGAR |
| biz_model | 사업 모델 요약 | yfinance |
| exclude_analysis | 분석 제외 여부 (True/False) | `config.py` 기준 |

`fiscal_year_end_month`는 SEC EDGAR `companyfacts` API의 `fiscalYearEnd` 필드에서 수집한다.  
`exclude_analysis`는 `scripts/config.py`의 `EXCLUDED_SECTORS`를 기준으로 자동 설정된다.


## 3. 분석 제외 섹터 (`scripts/config.py`)

기업 펀더멘털 분석에 표준 지표(revenue·operating_income·net_income·CFO)가 적합하지 않은 섹터는 수집은 하되 **분석에서 제외**한다.

| 섹터 | 제외 이유 |
|---|---|
| Financial Services | 매출·영업이익 개념 상이, 레버리지가 사업 모델. 순이익·CFO 중심 |
| Real Estate | REIT는 FFO 기준 밸류에이션, 일반 이익 지표 부적합 |
| Energy | 원자재 가격 종속, 기업 펀더멘털보다 commodity cycle 영향 큼 |
| Basic Materials | 마이닝(FCX·NEM 등) 포함, 동일 이유 |
| Utilities | 규제독점, 수익률이 정부 규제로 결정, rate base 밸류에이션 |

- 분석 대상: 약 330개 / 제외: 약 173개 (전체 503개 기준)
- 모든 분석 스크립트는 `from config import EXCLUDED_SECTORS`로 일관 적용


## 4. 분기 재무 데이터

- **소스**: SEC EDGAR XBRL API (`https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json`)
- **무료, API 키 불필요** (User-Agent 헤더 필요)

### 수집 항목

| 항목 | XBRL 태그 (우선순위) | 비고 |
|---|---|---|
| revenue | RevenueFromContractWithCustomerExcludingAssessedTax, SalesRevenueNet, Revenues, RevenueFromContractWithCustomerIncludingAssessedTax, SalesRevenueGoodsNet, NetRevenues, OilAndGasRevenue, GasGatheringTransportationMarketingAndProcessingRevenue, RegulatedAndUnregulatedOperatingRevenue | 에너지/유틸리티 섹터 특화 태그 포함 |
| operating_income | OperatingIncomeLoss, IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest, IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments, IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic | OperatingIncomeLoss 미신고 기업은 세전이익을 대용 |
| net_income | NetIncomeLoss, ProfitLoss, NetIncomeLossAvailableToCommonStockholdersBasic | ProfitLoss = 비지배주주 포함 총이익; AvailableToCommonStockholders = 우선주 배당 차감 후 |
| cfo | NetCashProvidedByUsedInOperatingActivities, NetCashProvidedByUsedInOperatingActivitiesContinuingOperations | |
| capex | PaymentsToAcquirePropertyPlantAndEquipment, PaymentsToAcquireProductiveAssets, PaymentsToAcquireOtherPropertyPlantAndEquipment, PaymentsToAcquireOilAndGasPropertyAndEquipment, PaymentsToAcquireOilAndGasEquipment | |
| total_assets | Assets | 연간(Q4)만 저장 |
| total_equity | StockholdersEquity, StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest | 연간(Q4)만 저장 |
| shares_diluted | WeightedAverageNumberOfDilutedSharesOutstanding, WeightedAverageNumberOfSharesOutstandingBasic, CommonStockSharesOutstanding | 연간(Q4)만 저장. EDGAR 없으면 yfinance로 보정 (`patch_shares_yfinance.py`) |

### 분기 레이블: 회계연도 기준

분기 레이블 `{year}Q{q}`은 **회계연도 기준**으로 부여한다.

```
end_year  = end_date 연도
end_month = end_date 월
if fp == "FY":
    year = end_year
else:
    year = end_year + 1 if end_month > fy_end_month else end_year
```

- 예: AAPL(9월 결산) FY2026 Q1은 Oct~Dec 2025에 해당. end_date=2025-12, end_month(12) > fy_end_month(9) → year=2026 → **2026Q1**
- 12월 결산 회사는 calendar year = fiscal year이므로 기존과 동일

이 방식으로 회계연도가 다른 회사끼리 period_key가 섞이는 문제(cross-FY mixing)를 방지한다.

### 수집 규칙

| 항목 유형 | 선택 기준 |
|---|---|
| Flow (revenue·net_income·cfo·capex 등) | YTD 누적값 중 가장 큰 값 선택 (`prefer_ytd=True`) → `ytd_to_single_quarter()`로 단분기 변환 |
| Snapshot (total_assets·total_equity·shares_diluted) | 연간 10-K에서만 수집 |
| shares_diluted | 가장 먼저 신고된 값 선택 (`prefer_earliest_filed=True`) — 주식분할 소급조정 방지 |

### 음수값 처리

- **revenue**: 항상 양수여야 하므로 음수는 NULL 저장 (YTD 뺄셈 artifact)
- **capex**: 항상 양수여야 하므로 음수는 NULL 저장 (동일 이유)
- **net_income·cfo·operating_income**: 실제 손실 가능 → 음수 그대로 유지

### DB 스키마 (`data/stocks.db`)

`quarterly_financials` 테이블:

| 컬럼 | 타입 | 설명 |
|---|---|---|
| ticker | TEXT | 종목 티커 |
| term | TEXT | 분기 레이블 (예: 2026Q1) — 회계연도 기준 |
| fiscal_year_end_month | INTEGER | 회계연도 종료 월 (1~12) |
| revenue | INTEGER | 매출 (USD). 음수 시 NULL |
| operating_income | INTEGER | 영업이익 |
| net_income | INTEGER | 순이익 |
| cfo | INTEGER | 영업현금흐름 |
| capex | INTEGER | 자본적지출. 음수 시 NULL |
| total_assets | INTEGER | 총자산 (Q4만) |
| total_equity | INTEGER | 총자본 (Q4만) |
| shares_diluted | INTEGER | 희석 가중평균 주식수 (Q4만) |
| updated_at | TEXT | 수집 일시 (UTC) |
| PRIMARY KEY | (ticker, term) | |

### 알려진 NULL 한계

| 항목 | 대상 | NULL 수준 | 이유 |
|---|---|---|---|
| total_assets·total_equity·shares_diluted | 전체 | ~50% | Q4(연간)만 수집 — 설계상 정상 |
| revenue | Financial Services | ~13% | 은행/보험은 매출 개념 상이 (이자수익·보험료 등) |
| operating_income | Real Estate | ~10% | REIT는 임대료 구조, 표준 태그 미사용 |
| 모든 항목 | 2010~2015 초기 | 일부 갭 | EDGAR XBRL 의무화 초기, 태그 미표준화 |
| revenue | FDXF | 전체 | EDGAR CIK 없음 (수집 불가) |


## 5. 수집 스케줄 (연 4회)

| 시점 | 커버 분기 | SEC 마감 기준 |
|---|---|---|
| 3월 초 | Q4 / 연간 (10-K) | 대형사 60일 이내 (~3/1) |
| 5월 중순 | Q1 (10-Q) | 40일 이내 (~5/10) |
| 8월 중순 | Q2 (10-Q) | (~8/10) |
| 11월 중순 | Q3 (10-Q) | (~11/10) |


## 6. 스크립트 구성

| 스크립트 | 역할 |
|---|---|
| `config.py` | 공통 상수 (EXCLUDED_SECTORS 등) — 모든 스크립트 공유 |
| `update_universe.py` | stock_universe.csv 갱신 (연 1회 또는 S&P500 리밸런싱 후) |
| `collect_financials.py` | EDGAR에서 분기 재무 수집 → stocks.db upsert |
| `patch_shares_yfinance.py` | shares_diluted NULL 종목을 yfinance로 보정 (필요 시) |
| `check_quality.py` | 수집 후 데이터 품질 검증 |
| `build_summary_table.py` | 시가총액·수익률·PER 요약표 생성 |

### 일반적인 수집 절차 (분기마다)

```bash
python scripts/collect_financials.py      # ~10~15분
python scripts/check_quality.py           # 이상 없으면 분석 진행
```

### 유니버스 변경 시 (연 1회)

```bash
python scripts/update_universe.py
python scripts/collect_financials.py
python scripts/check_quality.py
```

### shares_diluted 보정 (필요 시)

```bash
python scripts/patch_shares_yfinance.py
```


## 7. 품질 체크 해석

```bash
python scripts/check_quality.py
```

| 경고 유형 | 의미 | 대응 |
|---|---|---|
| NULL 과다 없음 | 정상 | 분석 진행 |
| total_assets 50% NULL | 정상 (Q4만 수집) | 무시 |
| NULL 과다 발생 (flow 지표) | 최근 분기 수집 실패 or 새 XBRL 태그 필요 | 해당 종목 확인 |
| 급변 (2015 이전) | XBRL 초기 태그 혼용 아티팩트 | 무시 가능 |
| 급변 (최근) | 실제 이상값 가능성 | 해당 종목 확인 |
| 수집 누락 | CIK 없음 or EDGAR 미등록 | 해당 종목 확인 |
