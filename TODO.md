# TODO

## 완료

- 파이프라인 전체 (TTM → 성장률 → 밸류에이션 → 수익률 → 분류)
- `scripts/build_dashboard.py` + `docs/index.html` (401종목, 정적 HTML)
  - 버킷/신호/저평가 필터, Ticker 검색, 컬럼 정렬
  - 종목 클릭 → 상세 패널 (밸류에이션·TTM 재무·성장률 CAGR·주가수익률)
- **1. 대시보드 숫자 검토** (2026-07-02, 원래 예상보다 훨씬 크게 확장됨)
  - 판단로직 패널 재구성 (버킷별 매수/매도 시뮬 통합, 베이스 우선 표시, 숫자 포맷 통일)
  - dead code(signal_value 미호출)·threshold 버그(0.75 미적용) 수정
  - 평균→중앙값 전환 (아웃라이어 왜곡 제거), 신호를 단일조건(▲/▼)으로 단순화
  - growth/value 버킷 판정의 생존편향 발견·수정 → PIT(16분기 롤링) 보정 (`pit_buckets.db`)
  - cyclical_universe.txt의 실적기반 배제(생존편향) 발견·원복 + GICS 산업매칭 감사로 98→164종목 확장
  - stock_universe.csv의 Energy/Basic Materials/Utilities 섹터 전체 누락(329→401종목) 발견·편입
  - auto/energy/materials 신호 설계(CAPEX삭감 매수, rev↓+PE고평가 매도 등, 후보 테스트 후 채택/기각)
  - 상세 기록: `STATUS.md` 하단 각 날짜별 섹션
- **Growth/Value 동적 포트폴리오 시뮬 재실행** (2026-07-03) — `scripts/simulate_growth_portfolio.py`를 4개 분류 CSV 합집합+`pit_buckets16` 필터(static 분류 기준으로 growth_stocks.csv만 쓰면 PIT 이벤트 1,189개 누락되던 버그 발견·수정) + 단일조건(▲/▼) 신호로 재작성, growth·value 둘 다 실행하는 범용 스크립트로 확장. 결과: growth CAGR +26.69%(SPY +14.05%, 초과+12.63%p), value CAGR +25.53%(초과+11.48%p), 둘 다 12.5년(2013-12~2026-07). 단, 유니버스 자체의 생존편향(아래 항목)은 이 결과에도 그대로 남아있어 절대 수익률은 과장돼 있을 수 있음. 상세: STATUS.md "Growth/Value 동적 포트폴리오 시뮬 재실행".
- **`scripts/compute_valuation_current.py`** (2026-07-07) — 최신 분기 TTM 재무 × 오늘 가격으로 P/E·P/S·P/FCF·P/OP 재계산, `valuation.db`는 건드리지 않고 `data/analytics/valuation_current.json` 별도 캐시에 저장(400/401종목 성공, STZ는 shares_diluted 전체 NULL이라 기존과 동일하게 skip). `build_dashboard.py`가 캐시를 읽어 메인 테이블에 "P/E (현재)" 컬럼 추가, 상세 패널은 "현재 / 20d / 4y 평균" 3단 비교로 확장. 기존 20d 배수는 공시 앵커일(분기말+45~60일) 기준으로 계산되어 다음 분기 공시 전까지 최대 수개월 stale할 수 있어, 매일 갱신되는 "현재" 값을 보완적으로 추가한 것 — 매수/매도 신호 로직(`val_undervalued` 등)은 그대로 20d/4y 기준 유지(백테스트 검증된 신호라 변경 안 함).
- **로컬 데이터 수집 스케줄러** (2026-07-07) — git 저장소가 아직 없어(사용자가 git에 익숙하지 않음) `git push`는 보류, 완전 로컬 자동화만 구현. launchd 대신 `caffeinate -i python3` + 상시실행 파이썬 루프 방식 채택(사용자 선호).
  - 설계: **가격은 매일, 재무 원본 수집은 매주, 계산은 가격 다음 매일.** `collect_financials.py`는 "새 공시 있는 종목만 골라 받는" 게 아니라 매번 유니버스 전체(~503종목)를 통째로 재요청해 고정비용 ~5~6분이 들어(새 실적 유무와 무관하게 항상 이만큼 걸림) 매일 돌릴 이유가 없어 주 1회로 분리. 반면 로컬 계산 체인(TTM~대시보드)은 401종목 기준 ~3분이라 매일 돌려도 부담 없고, 밸류에이션 4년 롤링 평균 등이 매일 갱신되는 가격을 반영해야 해서 가격 수집 직후 매일 실행.
  - `automation/daily_update.sh` (화~토 KST 09:00 실행): collect_prices → compute_ttm → compute_growth → compute_valuation → compute_returns → classify_stocks → compute_valuation_current → build_dashboard
  - `automation/weekly_collect_financials.sh` (일요일 1회): collect_financials 만 실행 — 결과(`stocks.db`)는 다음 날 daily_update.sh의 compute_ttm 이하 단계에서 자동 반영됨. 새 버킷 편입/제외 등 판단이 필요한 변경은 자동화 안 함, 결과 CSV는 필요할 때 사람이 검토.
  - `automation/scheduler_data_collection.py`: **화~토** 00:00 UTC(KST 09:00) → daily_update.sh, **일요일** 00:00 UTC → weekly_collect_financials.sh, **월요일** 스킵. 요일 매핑에 주의 — KST 09:00 실행 시점은 미국 동부시간 "전날 저녁" 기준이라, KST 월요일=미국 일요일 저녁(휴장, 새 종가 없음)/KST 토요일=미국 금요일 저녁(개장, 금요일 종가 반영)이 되어 월~금이 아니라 화~토가 맞음(2026-07-07 최초엔 월~금으로 잘못 설정했다가 사용자가 요일 매핑 오류 지적, 수정함). 실행: `caffeinate -i python3 automation/scheduler_data_collection.py` (터미널을 켜둔 채 유지). 로그: `automation/logs/{YYYYMMDD_daily,YYYYMMDD_weekly,scheduler}.log`
  - 실제 실행 테스트 완료 — daily_update.sh(재무 포함 버전)로 전체 파이프라인 9분 52초에 정상 완료 확인(400/401종목), 이후 재무 수집을 분리해 최종 형태로 정리.
