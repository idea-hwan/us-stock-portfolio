# 작업 현황 메모 (2026-06-22)

## 지금까지 만든 것

```
EDGAR 재무 데이터
    └─ compute_ttm.py        → data/ttm_valuation.db   (TTM 손익/현금흐름)
    └─ compute_growth.py     → data/ttm_growth.db      (CAGR 성장률)
    └─ compute_valuation.py  → data/valuation.db       (P/E·P/S·P/FCF·P/OP 배수)

yfinance 주가 데이터
    └─ collect_prices.py     → data/prices.db          (일별 수정주가, SPY 포함)

위를 합쳐서
    └─ compute_returns.py    → data/returns.db         (선행수익률 + SPY alpha)
    └─ classify_stocks.py   → data/analytics/*.csv    (종목 분류 스냅샷)
```

---

## DB 파일 요약

| 파일 | 행수 | 내용 |
|------|------|------|
| `data/ttm_valuation.db` | ~20k | TTM 재무 (매출/영업이익/순이익/CFO/FCF) |
| `data/ttm_growth.db` | ~20k | 1y/2y/4y 성장률 |
| `data/valuation.db` | 18,925 | 분기별 밸류에이션 배수 (20d·4y 평균) |
| `data/prices.db` | ~155만 | 일별 수정주가 (330종목 + SPY) |
| `data/returns.db` | 18,790 | 분기별 선행수익률 12m/15m/18m + SPY alpha |

---

## 종목 분류 구조

**4개 버킷** (`data/analytics/{bucket}_stocks.csv`)

| 버킷 | 종목수 | 기준 |
|------|-------|------|
| `cyclical` | 54 | `data/cyclical_universe.txt` 수동 리스트 |
| `growth` | 63 | 32분기 연속 영업흑자 + 영업이익 2y CAGR > 4y CAGR |
| `value` | 131 | 32분기 연속 순이익 흑자 (성장 조건 미달) |
| `unclassified` | 81 | 나머지 |

**cyclical 세부 업종** (`cyclical_type` 컬럼)

| 업종 | 종목수 | 대표 종목 |
|------|-------|---------|
| `semiconductor` | 19 | MU, AMAT, LRCX, KLAC, AMD, INTC, STX, WDC, DELL ... |
| `transport` | 11 | DAL, UAL, FDX, UPS, UNP, CSX, ODFL ... |
| `housing` | 6 | DHI, PHM, LEN, NVR, HD, LOW |
| `auto` | 4 | GM, F, TSLA, APTV |
| `leisure` | 11 | RCL, CCL, MAR, HLT, LVS, MGM, BKNG, ABNB ... |
| `industrial` | 3 | CAT, DE, PCAR |

---

## 업종별 시뮬 결과 (alpha_12m, anchor ≤ 2025Q2 기준)

| 업종 | 중앙값 | 양수비율 | 판정 |
|------|-------|---------|-----|
| housing | +4.0% | 54.8% | ✓ 알파 있음 |
| semiconductor | +2.3% | 52.4% | ✓ 알파 있음 (평균은 왜곡 큼) |
| industrial | -2.8% | 45.2% | △ |
| transport | -1.5% | 47.5% | △ (ODFL만 +15%) |
| auto | -6.9% | 42.4% | ✗ (TSLA 제외 시 전부 음수) |
| leisure | -2.4% | 46.7% | ✗ |

> 완전한 12m 수익률 필터: `anchor_term <= '2025Q2'`  
> 15m 완전: `<= '2025Q1'`, 18m 완전: `<= '2024Q4'`

---

## 팩터 분석 완료 현황 (2026-06-22)

### cyclical 진입 팩터 — 완료
`docs/cyclical_classification.md` 참조.  
세 축: 이익/매출 성장률 + capex 방향 + 밸류에이션 배수 vs 4y 평균.  
업종별 최강 조합 확정 (semiconductor 별도 로직 포함).

### growth 진입 팩터 — 완료
`docs/bucket_factor_analysis.md` 참조.  
핵심: 이익 일시 역성장 + 매출 가속 (투자·비용 선집행 구간 매수).

### value 팩터 — 완료 (제외 필터로 활용)
타이밍 진입 팩터 없음. 매출 2y 역성장 / P/S+영업역성장 / P/OP+영업역성장 = 회피 조건.

---

## 스크리닝 스크립트 완료 (2026-06-22)

`scripts/screen_candidates.py` — 종목별 최신 스냅샷에 팩터 적용, 매수 후보 출력.  
결과: `data/analytics/screen_results.csv` (248행)

현재 신호 발생 종목 (2026-06-22 기준):
- ★ ABNB (leisure): val+capex+op 3조건 동시
- ○ BKNG (leisure): val 충족
- ○ DECK (retail): val 충족
- ○ MCHP, ON (semiconductor): op 2y 역성장 — 단, 주가 이미 +50~130% 선반영

---

## 다음에 할 것

### 1. 탑 20 대기업 현황 대시보드
주요 대기업 ~20개를 골라 각 종목이 현재 어느 상태에 있는지 한눈에 보는 뷰.  
버킷(growth/value/cyclical) + 사이클 위치 + 핵심 팩터 신호 조합.

표시 내용 (종목별):
- **버킷**: growth / value / cyclical(업종)
- **이익 모멘텀**: op 1y/2y 성장률 방향 (회복 중 / 역성장 중 / 가속 중)
- **밸류에이션 위치**: 현재 배수가 4y 평균 대비 싼지 비싼지
- **팩터 신호**: 해당 버킷/업종 진입 팩터 충족 여부
- **주가 최근 흐름**: 3개월/1년 수익률

탑 20 후보: AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, BRK-B, JPM, V,  
UNH, JNJ, LLY, AVGO, MA, XOM, HD, PG, COST, MCD (시총 기준)

→ 스크립트: `scripts/top20_dashboard.py`  
→ 출력: 콘솔 테이블 or HTML 리포트

### 2. 스냅샷 CSV에 SPY alpha 추가 (작은 작업)
`classify_stocks.py`의 `build_snapshot()`이 `returns.db`를 참조해서  
`alpha_12m/15m/18m` 컬럼을 CSV에 포함.  
→ 지금은 CSV에 `ret_12m`만 있고 SPY 비교 없음.

---

## 판단로직 패널 방법론 — PIT 보정 + 신호 단순화 (2026-07-02)

### 문제: 생존편향
`classify_stocks.py`가 growth/value 라벨을 "종목별 최신 anchor_term 기준"(즉 현재 시점에서 역산)으로 한 번만 판정해서 그 종목의 전체 과거 히스토리에 일괄 적용하고 있었음. 이러면 "지금 살아남아서 계속 잘하고 있는 종목"의 과거 전체를 백테스트에 쓰게 돼서 결과가 낙관적으로 부풀려짐(생존편향).

### 수정: point-in-time 롤링 재판정
- 각 분기 시점마다 "그 시점까지의 데이터"만으로 연속 흑자 조건을 롤링 재판정하는 방식으로 변경 (`data/analytics/pit_buckets.db`의 `pit_buckets`/`pit_buckets16` 테이블).
- 원본 재무 데이터(`ttm_financials`)가 2010Q4부터 시작 — 32분기(8년) 조건은 검증 가능 시작점이 2018Q3까지 밀리고 표본도 작아짐(growth n≈5,938).
- **16분기(4년)로 완화** → 검증 시작점 2013Q4, 표본 거의 2배(n≈10,605). `classify_stocks.py`의 `MIN_Q`도 32→16으로 변경해 라이브 종목 분류에도 반영(growth 232→266종목, value →255종목).

