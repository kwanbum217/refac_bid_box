"""연도별 WTO 정부조달협정 기준 고시금액."""

NOTICE_AMOUNT_BY_YEAR = {
    2023: 220_000_000,  # 기획재정부 2022-12-30 보도자료, 고시 제2022-32호
    2024: 220_000_000,  # 기획재정부 2022-12-30 보도자료, 고시 제2022-32호
    2025: 230_000_000,  # 기획재정부 2024-12-24 보도자료
    2026: 230_000_000,  # 기획재정부 2024-12-24 보도자료
}
DEFAULT_NOTICE_AMOUNT = 220_000_000


def notice_amount_for_year(year: int) -> int:
    return NOTICE_AMOUNT_BY_YEAR.get(year, DEFAULT_NOTICE_AMOUNT)
