# AGENTS.md — 에이전트용 작업 가이드

미국 주식(약 400종목)을 growth / value / cyclical 버킷으로 분류하고, 매수(▲)·매도(▼) 신호를 계산해 정적 대시보드로 배포하는 개인 프로젝트.

- 대시보드: `docs/index.html` → GitHub Pages (https://idea-hwan.github.io/us-stock-portfolio/)
- 진행 기록: `STATUS.md`(날짜별 작업 상세), `TODO.md`(완료/다음/보류). 둘 다 크다. 필요한 섹션만 찾아 읽을 것.
- 방법론 문서: `docs/*.md` (데이터 수집, TTM, 성장률, 밸류에이션, 신호 그리드)

## 환경

- Python 3.10+ (`dict | None` 문법 사용). 가상환경은 저장소 루트 `.venv`.
- 설치: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- 실행은 항상 `.venv/bin/python scripts/xxx.py` (저장소 루트에서).
- `.env`(커밋 금지): `SEC_USER_AGENT=이메일 (research)` 한 줄. SEC 요청 헤더는 `scripts/config.py`의 `sec_headers()`/`sec_get()`만 쓴다.

## 데이터 (git 제외 — 다른 PC로 옮길 때 직접 복사)

| 경로 | 내용 | 재생성 |
|------|------|--------|
| `data/stocks.db` | EDGAR 분기 재무 원본 | `collect_financials.py` (~6분) |
| `data/prices.db` | 일별 수정주가 | `collect_prices.py` |
| `data/ttm_*.db`, `valuation.db`, `returns.db` | 계산 결과 | daily 파이프라인 |
| `data/analytics/all_stocks.csv` 등 | 분류·현재 밸류에이션·품질 플래그 | daily 파이프라인 |
| `data/analytics/pit_buckets.db` | PIT 버킷 판정(백테스트용) | **생성 스크립트 없음 — 반드시 복사** |
| `data/analytics/handoff_20261006/` | YTD 버그 수정 전 백업·기준선 | **재생성 불가 — 복사** |

`reference/`(6GB)는 별개 참고 저장소. 스크립트가 쓰지 않는다.

## 파이프라인

```
collect_prices → compute_ttm → compute_growth → compute_valuation → compute_returns
→ classify_stocks → compute_valuation_current → compute_data_quality → build_dashboard
```

- `automation/daily_update.sh`: 위 체인 + 변경 있으면 `git add -A` → commit → push (자동).
- `automation/weekly_collect_financials.sh`: `collect_financials.py` + 지연 점검. push 없음.
- `automation/scheduler_data_collection.py`: 화~토 KST 09:00 daily, 일요일 weekly, 월요일 스킵.
  실행: `caffeinate -i .venv/bin/python automation/scheduler_data_collection.py` (터미널 상시 실행).
- **스케줄러는 한 PC에서만 돌린다.** 두 곳에서 돌리면 자동 push끼리 충돌한다.

## 작업 규칙

1. **커밋은 작업 단위로 바로.** daily_update가 `git add -A`로 쓸어가므로, 미완성 변경을 두면 "auto: dashboard update"에 섞여 push된다. 작업 마무리 때 커밋 여부를 사용자에게 먼저 묻는다.
2. **push·force-push 등 원격에 영향 주는 동작은 설명 후 확인받는다.** 저장소는 Public이다.
3. **LLM 판단이 들어간 작업은 무인 자동화하지 않는다.** 주간 신호 리포트는 사용자가 요청할 때 수동 진행, 검토 후 커밋.
4. **자동화는 launchd/cron보다 `caffeinate -i` + 파이썬 스크립트**를 기본으로 제안한다.
5. **외부 요청에 회사 메일 금지.** SEC는 `.env`의 `SEC_USER_AGENT`만. 이메일을 지어내지 않는다.
6. **숫자 포맷:** `65.2B`, `1.5M` 같은 약어 금지. 콤마 포맷 또는 헤더에 단위 표기.
7. **사용자 대신 쓰는 글(X 게시물 등):** 짧고 딱딱 끊어지는 단문. 해시태그·존댓말 없음.

## 백테스트 방법론 원칙 (사용자 검증 완료)

1. **PIT 보정** — 버킷 판정은 각 앵커 시점까지의 데이터로만 롤링 재판정. 현재 상태를 과거에 역산 적용 금지.
2. **중앙값** — 알파 집계는 평균이 아니라 median.
3. **신호는 단일 조건** — 다단계 tier 금지. 베이스 대비 유의미한 조합 하나만 남긴다.
4. **버킷은 비배타적** — 다른 버킷 소속 여부로 편입/제외하지 않는다.
5. **서사적 배제 금지** — "방어적으로 보인다" 같은 이유로 빼지 않는다. 배제 근거는 GICS 섹터 등 구조적이어야 한다.
6. **표본 최대 확보** — 엣지가 불확실해도 GICS 매칭되면 일단 편입.
7. **베이스가 너무 좋으면 유니버스 생존편향부터 의심** — `stock_universe.csv`는 오늘 기준 리스트다.
8. **Cyclical 분석은 가격 turning point(zigzag) 먼저, 팩터는 그다음.** 업종마다 리드/래그 방향이 다를 수 있으니 일반화하지 않는다.

## 주간 매수·매도 신호 리포트

- 절차서: `automation/prompts/weekly_signal_report_prompt.md` (이 문서대로 진행)
- 결과: `docs/signal_reports/YYYY-MM-DD.md`, 이후 `build_dashboard.py`로 대시보드 반영
- 핵심: 1차 출처(SEC 공시·IR) 우선, 가격은 `data/prices.db`에서만, 기사 게재일 확인, 직전 4주 리포트와 교차검증.
- 절차서의 "서브에이전트"는 종목별 병렬 조사를 뜻한다. 병렬 실행이 안 되면 종목별로 순서대로 조사해도 된다. 같은 업종 종목끼리는 반드시 나란히 놓고 판정 일관성을 확인한다.