### 발견: 매그니피센트7 쏠림
32분기 기준(2018~2026)으로 계산했을 때 베이스라인(무신호 평균) alpha가 전부 마이너스로 나와서 이상해 보였음. 원인은 2023~2025년이 표본의 큰 비중을 차지하는데, 이 기간 SPY(시총가중)가 소수 초대형주로 끌어올려져서 동일가중 성장/가치주 평균이 지수에 뒤처졌기 때문(계산 버그 아님). 16분기로 완화해 2013년 이후 데이터를 더 포함시키니 베이스가 거의 0%로 정상화됨.

### 신호 단순화
16분기 PIT 기준으로 재검증한 결과 ★★(강한 조합) 신호만 베이스 대비 유의미하고, ★/○ 단독 신호는 베이스보다 못하거나 비슷 — 전부 제거하고 매수 신호를 **단일 조건**으로 축소:
- 매수: `rev2y가속 and P/OP저평가 and CAPEX 1y↓` (growth/value 동일)
- 매도: `rev1y역성장 and (P/OP고평가+CAPEX↑ or P/FCF고평가+CAPEX가속)` (growth/value 동일, 기존 ▼▼×2+▼ 통합)
- value의 회피 플래그(✗, 매출2y역성장)도 일관성을 위해 제거 — 매수/매도 각 하나씩만 유지.
- 신호 심볼을 ★★→▲(매수, 초록), 매도는 ▼(빨강)로 통일. 사이클 버킷은 업종별 세부 조건이 남아있어 기존 ★/▼▼ 체계 유지.

### 남은 이슈
- 포트폴리오 회전 시뮬(`scripts/simulate_growth_portfolio.py`)은 아직 구 방식(생존편향 있는 growth_stocks.csv) 기준 — 16분기 PIT 유니버스로 재실행 필요.

---

## Cyclical 유니버스 생존편향 발견 및 수정 (2026-07-02)

### 문제 발견
`data/cyclical_universe.txt` 파일에 "제외 원칙 (2026-06-22 리뷰)"라는 주석으로 다음 종목들이 실적 기반 사유로 제외돼 있었음: 카지노(LVS/MGM/WYNN, "경기순환 아님"), 크루즈(RCL/CCL/NCLH, "알파 없음"), 의류(RL/TPR, "구조적 업황 하락"), BBY(동일), 반도체 SWKS("사이클 소외"), capital_goods 저성과주(SWK/EMR/MMM/ROK, 각각 개별 사유). "알파 없음"이라는 표현 자체가 사후적으로 백테스트 결과를 보고 종목을 뺐다는 증거 — 전형적인 생존편향(cherry-picking).

### 검증
제외 종목들을 다시 넣고 베이스(median alpha_12m) 비교:

| 업종 | 기존(제외) | 제외종목만 | 통합 |
|------|-----------|-----------|------|
| leisure | +3.3% | −6.0% | **−1.9%** (부호 반전) |
| retail | +0.8% | −8.6% | **−1.7%** (부호 반전) |
| capital_goods | +4.1% | −3.2% | +2.8% |
| semiconductor | +6.2% | −9.9%(SWKS만) | +5.0% |

leisure·retail은 베이스가 통째로 뒤집힐 만큼 영향이 컸음.

### 조치
- 방산(LMT/NOC/GD/HII/LHX)·농기계(DE) — 경기순환과 다른 구조적 동인이라 **개념적 제외로 유지**.
- 카지노·크루즈·의류·BBY·SWKS·capital_goods 저성과주 — **전부 원복**.
- `classify_stocks.py` 재실행 → `cyclical_stocks.csv` 재생성 (81→95종목).
- 판단로직 패널 Cyclical 섹션 전체 재계산.

### 특히 주목할 결과: leisure ★★ 신호 완전 반전
원복 전: "val저평가 + CAPEX확대 + 영업흑자" 조합(★★)이 12m+6.5%/18m+0.8%/24m+35.9%로 강한 매수 신호로 보였음.
원복 후: 같은 조합이 12m−6.4%/18m−6.9%/24m−27.3%로 **명백한 가치함정**으로 판명. 카지노주(LVS/WYNN 등)가 마카오 규제·수요 붕괴 국면에서 "저평가+CAPEX확대(신규 리조트 투자 지속)"를 동시 충족했던 경우가 다수 — 반등 없이 손실만 키움. 대신 저평가 단독(★) 신호가 베이스 대비 견고한 edge를 보임(12m+7.3%p, 18m+20.8%p).

→ 교훈: 수동 큐레이션 유니버스는 "왜 이 종목을 뺐는가"를 반드시 감사해야 함. 사후적 성과 기반 제외 사유("알파 없음", "구조적 하락")는 생존편향의 강한 신호.

---

## Energy·Basic Materials·Utilities 섹터 편입 (2026-07-02)

### 문제 발견
Cyclical 유니버스의 construction/housing 종목수가 너무 적어(6개) 감사하던 중, `data/stock_universe.csv`의 `exclude_analysis` 플래그가 **Financial Services·Utilities·Real Estate·Energy·Basic Materials 5개 섹터 전체**(101+72=173종목)를 분석 유니버스에서 통째로 빼고 있던 것을 발견. 건설 자재주(MLM/VMC/CRH)가 Basic Materials 섹터라는 이유만으로 통째로 누락돼 있었음.

### 판단
- Financial Services(70)·Real Estate(31) — 은행/보험/REIT는 영업이익·순이익 기반 회계 구조가 이 방법론과 근본적으로 안 맞음 → **계속 제외**.
- Energy(21)·Basic Materials(20)·Utilities(31) 총 72종목 — 회계 구조상 호환성 문제 없음. Energy·Materials는 원자재 사이클 변동성이 커서 **Cyclical 버킷 후보**, Utilities는 규제 요금 기반의 경기방어적 성격이라 **Growth/Value 자동 분류에 맡김**. → **편입 결정**.

### 조치
1. `stock_universe.csv`에서 위 3개 섹터 72종목의 `exclude_analysis`를 False로 변경.
2. 가격 수집(`collect_prices.py`, 신규 72종목 전체 히스토리 2006~ 34.5만행) → TTM(`compute_ttm.py`) → 성장률(`compute_growth.py`) → 밸류에이션(`compute_valuation.py`) → 선행수익률(`compute_returns.py`) 전체 파이프라인 401종목으로 재실행.
3. `cyclical_universe.txt`: 골재·시멘트(MLM/VMC/CRH)만 construction에 수동 편입, 나머지는 growth/value/unclassified 자동 분류.
4. `classify_stocks.py`, `pit_buckets.db`(32Q/16Q 모두) 재생성 — growth_pit16 6,872→13,862행, value_pit16 6,531→13,312행.
5. 판단로직 패널의 Growth/Value 매수·매도 시뮬 전체, Cyclical construction 섹션 재계산.

