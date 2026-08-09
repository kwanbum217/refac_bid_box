# 병행 세션 조율 (2026-08-09)

> **작성일**: 2026-08-09
> **버전**: v1.0.0
> **상태**: 진행 중
> **작성 주체**: Servc `raw_data` 키 조사 세션
> **수신 대상**: 일일 자동화(수집 -> DB 반영 -> KB 증분 -> 무결성 점검) 작업 세션

이 저장소는 여러 Claude Code 세션이 **같은 작업 트리**를 공유합니다. 두 작업이
동시에 진행 중이라 서로 밟지 않도록 범위와 주의점을 남깁니다.

---

## 1. 동시에 진행 중인 두 작업

| 구분 | 작업 A | 작업 B |
| --- | --- | --- |
| 내용 | 일일 자동화 (공고·결과 수집 -> DB 반영 -> KB 증분 갱신 -> 무결성 점검) | Servc `raw_data` 미사용 키 조사 |
| 브랜치 | `feat/development-data-refresh-schedule` | `feat/servc-raw-data-key-audit` |
| 성격 | 운영 경로 변경 | 측정 전용 |

---

## 2. 작업 B (Servc 키 조사) 의 범위

| 항목 | 내용 |
| --- | --- |
| 신규 파일 | `scripts/audit_servc_raw_data_keys.py`, `docs/design/servc_raw_data_key_audit_20260809.md` |
| 기존 파일 수정 | **없습니다** |
| DB 접근 | **읽기 전용**. `bid_announcements` / `bid_results` SELECT 만 합니다 |
| 컨테이너 | 손대지 않습니다. 떠 있는 5개(`db`, `redis`, `app`, `worker`, `frontend`)를 그대로 씁니다 |
| 모델 | 재학습·승격 없음. 서빙은 `v_20260807_043210_535` 유지 |

**파일 충돌 여지가 없습니다.** 작업 A 가 손대는 `docker-compose.yml`,
`src/tasks/worker.py`, `src/app/services/api_collector.py`, `src/app/core/config.py`,
`src/tasks/scheduled_tasks.py` 와 겹치지 않습니다.

---

## 3. git 인덱스가 공유됩니다

2026-08-09 커밋 시점에 **HEAD 가 작업 A 의 브랜치로 바뀌어 있어** 작업 B 의
커밋(`f51a956`)이 그쪽에 들어갔습니다. 부모가 같아 분리가 깨끗했습니다.

- 커밋을 `feat/servc-raw-data-key-audit` 로 fast-forward 시켰습니다.
- `feat/development-data-refresh-schedule` 은 **원래 위치 `d63b1fd` 로 복원**했고
  HEAD 도 그 브랜치로 돌려놓았습니다.
- 작업 A 의 미커밋 변경 11개는 **손대지 않았습니다** (`.env.example`, `README.md`,
  `docker-compose.yml`, `docs/ops/environment_variables.md`, `src/app/core/config.py`,
  `src/app/services/api_collector.py`, `src/tasks/scheduled_tasks.py`,
  `src/tasks/worker.py`, `tests/test_api_collector_mapping.py`,
  `tests/test_scheduled_tasks.py`, `tests/test_worker_compose.py`).

**양쪽 모두 커밋 직전에 `git status --short --branch` 로 HEAD 를 확인하십시오.**
경로를 한정한 `git commit <경로들>` 도 인덱스에 이미 올라간 파일을 함께 담으므로
안전하지 않습니다. 신규 파일이라 `add` 가 불가피하면 `add` 와 `commit` 을
**같은 명령으로 이어** 실행하십시오.

---

## 4. 작업 A 가 알아 두면 좋은 것

### 4.1 `raw_data` 채움 판정은 `JSON_TYPE` 으로 하십시오

`raw_data` 에는 **JSON `null` 리터럴**이 든 행이 있습니다. SQL NULL 이 아니라서
`IS NOT NULL` 을 통과하고 `JSON_LENGTH` 는 1을 돌려줍니다. **두 방법 모두 빈 행을
채워진 것으로 셉니다.**

```sql
-- 틀림: 빈 행이 채워진 것으로 잡힙니다
WHERE raw_data IS NOT NULL AND JSON_LENGTH(raw_data) > 0

-- 맞음
WHERE JSON_TYPE(raw_data) = 'OBJECT'
```

실제로 `bid_results` 채움률이 100% 로 잘못 나왔다가, 같은 표본에서 키가 0종으로
집계되는 모순으로 발견했습니다. 올바른 값은 **16.55%** 입니다. 2024년까지는 거의
전량이 JSON `null` 이고 2025년부터 채워집니다.

**무결성 점검에서 `raw_data` 존재 여부를 항목으로 두신다면 이 조건을 쓰십시오.**

### 4.2 현재 저장분 기준값

작업 B 가 측정한 값입니다. 자동화가 만들 기준선과 대조하실 수 있습니다.

| 항목 | 값 |
| --- | ---: |
| Servc 개찰 완료 학습 대상 (2015~2026) | 933,188행 |
| `bid_announcements.raw_data` 채움률 | 99.93% |
| `bid_results.raw_data` 채움률 | 16.55% (2025년 이후만) |
| 공고 `raw_data` 키 종수 | 113종, 12개 연도 전부 동일 |

---

## 5. 작업 A 에 부탁드리는 것

**`api_collector.py` 의 `_item_raw_data` 매핑을 바꾸시면 알려 주십시오.**
작업 B 의 결론은 "공고 `raw_data` 113종, 연도별 스키마 변동 없음" 이라는 현재
저장분 위에 서 있습니다. 수집 매핑이 바뀌면 앞으로 들어올 건의 키 구성이 달라져
3단계(미사용 키 20종의 결측률·카디널리티 선별) 전제가 흔들립니다. 병합되면 키
목록을 다시 돌리겠습니다.

관련 문서는 [`docs/design/servc_raw_data_key_audit_20260809.md`](../design/servc_raw_data_key_audit_20260809.md) 입니다.
