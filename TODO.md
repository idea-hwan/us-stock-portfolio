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

---

## 다음

- **[최우선] Cyclical 버킷 재작업 — 가격→팩터 역방향 방법론, 업종별 순차 진행 중**
  - **배경**: semiconductor 베이스 12m 알파가 +5~7%로 비정상적으로 높은 이유 추적 → `stock_universe.csv`가 오늘 기준 시총 상위 종목만 담고 있어, 과거엔 컸지만 지금은 인수합병·상장폐지로 사라진 종목이 전체 백테스트 기간에서 통째로 빠져있는 **유니버스 자체의 생존편향** 발견(무료 소스로는 해결 불가, 포기). 대안으로 "팩터→결과"가 아니라 **"가격 turning point(zigzag 30% 되돌림) 먼저 찾고 → 그 앞뒤로 재무 팩터가 어떻게 끼었는지" 역방향 접근**으로 전환.
  - **진행 현황 — cyclical_universe.txt 전체 카테고리를 대표주 기준으로 완료(2026-07-13)**: 반도체(MU/AMAT/NVDA) → 자동차(F/GM, 방법론 부적합으로 종료) → 에너지(XOM/SLB/EOG)·소재(FCX/CF/NUE) → 건설(MLM/URI/PWR) → 레저(LVS/CCL)·리테일(BBY/AMZN)·자본재(CAT/VRT)·항공방산(BA/RTX)·운송(DAL/UNP). 상세: `docs/cyclical_semiconductor_analysis.md`, `docs/cyclical_energy_materials_analysis.md`, `docs/cyclical_construction_analysis.md`, `docs/cyclical_leisure_retail_capital_transport_analysis.md`. **종합 분류: `docs/cyclical_classification_summary.md`** — 사이클있음/없음(유념대상)/판단보류 3그룹.
  - **실전 결론**: 매수/매도 타이밍 신호로 실제 쓸 수 있는 건 여전히 반도체(MU/AMAT)뿐. "사이클 없음"(NVDA/PWR/VRT, 경계사례 AMZN)은 전부 AI 데이터센터 인프라 수혜주로 몰려있고 진짜 무사이클인지 아직 다운턴을 안 겪어서인지 구분 불가(n=0 사이클). "판단보류"(F/GM/BA/RTX/URI/BBY/MLM/UNP)는 대표성·데이터품질 문제로 이 방법론 자체가 안 맞음.
  - **재사용 가능한 도구**: `scripts/archive/cyclical_price_factor/`에 zigzag 탐지(`zigzag.py`)·재무 팩터 조회(`factors.py`) 스크립트 저장.
  - 참고: cyclical 매수/매도 신호는 대시보드에서 이미 꺼둔 상태(2026-07-08) — 이 재작업 전체가 끝나면 `signal_cyclical`/`sell_cyclical` 호출부 복원 검토(다만 반도체 외 업종은 신호화 실패했으므로 복원 범위는 반도체 한정 검토).
  - **git 커밋 아직 안 함** — 사용자와 결과 리뷰 중, 다음에 커밋 여부 확인.
  - 남은 여지: auto의 부품리테일/중고차(ORLY/AZO/CVNA) 미확인 보류, energy/materials/leisure 등 카테고리 내 나머지 종목으로 표본 확장(대표주 1~3개만 봄, 전체 검증은 아님).
  - 상세 배경: 메모리 `feedback_backtest_methodology`(원칙 7~8), `project_next_steps`.

---

## 보류

- `classify_stocks.py` 스냅샷 CSV에 `alpha_12m/15m/18m` 컬럼 추가
- out-of-sample 검증 (2006~2018 훈련 / 2019~2025 테스트)
- 가격 수집 실패 알림
- Cyclical의 semiconductor/leisure/retail/capital_goods/aerospace_defense 등 — GICS 매칭 외에 "완전히 새로운 후보군"이 더 있는지 재감사 (이번엔 GICS 산업 태그 매칭만 수행)
