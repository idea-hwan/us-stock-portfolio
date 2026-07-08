#!/bin/bash
# 매일 자동 갱신 (로컬 전용, git push 없음)
#   1. 가격 갱신
#   2. TTM 재계산
#   3. 성장률 재계산
#   4. 밸류에이션 배수(20d/4y) 재계산
#   5. 선행수익률 + SPY alpha 재계산
#   6. 종목 분류(growth/value/cyclical) 재계산
#   7. 현재(오늘 가격 기준) 밸류에이션 재계산
#   8. 대시보드(docs/index.html) 재생성
#
# EDGAR 재무 원본 수집(collect_financials.py)은 여기 없음 — 고정비용 5~6분이라
# 매주 1회 automation/weekly_collect_financials.sh 로 분리. 그 결과(stocks.db)는
# 다음 날 이 스크립트의 2~8단계에서 자동으로 반영됨.
#
# 순수 계산 단계(2~8)는 401종목 기준 약 3분 — 매일 돌려도 부담 없음.
# 새 버킷 편입/제외 등 판단이 필요한 변경은 자동으로 하지 않는다 —
# 결과 CSV(data/analytics/*_stocks.csv)는 필요할 때 사람이 검토할 것.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

LOG_DIR="$ROOT/automation/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d)_daily.log"

{
    echo "===== daily_update 시작 $(date '+%Y-%m-%d %H:%M:%S') ====="
    "$PY" scripts/collect_prices.py
    "$PY" scripts/compute_ttm.py
    "$PY" scripts/compute_growth.py
    "$PY" scripts/compute_valuation.py
    "$PY" scripts/compute_returns.py
    "$PY" scripts/classify_stocks.py
    "$PY" scripts/compute_valuation_current.py
    "$PY" scripts/build_dashboard.py
    echo "===== daily_update 완료 $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE" 2>&1