### 결과 — Growth/Value 베이스가 더 마이너스로, 신호 edge는 유지
| | 이전(329종목) | 이후(401종목) |
|---|---|---|
| Growth 베이스 12m/18m/24m | −0.8%/−0.7%/−0.5% | −1.4%/−1.7%/−2.1% |
| Growth ▲ 신호 12m/18m/24m | +5.4%/+4.9%/+4.7% | +2.6%/+4.4%/+2.7% |
| Growth ▲ 베이스 대비 격차 | +6.2%p/+5.6%p/+5.2%p | +4.0%p/+6.1%p/+4.8%p |
| Value 베이스 12m/18m/24m | −0.7%/−0.5%/−0.4% | −1.2%/−1.5%/−1.8% |
| Value ▲ 신호 12m/18m/24m | +8.5%/+11.0%/+8.3% | +7.9%/+10.3%/+7.4% |
| Value ▲ 베이스 대비 격차 | +9.2%p/+11.5%p/+8.7%p | +9.1%p/+11.8%p/+9.2%p |

Utilities·Energy·Materials가 growth/value 자동 분류에 섞여 들어가며 베이스 자체는 더 낮아졌지만(SPY 대비 상대적으로 부진했던 기간이 반영), ▲ 신호의 베이스 대비 초과수익(edge)은 Growth·Value 모두 거의 그대로 유지 — 특히 Value는 격차가 거의 변하지 않을 만큼(9.2%p→9.1%p 등) 신호가 견고함을 재확인.

### 결과 — construction 24m 역전 현상 해소
MLM·VMC·CRH 편입 전(6종목)에는 3중 저평가(★) 신호가 24m에서 베이스보다 낮아지는(+13.4% vs +24.5%) 이상 현상이 있었음(n=15 소표본 노이즈로 추정). 9종목으로 확장 후 이 역전이 사라지고 전 구간(12/18/24m) 신호가 베이스를 뚜렷이 상회(+31.9%/+38.8%/+33.7% vs 베이스 +7.7%/+10.6%/+14.9%)하는 것으로 정리됨.

### 추가 반영: 전업종 공통 매도 신호 재계산
construction 3종목 편입으로 cyclical 전체 모집단이 95→98종목이 돼 "전업종 공통 매도 신호"(rev가속+PE고평가+FCF↓/CAPEX↓)도 재계산함. 결과는 사실상 동일 — 베이스 3m+0.7%/6m+1.0%/9m+1.3%, FCF↓ 조합 3m−1.5%/6m−2.0%/9m−0.8%(빈도4.2%), CAPEX↓ 조합 3m−0.3%/6m−1.6%/9m−1.8%(빈도4.4%, 원래보다 더 강함으로 확인). 이걸로 판단로직 패널의 **정적 시뮬(백테스트 테이블) 전체가 401종목/16Q PIT/생존편향 수정 기준으로 완전히 최신화됨.**

### 남은 이슈
- Cyclical의 semiconductor/leisure/retail/capital_goods/aerospace_defense/auto/transport는 "누락된 후보가 있는지"를 아직 감사하지 않음 (이번엔 construction/housing만 종목수가 유독 적다는 점에서 감사가 시작됨) — 필요 시 추가 검토.
- 포트폴리오 회전 시뮬(`scripts/simulate_growth_portfolio.py`, 동적 시뮬)은 여전히 구 유니버스(생존편향 있는 329종목, 32Q 비-PIT) 기준으로 1회만 실행됨 — 16Q PIT + 401종목 확장 유니버스로 재실행 필요.

---

## Cyclical 2차 확장 — GICS 산업 매칭 감사 + Energy/Materials 신설 (2026-07-02)

### 문제 발견 1: "growth/value 중복이면 cyclical 제외"는 잘못된 로직
construction/housing만 종목수가 적다는 점에서 시작한 감사를 semiconductor/transport/auto/aerospace_defense/capital_goods/retail까지 확장. 처음엔 "NVDA/AVGO 등은 이미 growth로 강하게 잡히니 cyclical에서 뺴는 게 낫다"는 논리로 후보를 걸러냈으나, 사용자가 정정: **버킷은 비배타적이고 중복 신호가 오히려 정보량이 많다 — growth/value 소속 여부는 cyclical 편입 여부와 무관한 판단 기준**. GICS 산업/섹터 태그가 기존 cyclical_type과 일치하면 서사로 걸러내지 말고 편입해야 함.

### 문제 발견 2: 할인점 등 진짜 개념적 불일치는 구조적 근거로 구분
"방어적으로 보인다"는 서사로 뺐던 ORLY/AZO/GPC(Auto Parts)·CVNA(Auto & Truck Dealerships)는 실제로는 GICS **Consumer Cyclical** 섹터 — 잘못된 배제였음. 반면 WMT/COST/TGT/DG/DLTR(Discount Stores)는 GICS **Consumer Defensive** 섹터로 애초에 다른 카테고리 — 이건 서사가 아니라 구조적으로 다른 분류라 계속 제외.

### 조치 — 기존 카테고리 보강 (98→126종목)
| 업종 | 추가 | 근거 |
|---|---|---|
| semiconductor | NVDA/AVGO/TXN/ADI/MPWR | 동일 GICS Semiconductors 산업 |
| transport | EXPD | 동일 산업(Integrated Freight & Logistics) |
| auto | CVNA/ORLY/AZO/GPC | GICS Consumer Cyclical 동일 섹터 |
| aerospace_defense | AXON | 동일 산업(단, 연방 국방예산 직접의존 아님 — 방어적 성격 약함) |
| capital_goods | PCAR/VRT/OTIS/XYL/IEX/NDSN/PNR/AOS | Industrials 동일 계열 |
| construction | J(Jacobs) | Engineering & Construction |
| retail | LULU/AMZN/DASH/EBAY/TJX/ROST/CASY/TSCO | GICS Consumer Cyclical 동일 섹터 |

데이터 이력이 너무 짧은 Q(Qnity Electronics, 2분기)·FDXF(FedEx Freight, 0분기)는 서사가 아닌 순수 데이터 부족으로 보류.

### 조치 — Energy/Materials 신설 (126→164종목)
Energy(21, 유가 사이클)·Materials(17, 비료/화학/구리/금/철강)는 원자재 가격 사이클의 전형적 업종인데 cyclical_type 섹션 자체가 없어 growth/value/unclassified 자동분류로만 흘러가고 있었음. "엣지가 없어도 상관없다, 표본이 커야 신뢰도가 강해진다"는 방침에 따라 신호 설계 없이 베이스라인만 우선 확보. Utilities는 규제 요금 기반 방어주 성격이 구조적으로 달라 계속 제외.

**참고 — 코드 제약:** `classify_stocks.py`의 `load_cyclical()`은 종목당 cyclical_type을 1개만 저장(마지막 등장이 우선). MLM/VMC/CRH는 개념적으로 construction과 materials 둘 다 해당하지만 construction에만 등재(먼저 만들어진 카테고리 유지, 중복 등재 시 소리 없이 덮어써짐 — 실제로 이 버그를 만들 뻔했다가 발견 후 수정).

