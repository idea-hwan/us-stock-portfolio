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

## 스크립트 실행 순서 (처음부터 재실행 시)

```bash
python scripts/collect_prices.py          # 주가 수집 (SPY 포함)
python scripts/compute_ttm.py             # TTM 재무
python scripts/compute_growth.py          # 성장률
python scripts/compute_valuation.py       # 밸류에이션 배수
python scripts/compute_returns.py         # 선행수익률 + SPY alpha
python scripts/classify_stocks.py         # 종목 분류 → analytics/*.csv
```