- **대시보드 컬럼 개편 + Cyclical 신호 임시 비활성화 + GitHub Pages 배포** (2026-07-08)
  - `build_dashboard.py` 메인 테이블: `P/E(현재)` → `P/E(20d)`+`P/E(4y)` 2열로 교체(저평가 판단에 실제로 쓰이는 두 값을 바로 비교), 주가수익률에 `1w(%)` 컬럼 추가(1m/3m/1y 옆). 상세 패널에도 동일 반영.
  - `get_signals()`/`get_sell_signals()`에서 cyclical 분기 제거 — 매수/매도 신호에 '사이클' 더 이상 안 뜸(`signal_cyclical`/`sell_cyclical` 함수는 남겨둠, 아래 Cyclical 재작업 끝나면 복원). growth/value 신호는 그대로.
  - **git 저장소 최초 설정**: `git init` → `.gitignore`(.venv/__pycache__/reference/data 원본DB·analytics/logs 제외) → GitHub repo `idea-hwan/us-stock-portfolio`(Public) 생성 → `gh` CLI 설치+브라우저 로그인(`gh auth login --web`) → push → **GitHub Pages 활성화(`/docs`) 완료: https://idea-hwan.github.io/us-stock-portfolio/**
  - `automation/daily_update.sh` 마지막에 git add/commit/push 자동 추가(변경 없으면 스킵) — 매일 새벽 자동 실행으로 Pages도 같이 갱신됨. 스케줄러 재시작 불필요(스크립트는 실행 시점에 디스크에서 새로 읽음).
  - **커밋 원칙 합의**: 코드/스크립트 수정은 세션 마무리 시점마다 커밋(전체 작업 끝날 때까지 몰아두지 않기) — 이유는 자동 push가 `git add -A`라 미완성 상태를 애매한 메시지로 같이 쓸어갈 수 있어서. 상세: 메모리 `feedback_automation_preference`.
- **스크립트/문서 정리 — 불필요·중복 파일 감사 및 정리** (2026-07-08)
  - 조사 에이전트로 `scripts/`·`docs/`·`analysis/` 전체를 automation 참조여부·STATUS.md 언급·기능중복 기준으로 분류(KEEP/ARCHIVE/DELETE-CANDIDATE), 결과 확인 후 정리.
  - **삭제**(완전히 대체돼 정보손실 없음): `scripts/top100_dashboard.py`·`build_summary_table.py`·`simulate_growth.py`(구 ★★/★/○ 신호체계), `docs/top100_dashboard.md`+`.html`(GitHub Pages로 index.html과 혼동될 위험 있던 stale 페이지), `analysis/build_html_table.py`+`stock_universe.html`(초기 프로토타입), `analysis/momentum/`(Ondo 토크나이즈 주식 분석 — 이 프로젝트와 무관한 별개 주제 전체 삭제, `analysis/` 폴더 자체도 비어서 삭제됨).
  - **`scripts/archive/`로 이동**(신호 도출 방법론 기록, 지금은 안 돌리지만 재현·참고용 — 특히 cyclical 재작업 때 참조): `simulate_growth_factors/sell.py`, `simulate_value_factors/sell.py`, `simulate_cyclical.py`+`_sell.py`, `screen_candidates.py`, `patch_shares_yfinance.py`.
  - **`docs/archive/`로 이동**(현재 코드와 어긋난 stale 수치 있어 "지금 코드"로 오인 방지): `dashboard_plan.md`, `bucket_factor_analysis.md`, `cyclical_classification.md`.
  - **`scripts/config.py` 수정**: `EXCLUDED_SECTORS`가 Energy/Basic Materials/Utilities를 아직 포함해 `stock_universe.csv`(2026-07-02 이후 이 3섹터 편입) 실제 상태와 불일치하던 것 발견·수정 → Financial Services/Real Estate 2개만 남김. `check_quality.py`가 이 값을 그대로 씀.
  - `docs/db_overview.md`·`docs/data_collection.md`의 stale 종목수(329/330→401개, 제외섹터 5개→2개) 수정.