### 결과 — 여러 업종의 성격이 근본적으로 바뀜
- **auto**: 완성차 4종목(GM/F/TSLA/APTV)뿐이던 베이스는 전 구간 뚜렷한 마이너스(−7.4%~−7.8%)였으나, 부품 리테일·중고차 추가 후 거의 중립(+1.0%~−1.9%)으로 전환 — 더 이상 일괄 매수 회피 업종이 아님. P/E 고평가 매도 신호도 완전히 반전(9m −4.2%p → +8.7%p, ORLY/AZO 같은 꾸준한 컴파운더가 "고평가" 구간에서도 계속 상승).
- **aerospace_defense**: AXON 편입 후 P/E 고평가 신호가 반전(9m −0.6%p → +2.2%p) — AXON 비중 영향으로 신호 폐기.
- **retail**: 베이스가 전 구간 플러스로 전환(12m −1.3%→+1.4%), ★★ 신호는 절대값이 낮아졌지만(+25.4%→+13.8% 등) 표본이 3배 가까이 커져 신뢰도는 오히려 상승.
- **semiconductor**: 대형 로직·아날로그주 편입으로 베이스가 크게 상승(+2.4%→+5.3%), 매도 신호가 "미정의"에서 "유의미한 언더퍼폼"으로 격상(P/FCF 고평가 9m −3.1%p).
- **energy·materials(신규)**: 둘 다 보유 기간이 길수록 SPY 대비 열위가 커지는 구조적 부진(24m 기준 각각 −15.5%, −9.8%) — 이 기간 메가캡 기술주 주도 장세에서 원자재 사이클 업종이 소외된 결과로 추정.

### 남은 이슈
- auto의 매수 신호는 아직 미정의 — 베이스가 중립권으로 바뀐 만큼 추후 신호 설계 여지 있음.
- energy·materials는 베이스라인만 확보한 상태 — 밸류에이션 기반 매수/매도 신호는 아직 설계하지 않음.
- 포트폴리오 회전 시뮬은 여전히 재실행 안 됨(위 항목과 동일).

---

## auto/energy/materials 신호 설계 (2026-07-02)

바로 위 "남은 이슈"의 auto 매수, energy/materials 매수·매도 신호를 채택한 원칙과 동일하게 후보 팩터를 여러 개 테스트(3중 저평가 조합, op 1y/2y 역성장, CAPEX 방향, rev 가속 등)해서 베이스 대비 갭이 크고 표본이 충분한 것만 채택. 동적 시뮬(포트폴리오 회전)은 내일로 미룸.

### 채택
- **auto 매수 — CAPEX 1y삭감** (n=140, freq32%): 12m/18m/24m 갭 +6.4%p/+9.9%p/+11.3%p, 표본이 커서 신뢰도 높음. energy와 동일 로직(설비투자 축소 = 사이클 저점 통과).
- **energy 매수 — CAPEX 1y삭감** (n=388, freq35%): 절대 수익은 낮지만(+1~2%) 베이스가 워낙 깊은 마이너스라 갭이 12m→24m로 갈수록 +7.0%p→+17.3%p로 확대. 표본이 매우 커서(전체의 1/3) 신뢰도 높음.
- **materials 매도 — rev↓+PE고평가** (n=111, freq12%): 9m 갭 −2.4%p로 약하지만 표본이 크고 방향 일관.

### 미채택 (테스트했으나 기각)
- **energy 매도**: P/E·P/S·P/OP·P/FCF 고평가 전부 테스트했으나 매도 신호로 성립 안 함 — 오히려 P/E 고평가군이 9m +3.7%p 아웃퍼폼. 밸류에이션이 비싸 보이는 구간이 실제로는 유가 상승 사이클 초입인 경우가 많은 것으로 추정. 이 팩터 세트로는 energy 매도 타이밍을 못 잡음.
- **materials 매수**: 3중 저평가 조합이 오히려 베이스보다 나쁨(갭 −10%p 이상) — "싸다"가 가치함정에 가까움. CAPEX 삭감(auto·energy에서 통한 로직)도 효과 없음(갭 거의 0).
- **auto/energy의 3중 저평가+CAPEX삭감 조합**: 극단적으로 좋은 수치가 나왔으나(예: auto n=6에 12m+160%) 표본이 3~20으로 너무 작아 노이즈로 판단, 채택하지 않음.

### 코드 반영
`signal_cyclical()`에 `auto`/`energy` → CAPEX 1y삭감 분기 추가, `sell_cyclical()`에 `materials` → rev↓+PE고평가 분기 추가. 둘 다 라이브 종목 배지에도 즉시 반영됨.

---

## Growth/Value 동적 포트폴리오 시뮬 재실행 (2026-07-03)

`scripts/simulate_growth_portfolio.py`가 구 유니버스(생존편향 있는 329종목, 32Q 비-PIT, ★★/★/○ 다단계 신호)로 1회 실행된 채 방치돼 있던 것을 재작성.

### 발견한 버그: static 분류 CSV만 쓰면 PIT 이벤트가 누락됨
`growth_stocks.csv`는 **현재 시점 기준** growth로 분류된 종목의 전체 히스토리만 담고 있음 — 지금은 growth가 아니지만 과거 특정 분기엔 `growth_pit16=True`였던 종목(MU/AMD/INTC/PFE/LVS 등 48종목, 총 1,189개 이벤트)이 통째로 빠짐. `growth_stocks.csv ∪ value_stocks.csv ∪ cyclical_stocks.csv ∪ unclassified_stocks.csv` 합집합으로 종목별 전체 팩터 히스토리를 복원한 뒤 `pit_buckets16` 테이블로 필터링하는 방식으로 수정.

### 변경 사항
- 이벤트 소스: `growth_stocks.csv` 단독 → 4개 분류 CSV 합집합 + `pit_buckets16` 필터
- 신호: ★★/★/○ 다단계 → build_dashboard.py의 최종 단일조건(▲매수/▼매도, growth·value 공용 로직) 그대로 이식
- growth 전용 스크립트 → growth/value 둘 다 실행하는 범용 스크립트로 확장(`run_simulation(bucket)`)

### 결과 (10슬롯, 12m 최소/18m 최대 보유, 무신호+12개월↑ 중 최고령 교체)
| 버킷 | 기간 | 포트폴리오 CAGR | SPY CAGR | 초과 | 총수익률 |
|---|---|---|---|---|---|
| growth | 12.5년(2013-12~2026-07) | +26.69% | +14.05% | +12.63%p | +1843.2% (vs SPY +420.3%) |
| value | 12.5년(2013-12~2026-07) | +25.53% | +14.05% | +11.48%p | +1632.1% (vs SPY +420.3%) |

구버전(구 유니버스, 32Q 비-PIT, growth만) 결과는 +22.83% CAGR/16.2년이었음 — 기간이 짧아졌지만(PIT 시작점이 2013Q4로 밀림) 연환산 수익률은 오히려 더 높게 나옴. Growth·Value 둘 다 여전히 SPY 대비 확실한 초과수익.

### 남은 주의사항
이 결과에도 [[Cyclical 유니버스 생존편향]] 섹션에서 발견한 것과 동일한 **유니버스 자체의 생존편향**(오늘 기준 대형주 리스트를 과거에 역산 적용, 인수합병·상장폐지 종목 누락)이 그대로 반영돼 있음 — growth/value도 예외 아님. 절대 수익률은 부풀려져 있을 가능성을 염두에 두고 해석할 것.

---

## 대시보드 실적 업데이트/잠정 배지 (2026-08-04)

