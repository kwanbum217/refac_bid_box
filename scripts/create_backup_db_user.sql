-- scripts/create_backup_db_user.sql
-- 백업 덤프 전용 최소 권한 MySQL 사용자 생성 스크립트
--
-- [실행 방법]
-- 운영 MySQL 서버에 관리자(root) 권한으로 접속하여 실행합니다:
--   mysql -u root -p < scripts/create_backup_db_user.sql
--
-- [보안 주의사항]
-- 1. IDENTIFIED BY 의 비밀번호는 자리표시자입니다. 운영 환경에 맞는 안전한 난수로 변경하십시오.
-- 2. 대상 데이터베이스명(procurement)이 다른 경우 해당 데이터베이스명으로 변경하십시오.
-- 3. 이 계정은 오직 백업 덤프(mysqldump)에 필요한 최소 권한만 부여받으며,
--    INSERT/UPDATE/DELETE/DROP 등의 데이터 및 스키마 변경 권한은 일체 부여되지 않습니다.

-- 1. 백업 전용 사용자 계정 생성 (비밀번호 자리표시자)
CREATE USER IF NOT EXISTS 'bidbox_backup'@'%' IDENTIFIED BY 'CHANGE_ME_BACKUP_PASSWORD';

-- 2. 데이터베이스 객체 및 데이터 읽기/덤프 최소 권한 부여
--    - SELECT: 테이블 데이터 조회 및 덤프
--    - SHOW VIEW: 뷰 정의 조회
--    - TRIGGER: 트리거 정의 조회 및 덤프
--    - LOCK TABLES: --single-transaction 수행 시 메타데이터 락 획득
--    - EVENT: 이벤트 스케줄러 정의 조회
GRANT SELECT, SHOW VIEW, TRIGGER, LOCK TABLES, EVENT ON `procurement`.* TO 'bidbox_backup'@'%';

-- 3. MySQL 8 mysqldump 호환성을 위한 글로벌 PROCESS 권한 부여
--    - PROCESS: mysqldump 8.0 의 Information Schema 테이블스페이스(TABLESPACES) 조회용
GRANT PROCESS ON *.* TO 'bidbox_backup'@'%';

-- 4. 권한 적용
FLUSH PRIVILEGES;
