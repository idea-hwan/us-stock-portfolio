"""
공통 설정 — 모든 분석 스크립트에서 import해서 사용
"""

# 기업 펀더멘털 분석에서 제외할 섹터
# 제외 이유:
#   Financial Services  — 매출·영업이익 개념 상이, 레버리지가 사업 모델. 순이익·CFO 중심
#   Real Estate         — REIT는 FFO 기준 밸류에이션, 일반 이익 지표 부적합
#
# Energy·Basic Materials(원자재 사이클 → Cyclical 버킷 후보)·Utilities(경기방어적
# → Growth/Value 자동분류)는 2026-07-02에 stock_universe.csv로 편입됨 (401종목 확장).
EXCLUDED_SECTORS = {
    "Financial Services",
    "Real Estate",
}


# ── SEC EDGAR 요청 헤더 ──────────────────────────────────────────────
# SEC는 실제 연락 가능한 User-Agent를 요구한다. 연락처는 코드에 넣지 않고
# 환경변수 SEC_USER_AGENT 또는 저장소 루트의 .env(커밋 제외)에서 읽는다.
def sec_headers() -> dict:
    import os
    import sys
    from pathlib import Path

    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        env = Path(__file__).resolve().parent.parent / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                key, _, val = line.partition("=")
                if key.strip() == "SEC_USER_AGENT":
                    ua = val.strip().strip('"').strip("'")
    if not ua:
        sys.exit("SEC_USER_AGENT가 없음 — 저장소 루트 .env 또는 환경변수에 "
                 "'SEC_USER_AGENT=이메일 (research)' 형식으로 설정하세요.")
    return {"User-Agent": ua}


def sec_get(url: str, headers: dict | None = None, timeout: int = 30, retries: int = 5):
    """SEC 요청 공용 함수 — 간헐적 SSL·연결 오류와 429/5xx를 지수 백오프로 재시도한다.
    (2026-10 SEC 호스트에서 'self-signed certificate in certificate chain' SSL 오류가 간헐적으로 발생,
    재시도하면 통과했다. 인증서 검증은 끄지 않는다.) 404 등 그 외 HTTP 오류는 재시도 없이 바로 올린다."""
    import time

    import requests

    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers or sec_headers(), timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = requests.HTTPError(f"HTTP {r.status_code}: {url}")
            else:
                r.raise_for_status()
                return r
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last = e
        time.sleep(min(2 ** i, 20))
    raise last