자매 저장소 `kr-stock-portfolio`가 DART 잠정실적 공시를 감지해 "잠정" 배지를 표시하는 걸 보고, 미국 주식에도 실적 갱신을 인지할 수 있게 해달라는 요청으로 시작. 미국엔 한국식 "잠정실적 공시" 제도가 없어 대응되는 두 SEC 이벤트로 나눠 구현.

### 배지 2종
| 배지 | 조건 | 의미 |
|---|---|---|
| 🟡 잠정: MM-DD | 최근 8-K(Item 2.02) 제출일 > 최근 10-Q/10-K 제출일 | 실적발표 프레스릴리즈는 나왔지만 정식 재무제표(10-Q/10-K)는 아직 |
| 🟢 실적: MM-DD | 최근 10-Q/10-K 제출일이 오늘 기준 7일 이내 | 정식 재무제표 반영 완료, 최근 갱신됨 |

두 조건은 정의상 상호배타적(8-K가 최신 확정 제출보다 최신이면 잠정, 아니면 잠정 아님) — 실제 501종목 검증 결과 겹치는 종목 0개.

### 구현
- `scripts/collect_financials.py`: `latest_filing()`이 이미 fetch하던 `companyfacts` JSON에서 최근 10-Q/10-K 제출일을 추가 API 호출 없이 스캔. `latest_8k_202()`는 `submissions` API를 신규 호출해 8-K 중 `items`에 "2.02" 포함된 것의 최근 제출일 추출 — 이건 티커당 API 호출을 2배로 늘림(전체 501종목 재수집 시간 증가, 주간 수집이라 부담 적음). 결과는 `stocks.db`의 새 테이블 `filing_meta`에 저장(스키마: [data_collection.md](docs/data_collection.md) 참조).
- `scripts/build_dashboard.py`: `filing_meta`를 로드해 `_is_provisional()`/`_filed_recent()`로 두 배지 상태 계산, 테이블 행(회사명 옆)과 상세 패널에 표시. 컨트롤바 검색창 옆에 배지 색상 범례 추가.

### 검증 (2026-08-04, 501종목 전체 재수집)
- 잠정(8-K만) 89종목 — 예: META(8-K 7/29, 10-Q는 아직 4/30), CVX, UNH, PG 등 어닝시즌 발표 후 10-Q 제출 전 정상 지연 구간.
- 실적 업데이트(확정 최근) 80종목 — 예: AAPL(10-Q 7/31), MSFT(10-K 7/29).
- 겹침 0종목.

### UI 반복 조정 (사용자 피드백)
회사명 컬럼에 배지를 그냥 이어붙이면 `overflow:hidden`+ellipsis에 배지까지 같이 잘리는 문제 발견 → 여러 번 반복(flex 분리+max-width 시도 → 짧은 이름 행에 빈 공백 생기는 부작용 발견 → 결국 max-width 자체를 없애고 auto width로 회귀). **결론: 회사명 컬럼은 truncation 없이 auto width로 둔다** — 드물게(전체의 2%가량) 아주 긴 이름(예: "Westinghouse Air Brake Technologies Corporation")이 그 행에서 컬럼을 넓힐 수 있지만, 고정폭+ellipsis 조합이 만드는 짧은 이름 행의 빈 공백보다 이게 낫다는 게 최종 판단. 버킷·매수/매도신호 컬럼은 폭을 줄이고 우측 정렬해 여유 공간 확보(전체 요약만, 상세는 행 클릭 시 패널에서 확인).

---

## 스크립트 실행 순서 (처음부터 재실행 시)

```bash
python scripts/collect_prices.py          # 주가 수집 (SPY 포함)
python scripts/compute_ttm.py             # TTM 재무
python scripts/compute_growth.py          # 성장률
python scripts/compute_valuation.py       # 밸류에이션 배수
python scripts/compute_returns.py         # 선행수익률 + SPY alpha
python scripts/classify_stocks.py         # 종목 분류 → analytics/*.csv
```

---

## 재무 수집 YTD 선택 버그 수정 + SEC companyfacts 지연 보충 (2026-10-06)

### 발견 경위
주간 신호 리포트 검증 중 INCY 2024Q2·Q3 순이익이 DB에 0.0으로 들어 있는 걸 발견. SEC 원본은 Q2 −444.6, Q3 +106.5(단위: 백만 달러).

### 버그: 손실 구간에서 YTD 누적값 대신 3개월 값이 선택됨
`collect_financials.py`의 `_best_record_per_period`가 같은 (연도, 분기)의 레코드 중 **값이 가장 큰 것**을 YTD로 골랐다. 누적이 음수이거나 부호가 섞이면 3개월 값이 뽑혀 이후 분기 차감(Q3 = 9개월 − 6개월 등)이 틀어진다.
- 수정: **기간(duration)이 가장 긴 레코드**를 선택, 같으면 최근 제출분 우선.
- 영향: 영업이익 4,255개 분기 값이 바뀜(부호가 바뀐 분기 583개). 441개 종목, 값이 바뀐 행 6,977행.
- 독립 검증(SEC frames API, 12월 결산 종목, 2019Q1~2026Q2): 영업이익 일치율 90.8% → 98.1%, 순이익 90.4% → 98.6%. 남은 불일치는 대부분 2019년 합병·사업재편 소급 재작성 건.

### 백테스트 영향 (같은 스크립트·같은 기간 2013-12 ~ 2026-10)
| 버킷 | 원래 데이터 | YTD 선택 수정 후 | **최종(직접 3개월 값 우선 등)** |
|---|---|---|---|
| growth CAGR / 초과(SPY 대비) | +21.04% / +7.29%p | +19.04% / +5.29%p | **+17.84% / +4.09%p** |
| value CAGR / 초과(SPY 대비) | +31.61% / +17.86%p | +22.74% / +8.99%p | **+22.82% / +9.07%p** |

- 핵심 신호(`rev_2y_acc + pop_low + capex_1y↓`)는 최종에도 상위권(성장 3팩터 12m +13.3%, n=307 / 가치 12m +18.3%, n=248; 원래는 +16.3% / +21.2%). 신호 정의는 유효하나 수익 크기는 이전보다 작음.
- 이 문서와 메모리의 이전 백테스트 수치(7/3 섹션 +26.69%/+25.53% 등)는 버그 있는 데이터 기준이므로 위 최종 값을 쓸 것.
- **이 문서의 위쪽 백테스트 결과(2026-07-03 섹션 등)는 버그 있는 데이터 기준이라 수치가 부풀려져 있다.** 이 섹션의 값을 기준으로 볼 것.
- 버킷 판정도 일부 바뀜(16종목). 대시보드 신호: 매수 11 → 9종목(CTSH·IQV 소멸, INCY는 ▲ 가치만 남음), 매도 6종목 유지(DD 소멸, CARR 신규).

