# Harness CI/CD 연동 가이드

> **작성일**: 2026-07-31
> **버전**: v1.0.0
> **설계 기준**: `REFACTORING_DESIGN.md` 3.8절 (플랫폼 종속 바이너리 제거 및 Harness Cloud 표준화)

---

## 개요

기존 레거시 `bid_box`에 포함되어 있던 Windows 전용 바이너리 `hc.exe`(46MB) 및 `.ps1` 스케줄러는 macOS/Linux 환경 실행 불가능 및 Git 저장소 비대화 문제를 유발했습니다.

`refac_bid_box`에서는 **Git 내 바이너리를 전면 제거(G2 크로스플랫폼)**하고, 표준 선언형 Harness CI/CD 파이프라인([`.harness/pipeline.yaml`](../../.harness/pipeline.yaml))으로 전환하여 컨테이너 환경에서 유연하게 구동하도록 수립했습니다.

---

## Harness CI 파이프라인 구성

| 파일 | 역할 |
| :--- | :--- |
| [`.harness/pipeline.yaml`](../../.harness/pipeline.yaml) | Harness Cloud 선언형 CI/CD 파이프라인 명세 |
| `docker-compose.yml` | 로컬 및 Harness Delegate 전용 스택 오케스트레이션 |

---

## 실행 절차

### 1. Harness Cloud 연동 시
- `.harness/pipeline.yaml` 파이프라인을 Harness Cloud 리포지토리 웹후크(Webhook)로 지정합니다.
- 코드가 push될 때마다 `quality_check`(규칙 검증 + ruff + pytest) 및 Docker 빌드가 자동 수행됩니다.

### 2. 로컬 실행 및 시뮬레이션
- Harness Delegate 없이 로컬에서 완전 동일하게 테스트하려면 아래 타깃을 구동합니다:
```bash
make check-all
```
