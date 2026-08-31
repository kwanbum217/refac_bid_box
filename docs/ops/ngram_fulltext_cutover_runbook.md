# 운영 ngram FULLTEXT 인덱스 컷오버 런북

> **작성일**: 2026-09-01
> **관련 Task**: `task_d33cbcec73c1` (Wave J)
> **전제 조건**: 사용자 명시적 승인 없이 이 런북의 어떤 단계도 실행하지 않습니다.
> **참조 근거**: [`handoff_wave_f_20260830.md`](handoff_wave_f_20260830.md),
> [`handoff_20260831_wave_gh.md`](handoff_20260831_wave_gh.md)

---

## 0. 선행 조건 체크리스트 (실행 전 전부 통과 확인)

| 조건 | 검증 방법 | 현재 상태 |
| --- | --- | :---: |
| ngram 선행필터 코드가 `main` 에 있고 기본값 OFF | `NGRAM_PREFILTER_ENABLED` 기본값과 `src/rag/structured_data.py` | Wave H2 로 충족. I-F 와 무관 |
| I-H 경계값 7 클래스 픽스처 병합 | `git log --oneline main` 으로 `kwanbum217/orca-i-h` 확인 | 미병합 |
| 경계값 7 클래스 실측 완료 | 5단계 하네스 실행 | 미실측 |
| 수집 서비스 정지 또는 점검 시간대 확인 | 운영 캘린더 | 확인 필요 |
| 디스크 여유 공간 >= 60GB | `df -h` | 확인 필요 |
| Docker 컨테이너 (`db`) 가동 중 | `docker compose ps db` | 확인 필요 |

**모든 행이 통과 전에는 다음으로 넘어가지 않습니다.**

---

## 1. 인덱스 존재 확인

운영 DB에 FULLTEXT 인덱스가 이미 있는지 확인합니다.

```sql
SELECT INDEX_NAME, COLUMN_NAME, INDEX_TYPE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('bid_announcements', 'bid_results')
  AND INDEX_TYPE = 'FULLTEXT'
ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
```

기대 결과: 0행 (현재 두 테이블 모두 FULLTEXT 인덱스 없음).

행이 반환되면 기존 인덱스 생성 경위를 확인하고 이 런북을 중단합니다.

---

## 2. 경계값 7 클래스 확인 (인덱스 생성 전 현황 파악)

`tests/fixtures/ngram_edge_keywords.json` 의 7건이 `is_safe_for_ngram: true` 인데
실 MySQL + FULLTEXT 인덱스에서 검증된 적이 없습니다. 현행 코드는 이를 보수적으로 제외합니다.

대상 클래스:

| ID | 유형 | 의심 근거 |
| --- | --- | --- |
| `edge_04` | 괄호 | MySQL ngram 은 괄호를 구분자로 취급할 수 있음 |
| `edge_05` | 하이픈 | boolean mode 에서 부정 연산자 충돌 |
| `edge_07` | 영문숫자 | 토큰화 경계 불확실 |
| `edge_09` | `%` | LIKE 와 달리 `%` 는 MATCH 에서 리터럴. 픽스처 값이 틀렸을 가능성 높음 |
| `edge_10` | `_` | 밑줄 처리 불일치 |
| `edge_11` | 따옴표 | 구문 검색 구분자 충돌 |
| `edge_12` | boolean 연산자 | `+`, `-`, `*` 연산자 혼입 |

실측은 3단계에서 인덱스를 만든 뒤 5단계에서 수행합니다.

---

## 3. 인덱스 생성 (사용자 승인 후)

### 3.1 주의 사항

- **Alembic 자동 마이그레이션 사용 금지.** `alembic revision --autogenerate` 는
  FULLTEXT 인덱스를 추적하지 않으며, DROP TABLE 을 시도할 수 있습니다.
  수동 DDL 만 허용합니다.
- **첫 FULLTEXT 추가는 테이블을 전체 재구축합니다.** MySQL 8 은 첫 FULLTEXT 인덱스 추가 시
  숨은 `FTS_DOC_ID` 컬럼을 삽입하며 테이블 전체가 재구축됩니다.
  재구축 중 해당 테이블 쓰기가 차단됩니다.
- **수집이 멈춘 시간대를 선택하십시오.** 쓰기 차단 중 수집 프로세스의 INSERT 가 타임아웃됩니다.

| 테이블 | 데이터 크기 | 예상 재구축 시간 (probe 기준) | 영향 |
| --- | ---: | ---: | --- |
| `bid_results` | 1,060MB | 약 126초 | 재구축 부담 작음 |
| `bid_announcements` | 27,272MB | 약 609초 (~10분) | 쓰기 차단 동안 수집 중단 필요 |

F3 실측은 격리 probe 스키마 기준이므로 운영 환경에서는 더 길어질 수 있습니다.
디스크 여유는 인덱스 크기(데이터의 66~87%)를 감안해 60GB 이상이어야 합니다.

### 3.2 실행 명령

```sql
-- bid_results 먼저 (크기가 작아 위험 낮음)
ALTER TABLE bid_results
  ADD FULLTEXT INDEX ft_bidwinnr_nm (bidwinnr_nm)
  WITH PARSER ngram;

-- bid_announcements (수집 정지 후)
ALTER TABLE bid_announcements
  ADD FULLTEXT INDEX ft_dminstt_nm (dminstt_nm)
  WITH PARSER ngram;
```

비밀번호를 명령줄에 노출하지 마십시오. MySQL 옵션 파일(`~/.my.cnf`)을 사용하거나
표준 입력으로 전달하십시오.