### 2차 수정: 직접 보고된 3개월 값 우선 + 방어 로직 (2026-10-06)
전수 감사(`scripts/audit_financials.py`, SEC frames 대조)에서 분기값 불일치의 약 절반(358건)이 어떤 공시에도 없는 '파생 오류'로 확인됨 — YTD 차감(Q3 = 9개월 − 6개월) 시 두 값의 보고 시점이 달라(소급 재작성) 생김.
- 매출·영업이익·순이익은 Q1~Q3를 10-Q에 직접 보고된 3개월 값(80~100일)으로 사용, 4분기 = 연간 − (Q1+Q2+Q3). 분기는 `fp`가 아니라 기간 종료일로 판정(3분기 10-Q에 2분기 값이 fp=Q3으로 실려 있음). 현금흐름(cfo·capex)은 3개월 값이 없어 기존 차감 방식 유지.
- 같은 태그에서 직전 분기와 값이 정확히 같으면 SEC 원본 오류로 보고 다음 태그 사용(AEP 2022Q3 NetIncomeLoss).
- 값이 정확히 0이고 뒤 순위 태그에 0이 아닌 값이 있으면 후자 사용(BKR NetIncomeLoss=0 vs ProfitLoss).
- 효과(분석 대상 섹터 분기 불일치): 748건 → 400건. 이 중 파생 오류 358건 → 1건, 나머지는 보고 시점 차이(DB는 원래 보고값, SEC frames는 8-K 등 재작성값)로 오류가 아님. 분기 일치율 매출 97.3→98.6%, 영업이익 97.3→98.4%, 순이익 98.4→99.2%. 연간 합계 일치율은 변화 없음(매출 99.3, 영업이익 98.8, 순이익 97.6, CFO 99.3, CAPEX 99.5%).
- 남은 문제: ① 매출 하위 항목 태그 의심 38종목 약 320분기(URI·BG·ADM·CHRW·LH는 총매출의 20~30%만 잡힘 — 진짜 오류 가능성 높음, RSG·COP·CEG 등 0.8 안팎은 정의 차이 가능), ② 분사·사업매각 종목(DD·CARR 등)은 분기마다 재작성 시점이 달라 구간이 섞임, ③ 분기 공백 78종목 261분기, ④ 순이익 정확히 0 분기 8건·매출 0 분기 12건(VRT는 SPAC 시절이라 정상).
- 점검 도구: `scripts/audit_financials.py`(읽기 전용, 약 6분)

### 3차 수정: 종목별·시대별 매출 태그 매핑 (2026-10-06)
매출 태그 후보가 여러 개(RevenueFromContract…, Revenues, SalesRevenueNet …)라 "먼저 값이 있는 태그"를 쓰면 URI(총매출의 22%)·BG·ADM·TRGP·GM·VST·NRG 등에서 하위 항목이 총매출로 잡혔다. 반대로 "큰 값 우선"은 RSG(내부거래 제거 전 총액)·PM(소비세 포함)·HAS에서 틀린다. → **기업이 자기 10-Q 손익계산서 맨 윗줄에 실제로 쓴 XBRL 태그**를 정답으로 삼는다.
- `scripts/build_revenue_tag_map.py`: 종목당 2014·2017·2020·2023년과 최신 10-Q 손익계산서(R 페이지)에서 최상단 매출 행의 태그를 읽어 `{제출연도: 태그}`로 `data/revenue_tag_map.json` 저장(474종목, 금융주 등 29종목은 못 찾아 기존 우선순위 유지). 행 선택 규칙: 한 줄이면 그 줄, 여럿이면 라벨이 total/net revenues/net sales인 마지막 줄, 없으면 값이 가장 큰 줄.
- `collect_financials.py`: 각 분기는 "그 연도 이후 첫 샘플"의 태그를 1순위로 쓰고, 값이 없으면 기본 우선순위. **표준 총매출 태그 화이트리스트**(Revenues, RevenueFromContract…Excluding/IncludingAssessedTax, SalesRevenueNet, RegulatedAndUnregulatedOperatingRevenue)만 사용 — `SalesRevenueGoodsNet`·`SalesRevenueServicesNet`·`PassengerRevenue` 같은 하위 항목 태그는 UNH·INCY·BIIB·REGN에서 하위 줄이 잡혀 오히려 틀려서 제외.
- 만드는 중 잡은 버그: ① `CostOfRevenue`가 "Revenue" 포함이라 매출 행으로 오인 ② `…AvailableForSaleSecurities…`가 "Sales" 부분 일치로 오인 → 매출 태그 판정을 이름 시작/끝 기준으로 엄격화.
- 효과: 매출 하위 태그 의심 320 → 197건. URI 17→0, BG 11→0, ADM 9→0, CEG·GM·NRG·CNP·HLT·PODD·PM·ADP → 0. 임의 표본 103건을 손익계산서 최상단 값과 대조해 101건 일치(98.1%); 불일치 2건(TEL 2014Q2·KMB 2014Q1)은 소급 재작성 차이.
- 남은 의심: HUM 27·WMB 13·HAS 14·EQT 7·VST 7·PEG 5·COP 4 등(RSG 41건은 DB가 맞는 정의 차이). 상세와 다음 작업은 `TODO.md` "2026-10-07 재개" 블록.
- 백테스트 수치는 run4 시점 값(growth +17.84%, value +22.82%). 3차 수정 반영 후 재측정 필요.

### 벤치마크 SPY 가격 정지 발견·수정 (2026-10-07)
`collect_prices.py`는 `stock_universe.csv`의 종목만 수집하는데 SPY는 유니버스에 없어서, **일일 수집이 SPY를 한 번도 갱신하지 않았다.** SPY는 예전에 수동으로 받은 2026-06-18(746.74)에서 멈춰 있었고, 이후 3.5개월 동안 백테스트(`price_on_or_before`가 마지막 가격을 이어 씀)와 `compute_returns` 알파가 SPY를 보합으로 계산했다(실제 10/6 779.09, +4.3%).
- 수정: `collect_prices.py`가 SPY를 항상 수집 대상에 포함. SPY가 다른 종목보다 3일 넘게 뒤처지면 재시도하고, 그래도 안 되면 `⚠⚠` 경고를 로그에 남김(`check_benchmark_lag`). 첫 보충은 6/19~10/6 75행.
- 영향(같은 데이터, SPY만 보정): SPY CAGR +13.75% → +14.12%, growth 초과 +3.09%p → +2.70%p, value 초과 +12.55%p → +12.11%p. 팩터 수준 결과(핵심 신호 12m)는 그대로. 최종 수치: growth +16.82%, value +26.23%.
- 같이 정리: 가격이 30일 넘게 갱신되지 않은 종목(EA 8/10, SATS 7/17 — 상장폐지·비공개 전환 의심)은 대시보드에서 제외(`build_dashboard.load_stale_tickers`). 주간 수집에서 스킵되는 3종목은 EA·AVB·EQR(SEC 목록에 CIK 없음; AVB·EQR은 부동산이라 분석 제외).
- 주간 수집에 `check_stale_quarters.py` 연결(기준 분기는 제출 기한 분기말+50일로 자동 계산). 현재 SEC 지연·수집 누락·미제출 모두 0종목.