- **Cyclical 버킷 재작업 완료 — 가격→팩터 역방향 방법론** (2026-07-13)
  - **배경**: semiconductor 베이스 12m 알파가 +5~7%로 비정상적으로 높은 이유 추적 → `stock_universe.csv`가 오늘 기준 시총 상위 종목만 담고 있어, 과거엔 컸지만 지금은 인수합병·상장폐지로 사라진 종목이 전체 백테스트 기간에서 통째로 빠져있는 **유니버스 자체의 생존편향** 발견(무료 소스로는 해결 불가, 포기). 대안으로 "팩터→결과"가 아니라 **"가격 turning point(zigzag 30% 되돌림) 먼저 찾고 → 그 앞뒤로 재무 팩터가 어떻게 끼었는지" 역방향 접근**으로 전환.
  - **cyclical_universe.txt 전체 카테고리를 대표주 기준으로 완료**: 반도체(MU/AMAT/NVDA) → 자동차(F/GM, 방법론 부적합으로 종료) → 에너지(XOM/SLB/EOG)·소재(FCX/CF/NUE) → 건설(MLM/URI/PWR) → 레저(LVS/CCL)·리테일(BBY/AMZN)·자본재(CAT/VRT)·항공방산(BA/RTX)·운송(DAL/UNP). 상세: `docs/cyclical/cyclical_semiconductor_analysis.md`, `docs/cyclical/cyclical_energy_materials_analysis.md`, `docs/cyclical/cyclical_construction_analysis.md`, `docs/cyclical/cyclical_leisure_retail_capital_transport_analysis.md`. **종합 분류: `docs/cyclical/cyclical_classification_summary.md`** — 사이클있음/없음(유념대상)/판단보류 3그룹.
  - **실전 결론**: 매수/매도 타이밍 신호로 실제 쓸 수 있는 건 여전히 반도체(MU/AMAT)뿐. "사이클 없음"(NVDA/PWR/VRT, 경계사례 AMZN)은 전부 AI 데이터센터 인프라 수혜주로 몰려있고 진짜 무사이클인지 아직 다운턴을 안 겪어서인지 구분 불가(n=0 사이클). "판단보류"(F/GM/BA/RTX/URI/BBY/MLM/UNP)는 대표성·데이터품질 문제로 이 방법론 자체가 안 맞음.
  - **대시보드 정리**: `signal_cyclical`/`sell_cyclical` 죽은 코드 삭제, "Cyclical 버킷 — 업종별 매수 시뮬/매도 시뮬" 판단로직 패널(유니버스 생존편향 있던 옛 숫자) 통째로 제거. cyclical 분류 태그/필터는 성과주장이 없는 단순 라벨이라 유지 + "판단 로직" 패널의 "버킷 분류 기준" 표 아래에 위 문서 5개로 가는 참고 링크만 추가(신호·수치 없이 포인터만).
  - **재사용 가능한 도구**: `scripts/archive/cyclical_price_factor/`에 zigzag 탐지(`zigzag.py`)·재무 팩터 조회(`factors.py`) 스크립트 저장.
  - git 커밋·push 완료(`e48e987`→`4735986`).
  - 남은 여지(보류): auto의 부품리테일/중고차(ORLY/AZO/CVNA) 미확인, energy/materials/leisure 등 카테고리 내 나머지 종목으로 표본 확장(대표주 1~3개만 봄, 전체 검증은 아님).
  - 상세 배경: 메모리 `feedback_backtest_methodology`(원칙 7~9), `project_next_steps`.
- **문서 재점검 + 대시보드 화면 구성 재검토 완료** (2026-07-15) — 판단로직 패널을 4단계 흐름 요약·용어설명·배지·베이스vs신호 비교 막대그래프로 재구성해 가독성 개선(`1558f5f`). 이걸로 Cyclical 재작업 라운드 마무리.
- **주간 "매수 신호 리포트" 신설 + 대시보드 연동** (2026-07-15) — growth/value 매수 신호 종목을 숫자 스크리닝→뉴스 검증 순으로 걸러 `docs/buy_signal_reports/YYYY-MM-DD.md`로 저장, 대시보드에 날짜별 조회 패널 추가(`6bd4ca5`). 무인 자동화(클라우드 routine, 로컬 헤드리스 실행)는 둘 다 시도 후 보류 — 현재는 사용자 요청 시 수동 진행 + 커밋 전 검토. 참고 절차: `automation/prompts/weekly_buy_signal_report_prompt.md`(`68e0a8b`).

---

## 다음

### ▶ 다음 할 일 (2026-10-07 저녁 정리 — 이 목록이 기준, 아래 "진행 기록"은 참고용)

