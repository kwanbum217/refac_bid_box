# CURRENT_STATE 과업 상태 원장

> 목적: 자유 서술이 누적되어 같은 과업의 상태가 서로 달라지는 회귀를 CI에서 조기에 탐지합니다.
> 정본: [`../context/current_state_facts.yaml`](../context/current_state_facts.yaml)

## 구조

`current_state_facts.yaml`의 `facts` 배열은 과업별 `id`, `status`, `decision_date`,
`document_anchor`, `related_documents`를 보관합니다. `status`는 `active`, `rejected`,
`closed`, `blocked` 중 하나이며, `document_anchor`는 사람이 읽는
[`CURRENT_STATE.md`](../context/CURRENT_STATE.md)의 현재 결론 문구를 고유하게 가리킵니다.

## 검사 범위와 한계

`validate_agent_rules.py`는 각 앵커의 앞뒤 문맥에서 상태 표지가 존재하는지 확인하고,
상태와 반대되는 표지가 함께 있으면 실패합니다. 따라서 `rejected` 과업을 "미착수"나
"착수 예정"으로 되돌려 쓰는 오류, `closed` 과업을 "미해결" 또는 "기각"으로 쓰는 오류를
잡습니다. 앵커가 사라지거나 중복 ID, 허용되지 않은 상태, 필수 필드 누락도 실패합니다.

이 검사는 자연어 의미 전체를 해석하지 않습니다. 앵커가 다른 과업과 겹치거나, 앵커에서
멀리 떨어진 문단의 모순, 숫자·날짜의 논리 오류, 조건부 상태의 세부 차이는 잡지 못합니다.
상태를 바꾸거나 결론 문구를 고칠 때는 앵커와 원장을 같은 커밋에서 함께 갱신해야 합니다.

## 운영 방법

새 과업은 원장에 고유 ID와 결론 앵커를 추가한 뒤 `python3 scripts/validate_agent_rules.py
--quiet`를 실행합니다. 변경 후에는 `uv run pytest tests/ -q -m 'not data_assets'`와 같은
검사를 실행하며, 기존 16건 검사는 유지되고 상태 원장 검사가 17번째 항목으로 추가됩니다.