### 52/53주 회계연도 라벨 오류·분기 공백 수정 (2026-10-07)
분기 공백(최근 5년 안에 중간 분기가 빠진 종목)이 신호 누락의 원인일 수 있어 조사했다. 18종목 중 대부분이 **4분기 하나**가 빠진 52/53주 종목(연말이 12/28~1/3: SNA·JNJ·TXT·SWK·LHX·LDOS·TRMB·TDY·DPZ·KVUE)이었다.
- 원인: 회계연도 라벨 규칙이 FY와 분기에서 달랐다. 분기는 "종료일에서 10일을 뺀 달이 `fy_end_month`보다 크면 +1년", FY는 `end_year`를 그대로 사용 → 연말이 12/28인 종목(universe `fiscal_year_end_month=1`)의 4분기가 한 해 일찍 붙고 그 해 4분기가 통째로 빔. 더 나쁘게도 **4분기 값 자체가 틀렸다**(연간과 분기를 서로 다른 라벨로 차감: JNJ 2024Q4 250.6억 달러 저장, 실제 약 214억 달러). `compute_ttm`·`compute_valuation`이 분기 이름과 `fiscal_year_end_month`로 분기 말일을 계산하므로 기존 라벨 규칙("회계연도 Y는 달력상 Y년 fy_end월에 끝남")에 FY도 맞췄다. Dec 결산 종목은 영향 없음.
- 수정: `extract_periods`가 FY·분기 모두 `adj = 종료일 − 10일; year = adj.year + (adj.month > fy_end_month)` 사용. 효과: 값이 바뀐 행 171, 19종목. 분기 공백 18 → 7종목, 연간 합계 불일치 174 → 132건(매출 99.4%, 영업이익 99.1%, 순이익 97.9%, CFO 99.5%, CAPEX 99.7%).
- **사고와 교훈 — XOM 이력 삭제**: 라벨 변경 때문에 옛 라벨 행이 새 행과 겹쳐 남는 걸 막으려고 `prune_stale_terms`(수집된 분기에 없는 기존 행 삭제)를 넣었는데, XOM이 2026년 지주회사로 재편돼 SEC 종목 목록의 CIK가 새 법인(ExxonMobil Holdings Corp, 레코드 227건)으로 바뀌어 **2개 분기만 수집되면서 기존 64행이 삭제**됐다(이력은 옛 CIK 0000034088에 있음). 수정: ① 정리 안전장치 — 수집된 분기가 기존의 70% 미만이면 정리하지 않고 경고 ② `CIK_PREDECESSORS`(XOM)로 옛 CIK의 companyfacts를 합쳐 수집 → 66개 분기 복구. 전체를 백업과 대조해 다른 종목에는 같은 손상이 없음을 확인(행 수가 줄어든 종목 0). **지주회사 재편·CIK 변경 종목이 생기면 `CIK_PREDECESSORS`에 추가할 것.**
- 보충 범위 확대: `edgar_xbrl_fallback.patch_missing_filings`가 "가장 최근 제출일 이후"만 보던 것을 "이미 반영된 접수번호가 아니면 모두"(최근 8건, 3.3년 이내)로 넓혀 중간 공시 구멍(TAP 2026Q1, CAH 2026Q3: 뒤쪽 공시는 있는데 4/30 10-Q만 companyfacts에 없음)을 메움.
- 남은 공백 5종목은 합병·분사로 새로 생긴 법인이라 이력이 없는 정상 공백(PSKY·Q·SNDK·FDXF)과 분석 제외 섹터(BLK). 데이터 점검 플래그 51 → 38종목.
- 최종 백테스트(2013-12~2026-10, SPY 보정 후): growth CAGR +17.95%(초과 +3.83%p), value +27.87%(초과 +13.75%p). 핵심 신호 12m: growth +13.9%(n=287), value +18.7%(n=237). 포트폴리오 CAGR은 ±2~3%p 노이즈가 있어 범위(growth +17~19%, value +23~28%)로 볼 것.

### CAPEX 결측 조사에서 나온 두 가지: 설비투자 태그 확대, 대시보드 `groupby().last()` 버그 (2026-10-08)
CAPEX 분기값 검증을 하려다 값 정확도보다 **결측**이 더 큰 문제임을 발견했다. `capex` 결측이 전체 행의 12.8%였고, 분석 대상 중 최근 8분기 capex가 전부 비어 있는 종목이 21개였다. CAPEX 1년 감소는 매수·매도 신호의 필수 조건이라 이 종목들은 신호가 날 수 없는 사각지대였다.
- **표준 태그 확대**(`collect_financials.TARGETS` capex 목록 끝에 추가 — 기존 선택은 바뀌지 않고 빈 곳만 채움): `PaymentsForCapitalImprovements`(GLW·IT·SNA), `PaymentsToAcquireOtherProductiveAssets`(VZ·ROP·BAX), `PaymentsToExploreAndDevelopOilAndGasProperties`(APA·FANG), `PaymentsForConstructionInProcess`(ED), `PaymentsForProceedsFromProductiveAssets`(설비투자에서 매각 수입을 뺀 순액 — WAT 2025Q3 10-Q, VEEV). 효과: capex 1,225행(46종목) 채움, 사각지대 21 → 11종목, 대시보드 capex_1y 빈 종목 10 → 5(DTE·FDXF·NEE·PSX·TKO). 매출·영업이익·순이익·CFO 변화 0, 백테스트 변화 미미(growth +18.15%, value +27.92%). AEP·ETR의 capex 0.0 구멍 18행도 실제 값으로 채워짐.
- **남은 사각지대 = 회사 고유(extension) 태그**: PSX(`psx:CapitalExpendituresAndInvestments`), DTE(`dte:PlantAndEquipmentExpendituresUtility`), TKO, COP(`cop:PaymentToAcquireProductiveAssetsAndInvestments`), D, NEE 등. companyfacts에는 extension이 없어 10-Q 인스턴스를 직접 파싱해야 한다(APA 매출 NULL과 같은 구조).
- **대시보드 버그(중대)**: `build_dashboard.load_snapshots`가 `groupby('ticker').last()`로 종목별 스냅샷을 만들었다. pandas의 `GroupBy.last()`는 마지막 **행**이 아니라 **열마다 마지막 non-null 값**을 가져와, 최신 앵커에서 비어 있는 지표를 몇 년 전 앵커의 값으로 조용히 채웠다. 402종목 중 33종목이 핵심 열(pop_20d 21종목, op_1y·ni_1y 13종목, capex_1y 9종목, rev 1종목) 중 하나 이상이 과거 값이었다. 수정: `drop_duplicates('ticker', keep='last')`(마지막 행 그대로).
  - **VEEV의 매수 신호(최종 후보, 7/15~10/6 12주 연속)가 이 버그 때문이었다.** VEEV는 현금흐름표에 설비투자 줄이 아예 없어(투자활동에 단기투자 매입·만기뿐, 3개 공시 확인) `capex_1y`를 계산할 수 없는데, 대시보드는 2020년경의 capex_1y −35.2를 끌어와 "capex↓" 조건을 켰다. 수정 후 VEEV 신호는 사라진다(매수 7 → 6, 매도 7 변화 없음).
  - 다른 신호 종목(ISRG·FICO·GDDY·MKC·UHS·ACN)은 수정 후에도 신호가 유지된다. 과거 리포트 28종목 중 capex 전부 NULL이었던 종목은 COP(7/28·8/4 "신중" 그룹, 최종 판정에는 안 쓰임)뿐, 일부 분기만 NULL: INTU·DD.
  - **백테스트는 영향 없음**: 백테스트는 종목별 앵커별 행을 그대로 쓰고 NaN이면 이벤트를 만들지 않아 이 결함이 없다. 라이브 대시보드와 주간 리포트에만 있었다.
  - 교훈: pandas `groupby().last()`/`first()`는 NaN을 건너뛴다. "최신 행"이 필요할 땐 `drop_duplicates(keep='last')`나 `tail(1)`. (`load_shares`의 `.last()`는 주식 수의 마지막 유효값이 의도라 그대로.)