**A. 다음 주간 리포트 전에 (10/13 회차)**
1. **스케줄러 재가동 점검** (사용자): 켜기 전 `git status` 깨끗한지, `.env`의 `SEC_USER_AGENT` 있는지 확인. 첫 실행 후 로그에서 `⚠⚠`(SPY 지연 경고)·`⚠ 정리 건너뜀`(수집 불완전)이 없는지 본다. 스케줄러가 꺼져 있어 10/7 이후 가격이 비어 있으니 켜면 한 번에 채워진다.
2. **리포트 확정 대기 항목** (1차 출처로 확인): CARR 2025Q4 영업이익 급락(1.0억 달러)이 일회성인지(10-K·8-K) / LEN 10월 Form 4와 10/2~10/5 급락 원인 / FICO Freddie Mac Bulletin 적용 인수일 원문과 판정(제외 vs 고위험 유지, 지난 회차는 유지로 결정 대기) / INCY 3분기 실적(10/26 전후, IPR&D 12.7억 달러 반영 후 신호 소멸 여부) / ISRG 10/20 · UHS 10/26 · GDDY 10/29(소송 마감 10/20·10/26) · DHI 10/29 실적.
3. 리포트는 프롬프트의 **검증 원칙 6개**를 따라 작성(서브에이전트에 가격 직접 검색 금지, `edgar_lookup.py` 사용, 날짜 불명확한 목표가 변경은 쓰지 않기). 데이터 점검 배지(⚠) 종목은 판정 보류.

**B. 데이터 품질 (우선순위 순)**
4. **매출 하위 태그 의심 181건 중 실제 오류 가리기**: HAS 14·WMB 13·DVN 7·VST 7·EQT 5·PEG 5·OKE 3·HSIC·FTV 각 3. (RSG 41·PM 16은 DB가 맞는 정의 차이.) `scripts/audit_financials.py` 결과(`data/analytics/audit_financials_mismatch.json`)의 `quarter_low_rev`가 출발점.
5. **매출 태그 매년 샘플링** (약 45분, 백그라운드): 지금은 2014·2017·2020·2023·최신 5개 시점만 봐서 연도 사이에 최상단 태그가 바뀐 종목(VRSK 2022)이 틀린다. `build_revenue_tag_map.py`의 `sample_years`를 매년으로.
6. **12월 결산이 아닌 131종목 점검**: `check_stale_quarters.py`가 12월 결산만 본다. 지연·연간 합계 대조를 비12월 결산으로 확장.
7. **4분기 보고 시점 혼합의 근본 해결 여부**: 지금은 감지·표시·보류만(방침 A, 40건). 플래그 종목이 신호에 자주 걸리면 연도별 보고 시점 일관성(Q1~Q4를 같은 시점 값으로)을 구현. 백테스트가 다시 달라진다.
8. **분기 CFO·CAPEX 독립 검증**: 연간 합계로만 확인했다(frames에 누적 값이 없음). 10-Q 현금흐름표 표본 대조.
9. **CIK 변경·지주회사 재편 종목 점검**: XOM처럼 SEC 종목 목록의 CIK가 새 법인으로 바뀐 종목이 더 있는지 — 종목별 수집 분기 수가 비정상으로 적은 종목을 찾아 `CIK_PREDECESSORS`(`collect_financials.py`)에 옛 CIK 등록.
10. 순이익 0인 분기 8건(WDAY는 실제 0에 가까움, WST 2017Q4 확인 필요)·매출 0인 분기(VRT는 SPAC 시절이라 정상).

**C. 자동화·분석 (여유 있을 때)**
11. 점검 로그 알림: 가격 수집 실패 알림(기존 보류 항목)과 묶어서 SPY 지연·수집 불완전 경고를 사람이 보게 하기.
12. 백테스트 노이즈: 포트폴리오 CAGR이 데이터 수정마다 ±2~3%p 흔들림(10슬롯 회전 구조) → 여러 시작 시점 평균 같은 방식으로 범위 추정.
13. 기존 보류: out-of-sample 검증(2006~2018 훈련 / 2019~2025 테스트), `classify_stocks.py` 스냅샷 `alpha_*` 컬럼, Cyclical 신규 후보군 재감사.

### 참고: 2026-10-07 진행 기록 (상세)

> **상태(2026-10-07):** 아래 수정과 2026-10-06 주간 리포트는 모두 **커밋·push 완료**(`56b3154` 수집 로직, `b8c3ed6` 점검 도구, `b9cd53c` 데이터 점검 플래그, `d4397e4` 문서, `213ec85` 리포트·대시보드). 이 프로젝트의 스케줄러는 꺼져 있다 — 켜면 `daily_update.sh`가 `git add -A`로 변경을 자동 push하니, 켜기 전에 작업 트리가 깨끗한지(`git status`) 확인할 것. 10/6 종가는 아직 수집 전이라(스케줄러 꺼짐) 리포트 가격은 10/5 종가 기준이다.

