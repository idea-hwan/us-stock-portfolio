# US Stock Dashboard 기획서

> 작성일: 2026-06-24  
> 목적: 미국 주식 팩터 기반 모니터링 대시보드 — 설계 기준 문서

---

## 1. 목표

분기 재무 데이터 + 매일 갱신 가격을 합쳐,  
**버킷(성장/가치/경기순환) + 팩터 신호**를 한눈에 보는 대시보드를 만든다.

- 매일 최신 가격 자동 반영
- 분기별 재무 업데이트 수동 반영
- 어디서든 URL 하나로 접근 가능

---

## 2. 시스템 구조

```
[데이터 수집]
  collect_prices.py         → data/prices.db          (매일 자동, UTC 00:00)
  compute_ttm/growth/val    → 각 DB                   (분기별 수동)
  classify_stocks.py        → data/analytics/*.csv    (분기별 수동)

[HTML 생성]
  build_dashboard.py        → docs/index.html         (매일 자동, 가격 수집 후)

[배포]
  git push → GitHub Pages   → https://username.github.io/us-stock-portfolio/
```

### 자동화 (launchd / cron)

```
UTC 00:00 매일
  1. python scripts/collect_prices.py
  2. python scripts/build_dashboard.py
  3. git add docs/index.html && git commit -m "daily update" && git push
```

### 수동 업데이트 (분기별)

```bash
# 분기 실적 발표 시즌 (2~3월, 5~6월, 8~9월, 11~12월) 마무리 후 실행
python scripts/compute_ttm.py
python scripts/compute_growth.py
python scripts/compute_valuation.py
python scripts/compute_returns.py
python scripts/classify_stocks.py
python scripts/build_dashboard.py
git add docs/ && git commit -m "quarterly update YYYYQN" && git push
```

---

## 3. 대시보드 표시 내용

### 3-1. 헤더 요약

| 항목 | 내용 |
|------|------|
| 마지막 가격 업데이트 | 2026-06-24 (UTC 00:00 기준) |
| 마지막 재무 업데이트 | 2026Q1 (2026-05-20) |
| 표시 종목 수 | N / 전체 M종목 |

### 3-2. 종목 테이블 (기본 100개)

| 컬럼 | 설명 | 비고 |
|------|------|------|
| # | 시총 순위 | |
| Ticker | 종목 코드 | |
| 버킷 | growth / value / cyclical(업종) | 색상 구분 |
| 기준 분기 | 마지막 재무 스냅샷 시점 | anchor_term |
| 이익 추세 | ▲▲ 가속 / ▲ 성장 / ▼ 역성장 / ▼▼ 2y역성장 | op 기반 |
| 밸류에이션 | 저평가 / 고평가 / 중립 | 20d vs 4y 평균 |
| 팩터 신호 | ★★ / ★ / ○ / — / ✗ | 버킷별 로직 |
| 1M% | 1개월 수익률 | 현재 가격 기준 |
| 3M% | 3개월 수익률 | |
| 1Y% | 1년 수익률 | |
| 시총 | $B 단위 | |

### 3-3. 팩터 신호 기준 (버킷별)

**Growth:**
- ★★ — op 1y+2y 역성장 + rev 가속 (12m 최강 신호)
- ★  — op 1y 역성장 + rev 가속 (12m 기본)
- ○  — op 2y 역성장 + rev2y 가속 (18m 플레이)
- —  — 신호 없음

**Cyclical (semiconductor):**
- ★ — op 2y 역성장 (사이클 바닥 신호)

**Cyclical (housing/construction):**
- ★ — P/S + P/E + P/FCF 모두 4y 평균 이하

**Cyclical (leisure/retail):**
- ★ — 밸류 저평가 + capex 증가 + op 회복

**Value:**
- ✗ — 회피 조건 (매출 2y 역성장 / P/S+역성장 / P/OP+역성장)

---

## 4. 인터랙션

### 4-1. 필터 (JS, 클라이언트 사이드)

- 버킷 선택: `전체 / growth / value / cyclical`
- 신호 강도: `전체 / ★★ / ★ 이상 / ○ 이상`
- 밸류에이션: `전체 / 저평가만`
- 종목 직접 검색: ticker 입력으로 하이라이트

### 4-2. 종목 수 선택

- 기본: 시총 상위 100
- 선택: 200 / 전체 (~330) 토글

### 4-3. 정렬

- 기본: 시총 순
- 클릭 정렬: 1M% / 3M% / 1Y% / 신호 강도

---

## 5. 기술 스택

| 구분 | 기술 |
|------|------|
| HTML 생성 | Python (`build_dashboard.py`) |
| 스타일 | 인라인 CSS (다크 테마, 외부 의존성 없음) |
| 인터랙션 | 인라인 JavaScript (필터/정렬, 라이브러리 없음) |
| 배포 | GitHub Pages (정적 파일) |
| 자동화 | macOS launchd (plist) |
| 데이터 | SQLite DB + analytics CSV |

> 외부 CDN / 라이브러리 없음 → 오프라인에서도 동작, GitHub Pages 제약 없음

---

## 6. 파일 구조

```
us-stock-portfolio/
  scripts/
    collect_prices.py         # 기존 (변경 없음)
    build_dashboard.py        # 신규 — 대시보드 HTML 생성 메인 스크립트
    classify_stocks.py        # 기존 (변경 없음)
  data/
    prices.db
    analytics/
      *.csv
  docs/
    index.html                # GitHub Pages 메인 (빌드 결과물)
    dashboard_plan.md         # 이 문서
  automation/
    com.hwan.stockdash.plist  # macOS launchd 설정
    daily_update.sh           # cron 실행 스크립트
```

---

## 7. 작업 순서

1. `build_dashboard.py` 작성 — 기존 `top100_dashboard.py` 기반으로 재작성
   - 종목 수 100 → 가변
   - JS 필터/정렬 추가
   - 현재 가격 실시간 반영 (prices.db 최신 날짜 기준)
2. GitHub repo 설정 + Pages 활성화 (`docs/` 폴더 기준)
3. `automation/daily_update.sh` 작성
4. macOS launchd plist 등록 (UTC 00:00 = KST 09:00)
5. 테스트 — 수동 실행 후 Pages 반영 확인

---

## 8. 미결 사항

- [ ] GitHub repo 이름 / username 확인 → Pages URL 확정
- [ ] 시총 상위 100 기준: 현재 시총 동적 계산 vs 고정 리스트?
- [ ] 종목 추가/제거: 사용자가 직접 리스트 편집 (`config.py`에 오버라이드)?
- [ ] 가격 수집 실패 시 알림 방법 (메일? 로그만?)
