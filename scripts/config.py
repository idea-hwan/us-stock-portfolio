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