**2026-10-07 진행 기록 (오전)**
- 밤사이 push 없음 확인(이 프로젝트 스케줄러 꺼져 있음, 최신 커밋 `d4dc814` 그대로).
- 파생 DB·대시보드·백테스트를 run7(아래 수정 전부 반영) 기준으로 **재계산 완료** — 위 "현재 상태"의 재계산 필요 항목은 해결됨. 단 아직 미커밋.
- 추가 수정: ① SEC 요청 공용 재시도 함수 `config.sec_get`(간헐적 `self-signed certificate in certificate chain` SSL 오류 대응 — 어제 NVDA, 오늘 한 번 더 발생, 재시도하면 통과; 인증서 검증은 끄지 않음) ② `build_revenue_tag_map.py`가 비매출 태그 행에서 끊지 않고 첫 비용 행까지 읽도록 수정(HUM `Services` 1,264 → `Total revenues` 23,970 정상화, UNH·EQT·PM 정정).
- run7 결과: 감사 분기 매출 98.4 / 영업이익 98.4 / 순이익 99.2%, 연간 합계 변화 없음, 하위 태그 의심 181건(RSG 41·PM 16·HAS 14·WMB 13은 대부분 정의 차이). 백테스트 growth +16.84%(초과 +3.09%p) / value +26.30%(초과 +12.55%p). **run4→run7 사이 growth 17.84→18.76→16.84, value 22.82→25.46→26.30으로 ±2~3%p 흔들림 — 10슬롯 회전 구조라 데이터가 조금만 바뀌어도 매수 종목이 달라지는 시뮬레이션 노이즈.** 팩터 수준 결과는 안정적(핵심 신호 12m: growth +14.1→+14.3%, value +18.8%). 백테스트 CAGR은 소수점까지 믿지 말고 범위(growth +17~19%, value +23~26%)로 볼 것.
- 신호 변화 검증 완료: 매수 11→9(CTSH·IQV 소멸), 매도 6→7(DD 소멸, CARR·TRGP 신규). **TRGP 매도는 진짜**(SEC 원본: 총매출 TTM −2.0%, 예전 DB는 2024년에 계약 매출 태그·2025년부터 총매출 태그로 바뀌는 태그 혼용 때문에 +5.1%로 보였음). **XOM 버킷 변경은 정상**(예전 DB의 2025Q2·2026Q2 매출 0 구멍이 채워짐, 10-Q로 확인: 2026Q2 총수익 116,017). **CARR 매도는 신뢰 불가**(아래 2번 원인).
- 새로 밝힌 원인 — **4분기 파생 시 보고 시점 혼합(CARR 확정)**: 2023 연간 매출은 원래 22,098(2024-02 10-K) → 사업 분리 후 18,951(2025-02 10-K)로 재작성. 분기 값은 Q1 원래(5,273)·Q3 재작성(4,935)이 섞여 있어 Q4 = 18,951 − 16,200 = 2,751(정상은 직전 분기의 0.56배 아님). 4분기가 Q1~Q3 평균의 0.55배 미만·1.9배 초과인 (종목, 연도)가 **37종목 48건**(GE·DHR·JCI·D·OXY·CARR·PPG·FTV·JNJ·PFE·MMM 등 분사·매각 종목; MRNA·SNDK·EXE는 실제 변동 가능). 현재 신호 종목 중에는 CARR뿐.
- 새로 밝힌 한계 — **매출 태그 시대 샘플링 간격**: 2014·2017·2020·2023·최신 5개 시점만 샘플링해, 그 사이 연도에 최상단 태그가 바뀐 종목(VRSK 2022: 손익계산서 맨 윗줄이 `Revenues`인데 매핑은 계약 매출 태그)은 틀린다. 임의 표본 101건 중 일치 95건(94.1%, 불일치 6건: VRSK 2, 나머지는 KMB·DOV·GNRC 소급 재작성/CMS). 해결책은 매년 샘플링(약 3배, 45분).

**2026-10-07 저녁 — 2번 작업(분기 공백) 완료**
- 분기 공백 원인 = 52/53주 회계연도 라벨 불일치(4분기 값도 틀렸음) → 수정. 분기 공백 18 → 5종목(남은 건 신규 법인 이력 없음·분석 제외 섹터), 연간 합계 불일치 174 → 132. 상세는 `STATUS.md` "52/53주 회계연도 라벨 오류·분기 공백 수정".
- 수정 중 XOM 이력이 삭제되는 사고 → 안전장치(정리 70% 가드) + `CIK_PREDECESSORS`(XOM 옛 CIK 병합)로 복구·재발 방지. 전체 대조로 다른 종목 손상 없음 확인.
- 보충 범위 확대(중간 공시 구멍): TAP·CAH 채움.
- 최종 수치: 감사 분기 매출 98.4 / 영업이익 98.4 / 순이익 99.2%, 연간 99.4 / 99.1 / 97.9 / 99.5 / 99.7%. 백테스트 growth +17.95%(+3.83%p), value +27.87%(+13.75%p). 데이터 점검 플래그 38종목. 발행한 10/6 리포트와 현재 신호 비교: 신규 없음, 매수에서 LDOS 소멸(리포트에서 이미 제외한 종목).
- 미커밋: 이 섹션의 코드(`collect_financials.py`·`edgar_xbrl_fallback.py`·`collect_prices.py`·`build_dashboard.py`·`check_stale_quarters.py`)·`weekly_collect_financials.sh`·프롬프트·문서·대시보드.
- 남은 일(우선순위): ① 매출 하위 태그 의심 181건 중 확인(HAS·WMB·DVN·VST·EQT·PEG) ② 매출 태그 매년 샘플링(VRSK형) ③ 12월 결산 외 131종목 점검 ④ 분기 CFO·CAPEX 독립 검증 ⑤ CARR 2025Q4 급락 원인, LEN Form 4·급락 원인, FICO Bulletin 원문(다음 리포트용).

