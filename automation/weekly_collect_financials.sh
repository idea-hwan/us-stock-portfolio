#!/bin/bash
# 매주 1회 EDGAR 분기 실적 원본 수집 (로컬 전용, git push 없음)
#
# collect_financials.py는 "새 공시가 있는 종목만 골라서" 받는 게 아니라
# 매번 유니버스 전체(약 503종목)의 재무 이력을 통째로 재요청한다 — 그래서
# 새 실적이 하나도 안 나온 날도 소요 시간이 똑같이 ~5~6분 걸린다(고정비용).
# 이 고정비용을 매일 감수할 필요가 없어서 주 1회로 분리했다.
#
# 여기서 갱신한 stocks.db는 그 자체로는 지표에 반영되지 않는다 —
# 다음 daily_update.sh 실행(가격 다음 매일 도는 지표 계산 체인)에서
# compute_ttm.py 이하가 자동으로 최신 재무를 읽어 반영한다.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"

LOG_DIR="$ROOT/automation/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d)_weekly.log"

{
    echo "===== weekly_collect_financials 시작 $(date '+%Y-%m-%d %H:%M:%S') ====="
    "$PY" scripts/collect_financials.py
    echo "===== weekly_collect_financials 완료 $(date '+%Y-%m-%d %H:%M:%S') ====="
} >> "$LOG_FILE" 2>&1
