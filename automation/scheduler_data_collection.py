#!/usr/bin/env python3
"""
로컬 데이터 수집 스케줄러 — 터미널을 켜둔 채로 계속 실행해두는 방식.

실행:
    caffeinate -i python3 automation/scheduler_data_collection.py

동작 (KST 09:00 = UTC 00:00 실행 기준. 미국 동부시간은 KST보다 13~14시간
느려서, KST 아침 실행 시점엔 "전날 저녁(미국 동부시간)"의 종가가 반영됨):

    KST 실행일  →  미국 동부시간(전날 저녁)  →  새로 생기는 종가
    월          →  일요일 저녁 (휴장)         →  없음 → 스킵
    화          →  월요일 저녁 (개장)         →  월요일 종가
    수          →  화요일 저녁 (개장)         →  화요일 종가
    목          →  수요일 저녁 (개장)         →  수요일 종가
    금          →  목요일 저녁 (개장)         →  목요일 종가
    토          →  금요일 저녁 (개장)         →  금요일 종가
    일          →  토요일 저녁 (휴장)         →  없음 → 가격 잡 없음

    - 화~토 00:00 UTC (KST 09:00) → daily_update.sh
        (가격 수집 → TTM → 성장률 → 밸류에이션 → 수익률 → 종목분류
         → 현재 밸류에이션 재계산 → 대시보드 재생성)
    - 토요일 02:00 UTC (KST 11:00) → weekly_collect_financials.sh
        (EDGAR 분기 실적·8-K 잠정 배지. 한국 잠정실적 KST 12:00보다 앞.
         고정비용 ~10분. 지표 반영은 일요일 리포트와 다음 화요일 daily)
    - 일요일 05:00 UTC (KST 14:00) → weekly_signal_report.sh
        (주간 매수·매도 신호 리포트. 한국 일요일 16:00 가격·18:00 리포트보다 앞)
    - 월요일: 아무 것도 실행하지 않음 (새 종가 없음)

상세 로그는 automation/logs/YYYYMMDD_{daily,weekly,signal}.log 에 쌓인다.
이 스크립트는 "언제 뭘 실행했는지"만 automation/logs/scheduler.log 에 기록한다.

Ctrl+C로 종료.
"""

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT            = Path(__file__).parent.parent
DAILY_SCRIPT    = ROOT / 'automation' / 'daily_update.sh'
COLLECT_SCRIPT  = ROOT / 'automation' / 'weekly_collect_financials.sh'
REPORT_SCRIPT   = ROOT / 'automation' / 'weekly_signal_report.sh'
LOG_FILE        = ROOT / 'automation' / 'logs' / 'scheduler.log'

CHECK_INTERVAL_SEC = 20


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def run(script: Path, name: str):
    log(f'{name} 실행 시작')
    try:
        subprocess.run(['bash', str(script)], check=True)
        log(f'{name} 완료')
    except subprocess.CalledProcessError as e:
        log(f'{name} 실패 (exit {e.returncode}) — 상세는 automation/logs/*.log 참조')


def main():
    log('스케줄러 시작 — 화~토 KST 09:00 가격+계산, 토요일 KST 11:00 재무수집, 일요일 KST 14:00 주간 리포트, 월요일 스킵. Ctrl+C로 종료.')
    last_daily = None
    last_collect = None
    last_report = None

    try:
        while True:
            now     = datetime.now(timezone.utc)
            today   = now.date()
            weekday = now.weekday()  # 월=0 화=1 수=2 목=3 금=4 토=5 일=6

            # 화~토 KST 09:00. 월요일·일요일 00:00 UTC는 가격 잡 없음.
            if now.hour == 0 and now.minute == 0 and last_daily != today:
                last_daily = today
                if 1 <= weekday <= 5:
                    run(DAILY_SCRIPT, 'daily_update')

            # 토요일 KST 11:00 = 토요일 02:00 UTC
            if weekday == 5 and now.hour == 2 and now.minute == 0 and last_collect != today:
                last_collect = today
                run(COLLECT_SCRIPT, 'weekly_collect_financials')

            # 일요일 KST 14:00 = 일요일 05:00 UTC
            if weekday == 6 and now.hour == 5 and now.minute == 0 and last_report != today:
                last_report = today
                run(REPORT_SCRIPT, 'weekly_signal_report')

            time.sleep(CHECK_INTERVAL_SEC)
    except KeyboardInterrupt:
        log('스케줄러 종료 (Ctrl+C)')
        sys.exit(0)


if __name__ == '__main__':
    main()
