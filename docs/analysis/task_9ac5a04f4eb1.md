> 작업 ID: task_9ac5a04f4eb1
> 작성일: 2026-08-28
> 상태: candidate

# CPU utilization provenance 방식 식별자

## 변경 내용

벤치마크 호스트 부하 표본에 `cpu_utilization_method`와 `cpu_utilization_probe_ms`를 추가했습니다. Linux는 `proc_stat_delta`, macOS는 `ps_process_sum`, 미지원 플랫폼은 `unsupported`를 기록하며, 실패한 측정에도 방식 식별자와 실패 사유를 보존합니다.

## 검증 범위

Linux와 macOS 경로는 주입 가능한 파일 및 명령 실행기로 테스트합니다. 실제 벤치마크와 Docker 기동은 수행하지 않습니다.