**2026-10-07 오후 — 1번 작업 완료 + SPY 정지 발견**
- 리포트 프롬프트에 "검증 원칙" 6개 추가(1차 출처 우선·`edgar_lookup.py` 사용법·가격은 `prices.db`만·날짜 규칙·단일 출처 표기·판정 변경 사실 재대조·데이터 자체 의심) + 3단계 서브에이전트 지시에 연결.
- `weekly_collect_financials.sh`에 `check_stale_quarters.py` 연결(실패해도 파이프라인은 멈추지 않음). 점검 스크립트는 기준 분기를 자동 계산. 현재 SEC 지연·수집 누락·미제출 0종목.
- 주간 수집 스킵 3종목 확인: EA(비공개 전환 의심, 가격 8/10 정지), AVB·EQR(부동산 분석 제외, 가격 없음). EA·SATS는 대시보드에서 제외 처리.
- **SPY 가격이 6/18에서 멈춰 있었음을 발견·수정**(위 STATUS "벤치마크 SPY 가격 정지"). 백테스트 최종: growth CAGR +16.82%(초과 +2.70%p), value +26.23%(초과 +12.11%p), SPY +14.12%. 어제까지의 수치는 SPY가 3.5개월 보합으로 계산돼 초과수익이 소폭 부풀려져 있었다.
- 미커밋: `collect_prices.py`·`build_dashboard.py`·`check_stale_quarters.py`·`weekly_collect_financials.sh`·프롬프트·STATUS/TODO·대시보드.

**2026-10-07 오전 후속 — 방침 A 구현 완료 (데이터 점검 플래그)**
- `scripts/compute_data_quality.py`(신규, 읽기 전용): 최근 5개 회계연도에서 ① 4분기 매출이 1~3분기 평균의 0.55배 미만·1.9배 초과(`q4_anomaly`) ② 매출 0인 분기 ③ 분기 공백을 감지해 `data/analytics/data_quality.json` 저장. 현재 51종목(q4 40·gap 18·zero 1; CARR·DD·GE·DHR·JCI·D·OXY·PPG·FTV·JNJ·PFE·MMM 포함). 이번 주 리포트 대상 종목(VEEV·ISRG·FICO·GDDY·UHS·INCY·MKC·LEN·DHI·CRL·TRGP)은 모두 깨끗.
- `build_dashboard.py`: 종목 레코드에 `dq` 추가, 회사명 옆 "⚠ 데이터 점검" 주황 배지(마우스 올리면 사유) + 상세 패널 "데이터 점검" 행(신호는 원본 공시로 확인 전까지 보류 문구).
- `automation/daily_update.sh`: `compute_valuation_current` 다음, `build_dashboard` 직전에 `compute_data_quality.py` 실행 추가.
- `automation/prompts/weekly_signal_report_prompt.md`: 신호 종목에 `dq`가 있으면 판정 보류("데이터 불연속 — 판정 보류") + `edgar_lookup.py`로 재작성 여부 확인 후에만 판정하도록 규칙 추가. 신호 있는 플래그 종목은 현재 CARR(매도)·LDOS(매수, 분기 공백 1개 — 숫자 스크리닝에서 이미 제외)뿐.
- 4분기 보고 시점 혼합 자체의 해결(연도별 보고 시점 일관성)은 하지 않음 — 플래그 종목이 늘어나 신호에 자주 걸리면 그때 재검토.

**현재 상태 (2026-10-06 저녁)**
- `data/stocks.db` = 아래 수정이 전부 반영된 **최신 수집 결과**(run6). 그러나 파생 DB(`ttm_valuation`·`ttm_growth`·`valuation`·`returns`·`analytics/`)와 `docs/index.html`은 **직전(run5) 수집 기준**이라 재계산이 필요하다.
- 재계산 순서(약 3분): `compute_ttm` → `compute_growth` → `compute_valuation` → `compute_returns` → `classify_stocks` → `compute_valuation_current` → `build_dashboard` (각각 `.venv/bin/python scripts/<이름>.py`). git push 없이 수동으로 돌릴 것.
- 그 뒤 백테스트 3종(`simulate_growth_factors_pit`·`simulate_value_factors_pit`·`simulate_growth_portfolio`, 각 3~5초)을 돌려 기준선과 비교. 기준선·백업은 `data/analytics/handoff_20261006/`(git 제외)에 있다.

