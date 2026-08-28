> 작성일: 2026-08-28
> 적용 범위: 벤치마크 provenance의 호스트 CPU utilization 측정

# 벤치마크 측정 프로토콜

## CPU utilization

CPU utilization 값은 `cpu_utilization_method`와 `cpu_utilization_probe_ms`를 함께 기록합니다. `cpu_utilization_probe_ms`는 해당 utilization 관측에 소요된 실측 시간(ms)이며, 관측 부하를 해석할 때 사용합니다.

| 플랫폼 | 식별자 | 측정 원천 | 값의 의미 |
| --- | --- | --- | --- |
| Linux | `proc_stat_delta` | 두 시점의 `/proc/stat` CPU tick 차분 | 전체 커널 CPU 시간 중 busy tick 비율입니다. |
| macOS | `ps_process_sum` | `ps -A -o %cpu` 프로세스별 스냅샷 합산 후 논리 CPU 수로 정규화 | 프로세스별 `%CPU` 스냅샷 합산값입니다. |
| 미지원 플랫폼 | `unsupported` | 해당 없음 | utilization 값을 산출하지 않으며 실패 사유를 함께 기록합니다. |

Linux와 macOS 측정은 원천과 물리적 의미가 다르므로 절대값을 크로스플랫폼에서 직접 비교해서는 안 됩니다. 방식 식별자가 다른 리포트 사이에서는 비교하지 않고, 동일 플랫폼 및 동일 `cpu_utilization_method`를 가진 리포트끼리만 비교합니다.

측정 실패 시에도 `cpu_utilization_method`, `cpu_utilization_probe_ms`, `cpu_utilization_unavailable_reason`을 모두 남겨, 값 부재와 측정 방식 및 실패 원인을 구분합니다.
