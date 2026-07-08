"""
공통 설정 — 모든 분석 스크립트에서 import해서 사용
"""

# 기업 펀더멘털 분석에서 제외할 섹터
# 제외 이유:
#   Financial Services  — 매출·영업이익 개념 상이, 레버리지가 사업 모델. 순이익·CFO 중심
#   Real Estate         — REIT는 FFO 기준 밸류에이션, 일반 이익 지표 부적합
#   Energy              — 원자재 가격 종속, 기업 펀더멘털보다 commodity cycle 영향 큼
#   Basic Materials     — 마이닝(FCX·NEM 등) 포함, 동일 이유
#   Utilities           — 규제독점, 수익률이 정부 규제로 결정, rate base 밸류에이션
EXCLUDED_SECTORS = {
    "Financial Services",
    "Real Estate",
    "Energy",
    "Basic Materials",
    "Utilities",
}