**오늘 한 수정 (모두 `scripts/collect_financials.py`)**
1. YTD 선택: "가장 큰 값" → "기간이 가장 긴 레코드" (손실·부호 혼재 구간 버그)
2. Q1~Q3 손익(매출·영업이익·순이익)은 10-Q에 직접 보고된 3개월 값 사용, 4분기 = 연간 − (Q1+Q2+Q3). 분기는 `fp`가 아니라 기간 종료일로 판정
3. 같은 태그에서 직전 분기와 값이 정확히 같으면 SEC 원본 오류로 보고 다음 태그 사용 / 값이 0이면 뒤 순위 태그의 0 아닌 값 사용
4. 매출 태그: 종목별·시대별 "손익계산서 최상단 매출 태그" 매핑(`data/revenue_tag_map.json`, 생성: `scripts/build_revenue_tag_map.py`, 약 15분). 표준 총매출 태그 화이트리스트만 사용(`SalesRevenueGoodsNet`·`ServicesNet`·`PassengerRevenue` 등 하위 항목 태그는 제외 — UNH·INCY·BIIB에서 회귀가 났음)
5. companyfacts 갱신이 멈춘 종목은 10-Q/10-K 원본 XBRL에서 보충(`scripts/edgar_xbrl_fallback.py`)
6. SEC 연락처는 코드가 아니라 `.env`의 `SEC_USER_AGENT`(git 제외)에서 읽음

**검증 결과 (SEC frames 전수 대조: `scripts/audit_financials.py`, 약 6분)**
| 항목 | 원래 | 최종(run6) |
|---|---|---|
| 분기 매출 / 영업이익 / 순이익 일치율 | 97.3 / 97.3 / 98.4% | **98.5 / 98.4 / 99.2%** |
| 연간 합계 매출 / 영업이익 / 순이익 / CFO / CAPEX | 99.3 / 98.8 / 97.6 / 99.3 / 99.5% | 99.2 / 98.8 / 97.6 / 99.3 / 99.5% |
| 분석 대상 섹터 분기 불일치 | 748건 | 413건 (대부분 보고 시점 차이, 파생 오류 358 → 1) |
| 매출 하위 태그 의심 | 310건 | 197건 |
- 임의 표본 103건을 손익계산서 맨 윗줄과 대조: 101건 일치(98.1%). 불일치 2건(TEL 2014Q2, KMB 2014Q1)은 소급 재작성(KMB는 Halyard 분사) 차이.
- 백테스트(2013-12~2026-10): growth CAGR +21.04% → +17.84%(초과 +4.09%p), value +31.61% → +22.82%(초과 +9.07%p) — **run4 시점 값**이며 run6 반영 후 재측정 필요.

**남은 문제 (우선순위 순)**
1. **매출 하위 태그 의심 181건(run7) 중 실제 오류 가려내기**: RSG 41건은 DB가 맞음(순매출 vs 내부거래 제거 전 총액), PM 16건도 소비세 제외 순매출이 정답이라 DB가 맞음. 확인 남음: **HAS 14·WMB 13·DVN 7·VST 7·EQT 5·PEG 5·OKE 3·HSIC·FTV 각 3**. HUM은 해결(`Total revenues` 행까지 읽도록 수정).
2. **분사·사업매각 종목의 보고 시점 혼합**: DD·CARR 등은 분기마다 소급 재작성 시점이 달라 구간이 섞인다. 방침 결정 필요(최신 재작성 값으로 통일 vs 원래 보고값). 이번 대시보드의 "DD 매도 신호 소멸, CARR 신규 매도"는 이 때문에 신뢰 불가.
3. 분기 공백 78종목 261분기(MAA 12, FDXF 9, CI·CRH·DASH·TPL·BG·STE·MRNA·AMCR 6 등) 원인 미조사.
4. 순이익 0인 분기 8건·매출 0인 분기 12건(VRT는 SPAC 시절이라 정상, WDAY 2024Q1은 실제로 0에 가까움, WST 2017Q4는 확인 필요).
5. 독립 검증 못 한 것: 분기 CFO·CAPEX(연간 합계로만 확인), 12월 결산이 아닌 131종목의 연간 합계, `check_stale_quarters.py`도 12월 결산만 점검.
6. 주간 수집에서 스킵되는 3종목이 무엇인지, 신호 종목인지 확인.
7. 대시보드 신호 변화 재확인(재계산 후): 원래 대비 매수 11→9(CTSH·IQV 소멸, INCY는 ▲ 가치만), 매도 6 유지(DD 소멸, CARR 신규).

**커밋 계획 (완료 — 위 상태 참조)**
- 커밋 1 — 수집 로직·fallback·`.env` 분리: `scripts/collect_financials.py`, `config.py`, `update_universe.py`, `edgar_xbrl_fallback.py`, `build_revenue_tag_map.py`, `data/revenue_tag_map.json`, `.gitignore`
- 커밋 2 — 점검 도구: `audit_financials.py`, `check_stale_quarters.py`, `edgar_lookup.py`
- 커밋 3 — 문서: `STATUS.md`, `TODO.md`
- 리포트·대시보드(`docs/signal_reports/…`, `docs/index.html`)는 데이터가 확정된 뒤 주간 리포트를 다시 쓰고 나서 커밋