### 옛 CIK 이력 연결(CIK_PREDECESSORS)과 매출 태그 매년 샘플링 실험 (2026-10-07)
**CIK 변경 종목 점검**: 가격 이력은 2006년부터인데 재무 이력이 40분기 미만인 15종목을 찾았다(XOM의 지주회사 재편과 같은 유형). 사업이 이어지는 재편 9종목의 옛 CIK를 `collect_financials.CIK_PREDECESSORS`에 등록해 이력을 합친다 — XOM(0000034088), APA(Apache 0000006769), TPL(Texas Pacific Land Trust 0000097517), BG(Bunge Ltd 0001144519), DIS(옛 Walt Disney 0001001039), CI(옛 Cigna 0000701221), LIN(Praxair 0000884905), EVRG(Westar 0000054507), STE(옛 STERIS plc 0001624899). 합치지 않은 종목: PSKY·TKO·SW(별개 사업 합병·신규 법인), CRH(IFRS 시절 이력).
- 효과: 분기 수 APA 28→66, BG 17→66, CI 37→66, DIS 35→67, EVRG 39→66, LIN 38→66, TPL 29→65, STE 36→49(XOM 66 유지). 백테스트·감사 수치는 변하지 않음(PIT 이벤트에 영향 없음).
- 합치는 규칙의 시행착오(전부 고쳐서 지금은 아래 규칙): ① 처음엔 "새 법인 데이터 시작일 이전만" → XOM(2025Q3~2026Q1)·DIS(2016~2018 분기)가 지워짐 ② "새 CIK에 같은 기간이 있으면 옛 값을 건너뜀" → CI 2017Q1~Q3가 쓸 수 없는 값(710 등)으로 남음. 새 CIK에 그 기간이 10-K 분기 표·8-K 재작성으로만 있으면 수집 로직(10-Q만 사용)이 못 써서 값이 사라지는 문제. **최종 규칙: 옛 CIK 레코드를 모두 합치고(같은 레코드만 중복 제거) 값이 다르면 가장 최근 제출을 쓴다. 옛 CIK가 재편 뒤에도 자회사로 공시하는 종목(APA·EVRG)은 `CIK_PREDECESSOR_UNTIL`로 재편 시점까지만.** CI 2017년 매출은 710/757/733/39,606 → 10,474/10,425/10,489/10,418로 정상화.
- `build_revenue_tag_map.py`는 이 9종목의 옛 CIK 공시도 샘플링한다.

**매출 태그 매년 샘플링은 채택하지 않음(실험 결과 기록)**: 샘플링을 5개 시점(2014·2017·2020·2023·최신) → 2013년부터 매년(종목당 최대 14개, 2시간 20분)으로 늘리면 VRSK처럼 연도 사이에 태그가 바뀌는 종목이 고쳐질 거라 기대했다. 실측: 매출 227행(60종목)이 바뀌었고, 15% 넘게 바뀐 61행 중 해당 10-Q 손익계산서 맨 윗줄과 대조한 36행에서 **새 값이 맞은 곳 19건, 이전 값이 맞은 곳 17건**(개선: HSIC 2018·JCI 2016·KDP 2018·HWM·IRM 2021·DD·PNR·TMUS / 퇴보: COP 2021·CHRW 2018·AMT·IRM 2019·LNT 2024·BG 2018·MA·OXY·TRGP). 같은 종목 안에서도 연도에 따라 갈렸고(IRM·TAP), 감사 일치율도 그대로였다. 원인은 손익계산서 총계 행의 태그가 연도마다 `Revenues`였다가 `RevenueFromContract…`였다가 하는 종목에서 "첫 비용 행 전까지 가장 큰 'Total' 행" 규칙이 서로 다른 행을 잡기 때문. → **5개 시점 매핑 유지, 옛 CIK 9종목만 매년 샘플링.** 참고: 값이 갈릴 때 더 큰 값이 맞은 경우가 36건 중 28건(78%)이지만 RSG(내부거래 제거 전 총액)·PM(소비세 포함)에서 틀려서 "큰 값 우선"은 쓰지 않는다.
- 표준 매출 태그가 없는 종목: APA는 2021년 이후 us-gaap 매출 태그가 없다(손익계산서가 회사 고유 extension 태그 사용, companyfacts에는 extension이 없음) → 매출 NULL 20분기. 최근 8분기에 매출 NULL인 종목은 APA·FDXF와 한 분기씩인 WDC·DLTR·DD뿐.

### 데이터 점검 플래그 (2026-10-07)
분사·사업매각으로 연간 값은 소급 재작성됐는데 분기 값은 원래 값이 섞이면 4분기 파생값(연간 − Q1~Q3)이 비정상이 된다(CARR 2023: 연간 22,098→18,951 재작성, Q1 원래·Q3 재작성 → Q4 2,751). 이런 종목의 TTM·성장률·신호는 가짜일 수 있어, 해결 대신 **감지해서 표시·보류**하는 방식을 택했다.
- `scripts/compute_data_quality.py` → `data/analytics/data_quality.json` → 대시보드 "⚠ 데이터 점검" 배지 + 주간 리포트 판정 보류 규칙. 상세는 `TODO.md` "2026-10-07 오전 후속".
- 감지 기준(자동, 실제 사업 변동일 수도 있음): 4분기 매출이 1~3분기 평균의 0.55배 미만·1.9배 초과 / 매출 0인 분기 / 분기 공백. 현재 51종목.

### SEC companyfacts 갱신 지연 보충 (신규)
SEC companyfacts API가 종목별로 갱신을 멈춰 12월 결산 59종목이 7월 말 2분기 10-Q를 못 받음(과거 AEP 사례와 같은 유형). `scripts/edgar_xbrl_fallback.py`가 submissions에 있는데 companyfacts에 없는 10-Q/10-K를 찾아 원본 인스턴스(`*_htm.xml`)를 파싱해 같은 형식으로 병합. `collect_financials.py`가 자동 호출.
- 검증: 보충한 59종목의 매출·영업이익·순이익을 frames와 대조해 98건 일치 / 불일치 0건(frames 없는 79건은 대조 불가). 기존 분기 값 변경 0건.
- 점검 도구: `scripts/check_stale_quarters.py`(읽기 전용)로 지연 종목 확인. 12월 결산 외 131종목은 아직 점검 전.

### 같이 바뀐 것
- SEC User-Agent 연락처를 코드에서 `.env`(커밋 제외, `SEC_USER_AGENT`)로 분리 — `config.sec_headers()`.
- `scripts/edgar_lookup.py` 신규: 공시 목록·Form 4 집계·본문 검색(1차 출처 검증용).

### 남은 일
- 12월 결산 외 131종목 지연 점검, 주간 수집 스킵 3종목 확인, `total_assets` 결측(전체 행의 76%, 중간 분기 시점 데이터가 걸러지는 기존 동작) 사용처 확인.
- 매출 태그 우선순위가 분기마다 달라지는 종목(예: AEP) 점검.
- 이번 변경 사항 커밋(코드와 데이터 분리).
