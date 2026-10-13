"""과거(2015~2022 시행) 공고 전용 조달청 일반용역 적격심사 이력 레지스트리.

이 파일은 생성물입니다. 직접 고치지 말고 명세 YAML 을 고친 뒤
`uv run python scripts/build_pps_history_rules.py` 로 다시 생성하십시오.

정본 명세: `data/reference/pps_servc_qual_history_2015_2022.yaml`
근거 문서: `docs/analysis/pps_servc_qual_history_20261013.md`

서빙 레지스트리 `src/app/services/evaluation_rules.py` 는 2023-05-01 이후 판만 담습니다.
이 모듈은 그 이전 공고를 되짚을 때만 쓰며, 서빙 경로는 이 모듈을 import 하지 않습니다.
따라서 현행 공고의 규칙 매칭 결과는 이 모듈로 바뀌지 않습니다.

값의 성격
--------
- B(max_price_score)·k(multiplier)·base_ratio·flat_ratio·pass_score 는 YAML 에 실린 원문
  인쇄값 또는 본문 제10조 통과점수입니다. 추정하거나 파생하지 않습니다.
- lwlt_rate(낙찰하한율)는 원문에 인쇄되지 않아 `기준비율 - (100 - 통과점수) / k` 로 역산한
  YAML 파생값이며, 소수 둘째 자리까지 버린 뒤 0.005 를 뺀 `.995` 표기 관행을 따릅니다.
- 시행 구간이 뒤집힌 제2016-48호는 routable=False 로 두어 조회에서 뺍니다.
- 원문 별표의 계산식 문자열은 정본 YAML 에 그대로 있으며, 각 별표의 `source`(flSeq)로 찾습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

NOTICE_AMOUNT_BOUNDARY: Final[Literal["고시금액"]] = "고시금액"

# 추정가격 구간 경계. Decimal 이면 금액, NOTICE_AMOUNT_BOUNDARY 면 그 해 고시금액,
# None 이면 하한 또는 상한 없음입니다.
Boundary = Decimal | Literal["고시금액"] | None


@dataclass(frozen=True)
class HistoryScoreTier:
    """평점산식 구간 하나. 배점한도 구간과 경계가 다를 수 있어 별도 축으로 둡니다."""

    formula_lower: Boundary
    formula_upper: Boundary
    k: Decimal
    base_ratio: Decimal
    flat_ratio: Decimal | None
    pass_score: Decimal
    lwlt_rate: Decimal


@dataclass(frozen=True)
class HistoryPriceBand:
    """별표의 배점한도 구간 하나. 그 안에 평점산식 구간이 여럿일 수 있습니다."""

    price_lower: Boundary
    price_upper: Boundary
    max_price_score: Decimal | None
    tiers: tuple[HistoryScoreTier, ...]


@dataclass(frozen=True)
class HistoryAttachment:
    """별표 하나. service_type 은 서빙 레지스트리와 같은 코드입니다."""

    attachment: str
    title: str
    service_type: str
    source_service_type: str
    fl_seq: str
    rule_id: str
    source: str
    bands: tuple[HistoryPriceBand, ...]


@dataclass(frozen=True)
class HistoryRevision:
    """고시 판 하나. effective_from~effective_to 가 그 판이 시행된 구간입니다."""

    notice_key: str
    notice_no: str
    effective_from: date
    effective_to: date
    routable: bool
    exclusion_reason: str | None
    source: str
    attachments: tuple[HistoryAttachment, ...]


HISTORY_NOTICE_AMOUNT_BY_YEAR: Final[dict[int, int]] = {
    2023: 220_000_000,  # 기획재정부 고시 제2022-32호(2022-12-30). src/ml/notice_amount.py:4 와 같은 값
}

HISTORY_REVISIONS: Final[tuple[HistoryRevision, ...]] = (
    HistoryRevision(
        notice_key="2015-41",
        notice_no="조달청공고 제2015-41호",
        effective_from=date(2015, 5, 1),
        effective_to=date(2016, 4, 30),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2015-41호 (2015-04-22 발령, 폐지제정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사항목및배점한도",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="19967657",
                rule_id="SERVC_QUAL_HIST_2015_41_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 19967657)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("200000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("200000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사항목및배점한도",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="19967622",
                rule_id="SERVC_QUAL_HIST_2015_41_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 19967622)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사항목및배점한도",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="19967661",
                rule_id="SERVC_QUAL_HIST_2015_41_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 19967661)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사항목및배점한도",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="19967722",
                rule_id="SERVC_QUAL_HIST_2015_41_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 19967722)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사항목및배점한도",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="19967759",
                rule_id="SERVC_QUAL_HIST_2015_41_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 19967759)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2016-48",
        notice_no="조달청공고 제2016-48호",
        effective_from=date(2016, 5, 1),
        effective_to=date(2016, 4, 30),
        routable=False,
        exclusion_reason="명세상 시행 구간이 뒤집혀 있습니다(종료일 2016-04-30 < 시행일 2016-05-01).",
        source="조달청공고 제2016-48호 (2016-04-08 발령, 폐지제정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="24323670",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323670)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("200000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("200000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="24323678",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323678)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="24323693",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323693)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="24323709",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323709)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="24323734",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323734)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="24323749",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323749)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="육상운송용역중소기업자간경쟁제품대상적격심사",
                service_type="LAND_TRANSPORT_SME",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 대상)",
                fl_seq="24323752",
                rule_id="SERVC_QUAL_HIST_2016_48_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24323752)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2016-51",
        notice_no="조달청공고 제2016-51호",
        effective_from=date(2016, 5, 1),
        effective_to=date(2017, 4, 30),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2016-51호 (2016-04-26 발령, 폐지제정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="24468537",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468537)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("200000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("200000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="24468551",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468551)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="24468572",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468572)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="24468575",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468575)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="24468585",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468585)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="24468682",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468682)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="육상운송용역중소기업자간경쟁제품대상적격심사",
                service_type="LAND_TRANSPORT_SME",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 대상)",
                fl_seq="24468685",
                rule_id="SERVC_QUAL_HIST_2016_51_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 24468685)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2017-35",
        notice_no="조달청공고 제2017-35호",
        effective_from=date(2017, 5, 1),
        effective_to=date(2017, 9, 30),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2017-35호 (2017-04-03 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="29459892",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29459892)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("200000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("200000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="29459897",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29459897)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="29459902",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29459902)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="29459926",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29459926)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="29459958",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29459958)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="29459986",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29459986)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="육상운송용역중소기업자간경쟁제품대상적격심사",
                service_type="LAND_TRANSPORT_SME",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 대상)",
                fl_seq="29460047",
                rule_id="SERVC_QUAL_HIST_2017_35_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 29460047)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2017-82",
        notice_no="조달청공고 제2017-82호",
        effective_from=date(2017, 10, 1),
        effective_to=date(2017, 11, 30),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2017-82호 (2017-08-10 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사제5조제1항제1호관련",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="30900514",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900514)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("200000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("200000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사제5조제1항제2호관련",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="30900517",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900517)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사제5조제1항제3호관련",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="30900521",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900521)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사제5조제1항제3호관련",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="30900531",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900531)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사제5조제1항제4호관련",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="30900537",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900537)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사제5조제1항제5호관련",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="30900544",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900544)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="육상운송용역중소기업자간경쟁제품대상적격심사제5조제1항제5호관련",
                service_type="LAND_TRANSPORT_SME",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 대상)",
                fl_seq="30900548",
                rule_id="SERVC_QUAL_HIST_2017_82_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 30900548)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2017-95",
        notice_no="조달청공고 제2017-95호",
        effective_from=date(2017, 12, 1),
        effective_to=date(2018, 3, 31),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2017-95호 (2017-09-29 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="31491659",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491659)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("210000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("210000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="31491662",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491662)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="31491670",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491670)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="31491676",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491676)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="31491681",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491681)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="31491687",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491687)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="육상운송용역중소기업자간경쟁제품대상적격심사",
                service_type="LAND_TRANSPORT_SME",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 대상)",
                fl_seq="31491693",
                rule_id="SERVC_QUAL_HIST_2017_95_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 31491693)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2018-36",
        notice_no="조달청공고 제2018-36호",
        effective_from=date(2018, 4, 1),
        effective_to=date(2019, 3, 31),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2018-36호 (2018-03-29 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="33901427",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901427)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("210000000"),
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("210000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="33901435",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901435)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="33901439",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901439)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="33901442",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901442)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="33901446",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901446)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역중소기업자간경쟁제품비대상적격심사",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="33901450",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901450)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=Decimal("210000000"),
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=Decimal("210000000"),
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="육상운송용역중소기업자간경쟁제품대상적격심사",
                service_type="LAND_TRANSPORT_SME",
                source_service_type="육상운송용역(중소기업자간 경쟁제품 대상)",
                fl_seq="33901453",
                rule_id="SERVC_QUAL_HIST_2018_36_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 33901453)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2019-31",
        notice_no="조달청공고 제2019-31호",
        effective_from=date(2019, 4, 1),
        effective_to=date(2020, 3, 31),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2019-31호 (2019-02-21 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="40769526",
                rule_id="SERVC_QUAL_HIST_2019_31_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 40769526)",
                bands=(
                    HistoryPriceBand(
                        price_lower=NOTICE_AMOUNT_BOUNDARY,
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=NOTICE_AMOUNT_BOUNDARY,
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="40769532",
                rule_id="SERVC_QUAL_HIST_2019_31_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 40769532)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="정보통신용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="40769542",
                rule_id="SERVC_QUAL_HIST_2019_31_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 40769542)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="정보통신용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="정보통신용역(중소기업자간 경쟁제품 대상)",
                fl_seq="40769552",
                rule_id="SERVC_QUAL_HIST_2019_31_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 40769552)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="40769562",
                rule_id="SERVC_QUAL_HIST_2019_31_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 40769562)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="육상운송용역적격심사",
                service_type="LAND_TRANSPORT",
                source_service_type="육상운송용역",
                fl_seq="40769570",
                rule_id="SERVC_QUAL_HIST_2019_31_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 40769570)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2020-10",
        notice_no="조달청공고 제2020-10호",
        effective_from=date(2020, 4, 1),
        effective_to=date(2020, 7, 14),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2020-10호 (2020-03-11 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="59849491",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59849491)",
                bands=(
                    HistoryPriceBand(
                        price_lower=NOTICE_AMOUNT_BOUNDARY,
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=NOTICE_AMOUNT_BOUNDARY,
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="59849867",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59849867)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="소프트웨어용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="59850307",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59850307)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="소프트웨어용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 대상)",
                fl_seq="59850875",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59850875)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="59851567",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59851567)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="여객육상운송용역적격심사",
                service_type="PASSENGER_TRANSPORT",
                source_service_type="여객 육상운송용역",
                fl_seq="59851599",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59851599)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="화물육상운송용역적격심사",
                service_type="FREIGHT",
                source_service_type="화물 육상운송용역",
                fl_seq="59851795",
                rule_id="SERVC_QUAL_HIST_2020_10_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 59851795)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2020-30",
        notice_no="조달청공고 제2020-30호",
        effective_from=date(2020, 7, 15),
        effective_to=date(2021, 1, 6),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2020-30호 (2020-07-09 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="69741353",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69741353)",
                bands=(
                    HistoryPriceBand(
                        price_lower=NOTICE_AMOUNT_BOUNDARY,
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=NOTICE_AMOUNT_BOUNDARY,
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="69741365",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69741365)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="소프트웨어용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="69741917",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69741917)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="소프트웨어용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 대상)",
                fl_seq="69745277",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69745277)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="69747325",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69747325)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="여객육상운송용역적격심사",
                service_type="PASSENGER_TRANSPORT",
                source_service_type="여객 육상운송용역",
                fl_seq="69747481",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69747481)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="화물육상운송용역적격심사",
                service_type="FREIGHT",
                source_service_type="화물 육상운송용역",
                fl_seq="69747561",
                rule_id="SERVC_QUAL_HIST_2020_30_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 69747561)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2021-2",
        notice_no="조달청공고 제2021-2호",
        effective_from=date(2021, 1, 7),
        effective_to=date(2022, 2, 10),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2021-2호 (2021-01-05 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="96694581",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694581)",
                bands=(
                    HistoryPriceBand(
                        price_lower=NOTICE_AMOUNT_BOUNDARY,
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=NOTICE_AMOUNT_BOUNDARY,
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="96694587",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694587)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="소프트웨어용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="96694597",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694597)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="소프트웨어용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 대상)",
                fl_seq="96694603",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694603)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="96694609",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694609)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="여객육상운송용역적격심사",
                service_type="PASSENGER_TRANSPORT",
                source_service_type="여객 육상운송용역",
                fl_seq="96694617",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694617)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="화물육상운송용역적격심사",
                service_type="FREIGHT",
                source_service_type="화물 육상운송용역",
                fl_seq="96694625",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694625)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 6",
                title="보험용역적격심사",
                service_type="INSURANCE",
                source_service_type="보험용역",
                fl_seq="96694631",
                rule_id="SERVC_QUAL_HIST_2021_2_ATTACH_06",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 96694631)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("0.375"),
                                base_ratio=Decimal("88"),
                                flat_ratio=None,
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("47.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("0.375"),
                                base_ratio=Decimal("88"),
                                flat_ratio=None,
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("47.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
    HistoryRevision(
        notice_key="2022-42",
        notice_no="조달청공고 제2022-42호",
        effective_from=date(2022, 2, 11),
        effective_to=date(2023, 4, 30),
        routable=True,
        exclusion_reason=None,
        source="조달청공고 제2022-42호 (2022-02-10 발령, 일부개정)",
        attachments=(
            HistoryAttachment(
                attachment="별표 1",
                title="학술연구용역적격심사",
                service_type="ACADEMIC",
                source_service_type="학술연구용역",
                fl_seq="112916177",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_01",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916177)",
                bands=(
                    HistoryPriceBand(
                        price_lower=NOTICE_AMOUNT_BOUNDARY,
                        price_upper=None,
                        max_price_score=Decimal("40"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=NOTICE_AMOUNT_BOUNDARY,
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 2",
                title="시설분야용역적격심사",
                service_type="FACILITY",
                source_service_type="시설분야용역",
                fl_seq="112916183",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_02",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916183)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("5"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3",
                title="소프트웨어용역중소기업자간경쟁제품비대상적격심사",
                service_type="SW_NON_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 비대상)",
                fl_seq="112916193",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_03",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916193)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 3의2",
                title="소프트웨어용역중소기업자간경쟁제품대상적격심사",
                service_type="SW_SME",
                source_service_type="소프트웨어용역(중소기업자간 경쟁제품 대상)",
                fl_seq="112916199",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_03_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916199)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 4",
                title="폐기물처리용역적격심사",
                service_type="WASTE",
                source_service_type="폐기물처리용역",
                fl_seq="112916205",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_04",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916205)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5",
                title="여객육상운송용역적격심사",
                service_type="PASSENGER_TRANSPORT",
                source_service_type="여객 육상운송용역",
                fl_seq="112916213",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_05",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916213)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("4"),
                                base_ratio=Decimal("91"),
                                flat_ratio=Decimal("94"),
                                pass_score=Decimal("88"),
                                lwlt_rate=Decimal("87.995"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 5의2",
                title="화물육상운송용역적격심사",
                service_type="FREIGHT",
                source_service_type="화물 육상운송용역",
                fl_seq="112916221",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_05_2",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916221)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=NOTICE_AMOUNT_BOUNDARY,
                                formula_upper=None,
                                k=Decimal("2"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("95.5"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("80.495"),
                            ),
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=NOTICE_AMOUNT_BOUNDARY,
                                k=Decimal("4"),
                                base_ratio=Decimal("88"),
                                flat_ratio=Decimal("91.75"),
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("84.245"),
                            ),
                        ),
                    ),
                ),
            ),
            HistoryAttachment(
                attachment="별표 6",
                title="보험용역적격심사",
                service_type="INSURANCE",
                source_service_type="보험용역",
                fl_seq="112916227",
                rule_id="SERVC_QUAL_HIST_2022_42_ATTACH_06",
                source="data/reference/pps_servc_qual_history_2015_2022.yaml (flSeq 112916227)",
                bands=(
                    HistoryPriceBand(
                        price_lower=Decimal("500000000"),
                        price_upper=None,
                        max_price_score=Decimal("60"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("0.375"),
                                base_ratio=Decimal("88"),
                                flat_ratio=None,
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("47.995"),
                            ),
                        ),
                    ),
                    HistoryPriceBand(
                        price_lower=None,
                        price_upper=Decimal("500000000"),
                        max_price_score=Decimal("70"),
                        tiers=(
                            HistoryScoreTier(
                                formula_lower=None,
                                formula_upper=None,
                                k=Decimal("0.375"),
                                base_ratio=Decimal("88"),
                                flat_ratio=None,
                                pass_score=Decimal("85"),
                                lwlt_rate=Decimal("47.995"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
)


@dataclass(frozen=True)
class HistoryBandResolution:
    """조회 결과. 개정판·별표·구간과 B·k·기준비율·통과점수·하한율, 출처를 담습니다."""

    rule_id: str
    revision_key: str
    revision_notice_no: str
    attachment: str
    service_type: str
    source_service_type: str
    max_price_score: Decimal | None
    multiplier: Decimal
    base_ratio: Decimal
    flat_ratio: Decimal | None
    pass_score: Decimal
    lwlt_rate: Decimal
    source: str


def history_notice_amount_for_year(year: int) -> int | None:
    """그 해 용역 고시금액. 근거가 있는 연도만 값을 돌려주고 나머지는 None 입니다."""
    return HISTORY_NOTICE_AMOUNT_BY_YEAR.get(year)


def _coerce_date(value: date | datetime | str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _coerce_amount(value: Decimal | str | float | int | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError, InvalidOperation):
        return None
    return amount if amount > 0 else None


def _resolve_boundary(
    value: Boundary, notice_amount: Decimal | None
) -> tuple[Decimal | None, str | None]:
    """경계 표기를 금액으로 풉니다. 둘째 값이 있으면 확정 실패입니다."""
    if value is None:
        return None, None
    if isinstance(value, Decimal):
        return value, None
    if notice_amount is None:
        return None, "구간 경계가 고시금액인데 해당 연도 고시금액 근거가 없습니다."
    return notice_amount, None


def _select_revision(day: date) -> HistoryRevision | None:
    for revision in HISTORY_REVISIONS:
        if revision.effective_from <= day <= revision.effective_to:
            return revision
    return None


def _match(
    price: Decimal,
    lower: Boundary,
    upper: Boundary,
    notice_amount: Decimal | None,
) -> tuple[bool, str | None]:
    """하한 이상, 상한 미만으로 구간을 판정합니다. 둘째 값이 있으면 확정 실패입니다."""
    low, reason = _resolve_boundary(lower, notice_amount)
    if reason:
        return False, reason
    high, reason = _resolve_boundary(upper, notice_amount)
    if reason:
        return False, reason
    if low is not None and price < low:
        return False, None
    if high is not None and price >= high:
        return False, None
    return True, None


def resolve_history_band(
    notice_date: date | datetime | str | None,
    service_type: str,
    estimated_price: Decimal | str | float | int | None,
    notice_amount_boundary: Decimal | str | float | int | None = None,
) -> tuple[HistoryBandResolution | None, str | None]:
    """공고일·용역 유형·추정가격으로 개정판·별표·구간을 확정합니다.

    확정하면 (결과, None), 못 하면 (None, 사유)를 돌려줍니다. 값을 추정하지 않습니다.
    하한은 이상, 상한은 미만이며 경계값은 상위 구간에 듭니다.
    """
    day = _coerce_date(notice_date)
    if day is None:
        return None, "공고일이 없어 시행 중인 개정판을 고르지 못했습니다."
    price = _coerce_amount(estimated_price)
    if price is None:
        return None, "추정가격이 없어 구간을 고르지 못했습니다."
    revision = _select_revision(day)
    if revision is None:
        return None, "공고일 시점에 시행 중인 이력 개정판이 없습니다."
    if not revision.routable:
        return None, revision.exclusion_reason or "조회에서 제외된 개정판입니다."
    attachments = [item for item in revision.attachments if item.service_type == service_type]
    if not attachments:
        return None, f"이력 레지스트리에 {service_type} 별표가 없습니다."
    if len(attachments) > 1:
        return None, f"이력 레지스트리에 {service_type} 별표가 둘 이상입니다."
    attachment = attachments[0]
    notice_amount = _coerce_amount(notice_amount_boundary)

    matched_bands: list[HistoryPriceBand] = []
    band_reasons: list[str] = []
    for band in attachment.bands:
        ok, reason = _match(price, band.price_lower, band.price_upper, notice_amount)
        if reason:
            band_reasons.append(reason)
        elif ok:
            matched_bands.append(band)
    if not matched_bands:
        if band_reasons:
            return None, band_reasons[0]
        return None, "추정가격이 어느 배점 구간에도 들지 않습니다."
    if len(matched_bands) > 1:
        return None, "추정가격이 배점 구간 둘 이상에 겹칩니다."
    band = matched_bands[0]

    matched_tiers: list[HistoryScoreTier] = []
    tier_reasons: list[str] = []
    for tier in band.tiers:
        ok, reason = _match(price, tier.formula_lower, tier.formula_upper, notice_amount)
        if reason:
            tier_reasons.append(reason)
        elif ok:
            matched_tiers.append(tier)
    if not matched_tiers:
        if tier_reasons:
            return None, tier_reasons[0]
        return None, "추정가격이 어느 평점산식 구간에도 들지 않습니다."
    if len(matched_tiers) > 1:
        return None, "추정가격이 평점산식 구간 둘 이상에 겹칩니다."
    tier = matched_tiers[0]

    return (
        HistoryBandResolution(
            rule_id=attachment.rule_id,
            revision_key=revision.notice_key,
            revision_notice_no=revision.notice_no,
            attachment=attachment.attachment,
            service_type=attachment.service_type,
            source_service_type=attachment.source_service_type,
            max_price_score=band.max_price_score,
            multiplier=tier.k,
            base_ratio=tier.base_ratio,
            flat_ratio=tier.flat_ratio,
            pass_score=tier.pass_score,
            lwlt_rate=tier.lwlt_rate,
            source=attachment.source,
        ),
        None,
    )


def _validate_revisions(revisions: tuple[HistoryRevision, ...]) -> None:
    """생성물의 시행 구간과 필수값을 검사합니다. 어긋나면 import 시점에 실패합니다."""
    for revision in revisions:
        if revision.routable and revision.effective_to < revision.effective_from:
            raise ValueError(f"{revision.notice_key} 판의 시행 구간이 뒤집혔습니다.")
        if not revision.attachments:
            raise ValueError(f"{revision.notice_key} 판에 별표가 없습니다.")
        for attachment in revision.attachments:
            if not attachment.bands:
                raise ValueError(f"{attachment.rule_id} 별표에 배점 구간이 없습니다.")
            for band in attachment.bands:
                if band.price_lower is None and band.price_upper is None:
                    raise ValueError(f"{attachment.rule_id} 배점 구간에 경계가 없습니다.")
                if not band.tiers:
                    raise ValueError(f"{attachment.rule_id} 배점 구간에 평점산식이 없습니다.")
                multiple = len(band.tiers) > 1
                for tier in band.tiers:
                    unbounded = tier.formula_lower is None and tier.formula_upper is None
                    if multiple and unbounded:
                        raise ValueError(f"{attachment.rule_id} 평점산식 구간에 경계가 없습니다.")
                    if tier.k <= 0:
                        raise ValueError(f"{attachment.rule_id} 평점계수는 0보다 커야 합니다.")


_validate_revisions(HISTORY_REVISIONS)