**주간 신호 리포트 (2026-10-06 회차) 재작성 시 필요한 1차 출처 확인 결과** (현재 `docs/signal_reports/2026-10-06.md`는 수정 전 수치의 초안 — 데이터 확정 후 다시 쓸 것)
- 공통: 최종 후보·고위험·신중 종목(VEEV·ISRG·FICO·GDDY·UHS·LEN·DHI)은 2023년 이후 감사 불일치 0건 — 판정은 데이터 문제와 무관.
- **LEN**: 버크셔 SEC Form 4 합계(9/17~10/2) 5억 9,529만 달러, 평균 $79.35. 10/1~10/2 매수만 1억 9,263만 달러(평균 $79.65, 10/5 제출). 10/2 기준 보유 Class A 2,844만 주 + Class B 56.8만 주(발행주식 2억 3,790만 주 대비 약 12.2%). 10/5 종가 $74.44는 평균 매수가보다 6.2% 낮음. 급락 원인 미확인.
- **FICO**: Freddie Mac 공식 페이지에 9/30 날짜로 "Classic FICO와 VantageScore 4.0 크레딧 수수료 일치" 공지. 실제 적용 인수일은 Bulletin 본문 미확인(JS 렌더링). 지난주 기준("시행일 확정 시 제외 검토")이 이미 충족됐을 가능성 → 판정 결정 필요(제외 vs 고위험 유지).
- **UHS**: Federal Register에 7/23 제안규칙만 있고 확정규칙은 없음(의견 마감 9/21). 10/1 임계값 동결은 법(OBBBA) 조항이라 규칙과 무관하게 발효.
- **GDDY**: Gen Digital 8-K(9/28, Reg FD): CEO가 인수설을 확인·부인하지 않고 인수 판단 기준 5개(자사주 매입과의 비교 포함)만 공개. "가능성 낮아짐"은 RBC 해석.
- **MKC**: 10-Q 확인 — 지분재평가 이익 8억 6,680만 달러는 2026-01-02 McCormick de Mexico 지분 25% 추가 취득(총 75%) 시 FQ1 2026에 인식 → TTM에서는 2027년 3월경 FQ1 2027 반영 때 빠짐. 3분기 영업이익 −25%는 특별비용 1억 4,150만 달러(거래·통합비 9,530만, 자산손상 4,310만) 때문, 특별비용 제외 시 약 +22%.
- **INCY**: 일회성 환입(Contract dispute settlement)은 2025Q2 2억 4,225만 달러(리포트의 2억 4,600만은 오차). Vega 인수는 2026-07-06 종결, IPR&D 약 12억 7,000만 달러는 2026Q3 인식. 2024Q2~Q4 순이익은 −444.6/106.5/201.2(백만 달러)로 수정됐고 `ni_1y`는 +278%가 아니라 약 +85%.
- **DHI**: Freddie Mac 30년 금리 10/1 7.28%(전주 7.03%). FY4Q 실적 10/29.
- **CRL**: 새 악재 없음, 10/5 종가 $310.77(최근 1년 최고).
- 서브에이전트가 가져온 주가·목표가는 `prices.db`와 안 맞는 경우가 있었음(FICO $1,195.85 등) — 가격은 항상 `prices.db`에서.

**프로세스 개선 (미완)** — `automation/prompts/weekly_signal_report_prompt.md` 수정: ① 1차 출처(SEC 공시·원문) 우선, `scripts/edgar_lookup.py`(filings/form4/grep) 사용 ② 가격은 `prices.db` 값을 프롬프트에 주입 ③ 기사 게재일 기재, 이전 회차 이전 기사는 새 소식으로 세지 않기 ④ 2차 출처 단일 근거 수치는 "단일 출처" 표시 ⑤ 판정을 바꿀 사실만 1차 출처로 재대조. 그리고 `automation/weekly_collect_financials.sh` 끝에 `check_stale_quarters.py` 연결.

**참고**
- 백업·비교 기준(git 제외): `data/analytics/handoff_20261006/` — `stocks_before_ytdfix.db`(원래 DB), 수정 전 백테스트 출력, 감사 결과(run2·run4·run6), 대시보드 신호 스냅샷, YTD 선택 변경 목록.
- 상세 기록: `STATUS.md`의 "재무 수집 YTD 선택 버그 수정 …(2026-10-06)" 섹션, 메모리 `project_ytd_fix_backtest`.
- 읽기 전용 점검 도구: `scripts/audit_financials.py`(전수 대조), `scripts/check_stale_quarters.py`(SEC 지연 종목), `scripts/edgar_lookup.py`.


- **주간 매수 신호 리포트 — 몇 주 더 수동 발행하며 지켜보기** — 매주 사용자가 요청하면 수동으로 신호 스크리닝+뉴스 검증+리포트 작성+커밋. 몇 회차 쌓인 뒤 자동화할지(어느 단계까지, 어떤 방식으로) 판단.

---

## 보류

- `classify_stocks.py` 스냅샷 CSV에 `alpha_12m/15m/18m` 컬럼 추가
- out-of-sample 검증 (2006~2018 훈련 / 2019~2025 테스트)
- 가격 수집 실패 알림
- Cyclical의 semiconductor/leisure/retail/capital_goods/aerospace_defense 등 — GICS 매칭 외에 "완전히 새로운 후보군"이 더 있는지 재감사 (이번엔 GICS 산업 태그 매칭만 수행)
