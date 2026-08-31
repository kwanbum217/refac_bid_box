# MySQL 8 ngram FULLTEXT CI 격리 회귀 테스트 환경 구축 분석 보고서

> **작성일**: 2026-08-31
> **Task ID**: `task_fe40e063a6d9`
> **Run ID**: `run_428567a2da1f`
> **목적**: CI 상에서 MySQL 8 MATCH AGAINST 및 ngram parser 동작을 실제 검증하는 격리 서비스 및 초기화 픽스처 구축

---

## 1. 개요 및 배경

기존 CI 파이프라인에서는 `mysql_integration` 마커가 붙은 MySQL 전용 테스트(`tests/test_ngram_prefilter_equivalence.py`)가 실제 MySQL 인스턴스 부재로 인해 skip 처리되었습니다. 이로 인해 MySQL 8의 MATCH AGAINST 문법 및 ngram parser(`ngram_token_size=2`)의 동등성 및 경계값 동작이 지속적 통합 환경에서 실측 검증되지 못하는 공백이 존재했습니다.

운영 환경(procurement DB)의 FULLTEXT 인덱스는 사용자 보류 상태이므로, 운영 migration이나 `docker-compose.yml`에는 일체의 DDL을 추가하지 않고, GitHub Actions CI 전용의 일회성 격리 MySQL 8 서비스 컨테이너를 통해 안전하게 통합 회귀 테스트를 실행하도록 구성했습니다.

---

## 2. 주요 구현 내용

### 2.1 CI 전용 MySQL 8 격리 서비스 Job 추가 (`.github/workflows/ci.yml`)

- **Job 명칭**: `mysql-ngram-integration`
- **서비스 컨테이너**: `mysql:8.0` (포트 3306 바인딩, healthcheck 완비)
- **전용 스키마**: `test_procurement_ngram` (운영 `procurement` 스키마와 완전 분리)
- **초기화 단계**: `tests/fixtures/ngram_mysql_init.sql`을 실행하여 최소 테이블 생성 및 ngram FULLTEXT 인덱스, 픽스처 데이터 적재
- **검증 및 엄격성 보장**:
  - `uv run pytest tests/test_ngram_prefilter_equivalence.py -m mysql_integration -v` 실행
  - 테스트 결과에 `SKIPPED`가 포함되거나 통과 건수가 0건인 경우 CI가 즉시 실패하도록 사후 카운트 검증 단정 추가

### 2.2 격리 테스트 초기화 SQL 픽스처 (`tests/fixtures/ngram_mysql_init.sql`)

- **테이블 스키마**:
  - `bid_announcements`: `id`, `bid_ntce_no`, `bid_ntce_nm`, `dminstt_nm`, `category`, `FULLTEXT KEY ft_dminstt_nm (dminstt_nm) WITH PARSER ngram`
  - `bid_results`: `id`, `bid_ntce_no`, `dminstt_nm`, `bidwinnr_nm`, `category`, `FULLTEXT KEY ft_dminstt_nm (dminstt_nm) WITH PARSER ngram`, `FULLTEXT KEY ft_bidwinnr_nm (bidwinnr_nm) WITH PARSER ngram`
- **데이터셋 구성**:
  - **F3 기준선 10개 키워드**: `서울`, `거제`, `공사`, `거제시`, `교육청`, `한국전`, `한국토지주택공사`, `한국도로공사`, `부산광역시`, `경찰청`에 대해 `Servc` 및 `Cnstwk` 카테고리별 레코드 완비
  - **14개 경계값 클래스**: 1글자 한글(`시`, `청`), 정확히 2글자(`구청`), 공백 포함(`서울특별시 강남구`), 괄호(`한국도로공사(본사)`), 하이픈(`서울-경기`), 슬래시(`기획/관리`), 영숫자 혼합(`K-water2026`), 유니코드(`한국`), 와일드카드(`100%`, `공사_1차`), 따옴표(`공사's`), 불리언 연산자(`+공사*`), 매우 긴 기관명(`한국농어촌공사전남지역본부영광지사`), 중앙 부분문자열(`토지주택`)에 대한 검증 레코드 포함

---

## 3. 운영 안전 및 불변 조건 준수

| 불변 조건 | 준수 현황 | 비고 |
| --- | :---: | --- |
| G1 데이터 무손실 | **100% 준수** | 운영 DB 및 원본 스키마/데이터 일체 미변경 |
| 운영 DDL 격리 | **100% 준수** | Alembic migration, `docker-compose.yml` 무변경 |
| 범위 엄격성 | **100% 준수** | `allowed_write_files` 3개 파일만 수정/생성 |
| Skip 불인정 | **100% 준수** | 0건 실행 또는 skip 발생 시 exit 1 실패 처리 |
| 이모지 금지 | **100% 준수** | 주석, 커밋, 문서 내 이모지 일체 미사용 |

---

## 4. 검증 결과

1. **Workflow 구문 검증**: `uv run actionlint` 통과 (오류 0건)
2. **에이전트 규칙 정합성**: `python3 scripts/validate_agent_rules.py --quiet` 통과 (16/16 PASS)
3. **단위 및 회귀 테스트**: `uv run pytest tests/ -q -m 'not data_assets'` 전체 통과
