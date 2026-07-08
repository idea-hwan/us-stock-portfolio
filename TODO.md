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

---

## 다음

- **[최우선] Cyclical 버킷 재작업 — 팩터→결과가 아니라 가격→팩터 방향으로 뒤집기** (착수 예정, 오래 걸리는 작업이라 별도 세션에서)
  - **배경**: semiconductor 베이스 12m 알파가 +5~7%로 비정상적으로 높은 이유 추적 → `stock_universe.csv`가 오늘 기준 시총 상위 종목만 담고 있어, 과거엔 컸지만 지금은 인수합병·상장폐지로 사라진 종목(Maxim/Xilinx/Cypress/Linear Tech/Altera/Microsemi 등)이 전체 백테스트 기간에서 통째로 빠져있는 **유니버스 자체의 생존편향** 발견. yfinance·stooq 둘 다 이런 상폐 종목의 과거 가격을 대부분 못 줌(9개 중 2개만 성공) — 무료 소스로는 완전한 해결 불가, 유료 point-in-time 데이터(CRSP/Compustat급)가 필요해 이번엔 포기.
  - **결론**: Cyclical(및 growth/value도 동일 원리로 일부) 절대 알파 수치는 생존편향으로 부풀려져 있다고 보고 해석해야 함. 그래서 접근 자체를 바꾸기로 함 — 지금까지는 "팩터를 정하고 → 그 팩터가 뜬 시점 이후 알파가 어떻게 나오는지" 봤는데(팩터→결과), 다음엔 **"주가가 실제로 경기순환적으로 움직였는지(진짜 저점·고점을 찍었는지) 가격 자체를 먼저 보고 → 그 turning point 앞뒤로 어떤 팩터(밸류에이션·CAPEX·매출 등)가 실제로 끼어 있었는지" 역방향으로 접근**(가격→팩터). 유의미한 결과가 안 나올 수도 있음을 전제하고 시작.
  - 상세 배경: 메모리 `feedback_backtest_methodology`(원칙 7), `project_next_steps`.

### GitHub Pages 설정 (보류 — git 저장소 자체가 아직 없음)
- 사용자가 git 커밋/push에 아직 익숙하지 않아 우선 로컬 자동화만 진행하기로 함 (2026-07-07)
- 나중에 진행하게 되면: git init → GitHub 저장소 생성/remote 연결 → `docs/` 폴더 기준 Pages 활성화 → daily_update.sh/weekly_collect_financials.sh 끝에 git add/commit/push 추가

---

## 보류

- `classify_stocks.py` 스냅샷 CSV에 `alpha_12m/15m/18m` 컬럼 추가
- out-of-sample 검증 (2006~2018 훈련 / 2019~2025 테스트)
- 가격 수집 실패 알림
- Cyclical의 semiconductor/leisure/retail/capital_goods/aerospace_defense 등 — GICS 매칭 외에 "완전히 새로운 후보군"이 더 있는지 재감사 (이번엔 GICS 산업 태그 매칭만 수행)