### 3.3 생성 후 존재 확인

```sql
SELECT INDEX_NAME, COLUMN_NAME, INDEX_TYPE
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN ('bid_announcements', 'bid_results')
  AND INDEX_TYPE = 'FULLTEXT'
ORDER BY TABLE_NAME, INDEX_NAME;
```

기대 결과: `ft_bidwinnr_nm`(`bid_results`), `ft_dminstt_nm`(`bid_announcements`) 두 행.

---

## 4. Canary 질의

인덱스 생성 직후 MATCH AGAINST 가 정상 동작하는지 확인합니다.
MATCH 결과는 항상 LIKE 결과의 부분집합이어야 합니다.

```sql
-- bid_announcements: cnt_match <= cnt_like 여야 함
SELECT
  SUM(dminstt_nm LIKE '%거제시%')                                        AS cnt_like,
  SUM(MATCH(dminstt_nm) AGAINST('+거제시' IN BOOLEAN MODE) > 0)         AS cnt_match
FROM bid_announcements
WHERE dminstt_nm LIKE '%거제시%';

-- bid_results
SELECT
  SUM(bidwinnr_nm LIKE '%삼성%')                                         AS cnt_like,
  SUM(MATCH(bidwinnr_nm) AGAINST('+삼성' IN BOOLEAN MODE) > 0)          AS cnt_match
FROM bid_results
WHERE bidwinnr_nm LIKE '%삼성%';
```

cnt_match = 0 이거나 cnt_match > cnt_like 이면 인덱스 이상입니다.
LIKE 경로만 유지하고 원인을 조사한 뒤 플래그를 켜지 않습니다.

---

## 5. 경계값 7 클래스 실측 및 픽스처 정정

인덱스가 생성된 상태에서 Wave H G3 하네스를 실행합니다.

```bash
uv run pytest tests/integration/test_ngram_edge_keywords.py -v \
  -k "edge_04 or edge_05 or edge_07 or edge_09 or edge_10 or edge_11 or edge_12"
```

실측 결과에 따라 `tests/fixtures/ngram_edge_keywords.json` 을 정정합니다.

- `is_safe_for_ngram: true` 인데 누락 발생 -> `false` 로 정정
- `is_safe_for_ngram: false` 인데 누락 없음 -> `true` 로 변경 가능 (선택)

정정 후 전체 ngram 단위 테스트가 통과해야 합니다:

```bash
uv run pytest tests/unit/test_ngram_prefilter.py -v
```

**이 단계 통과 전에는 플래그를 켜지 않습니다.**

---

## 6. 기능 플래그 활성화

경계값 실측과 canary 질의가 전부 통과한 뒤에만 환경 변수를 켭니다.

`.env` 또는 `docker-compose.override.yml`:

```
NGRAM_PREFILTER_ENABLED=true
```

FastAPI 컨테이너 재기동:

```bash
docker compose restart api
```

재기동 후 대표 쿼리 몇 건으로 응답을 확인합니다.

---

## 7. Cold canonical 재측정

플래그를 켜고 컨테이너가 안정된 뒤 E4 와 동일 규약으로 측정합니다.

```bash
uv run python scripts/measure_coldsql_attribution.py \
  --fixture tests/fixtures/blind_fixture_v2.json \
  --flush-cache \
  --repeat 3 \
  --output data/benchmarks/coldsql_post_ngram_$(date +%Y%m%d).json
```

규약 준수 조건:
- fixture: `blind_fixture_v2` 32문항 전량
- `--flush-cache` 포함 (Redis cold 보장)
- 3회 반복
- `canonical=true` 로 저장

개선 기대값 (Wave F3 probe 스키마 기준, 운영값과 다를 수 있음):

| 집계 경로 | 현행 warm | ngram warm | 개선 배율 |
| --- | ---: | ---: | ---: |
| `dminstt_nm` GROUP BY + cat | 1,719.6ms | 90.6ms | 19.0배 |
| `bidwinnr_nm` GROUP BY + cat | 808.7ms | 283.8ms | 2.9배 |

결과를 `CURRENT_STATE.md` 에 갱신하십시오.

---

## 8. 금지 사항 (이 런북 전체에 적용)

- Alembic 자동 마이그레이션으로 FULLTEXT 인덱스를 생성하지 않습니다.
- 사용자 명시적 승인 없이 어떤 단계도 실행하지 않습니다.
- `bid_ntce_nm` 컬럼에 FULLTEXT 인덱스를 추가하지 않습니다
  (Wave F3 실측: 최대 2,500배 악화).
- 단건 `SELECT ID` 경로에 MATCH AGAINST 를 추가하지 않습니다
  (Wave F3 실측: 27배 악화).
- 경계값 실측 없이 `NGRAM_PREFILTER_ENABLED=true` 를 켜지 않습니다.

---

## 9. 롤백 절차

인덱스 생성 후 이상이 발견되면:

```sql
ALTER TABLE bid_results DROP INDEX ft_bidwinnr_nm;
ALTER TABLE bid_announcements DROP INDEX ft_dminstt_nm;
```

기능 플래그 롤백:

```bash
# .env 에서 NGRAM_PREFILTER_ENABLED=false 로 설정 후 재기동
docker compose restart api
```

인덱스 삭제는 생성보다 빠릅니다. `FTS_DOC_ID` 컬럼은 모든 FULLTEXT 인덱스가
삭제된 뒤에야 함께 제거됩니다.
