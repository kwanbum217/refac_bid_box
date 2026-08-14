# Cerebras Gemma-4 31B 워커 연동 세팅 및 점검 보고

> **작성일**: 2026-08-14
> **작성자**: Antigravity
> **수신자**: Claude (코디네이터) 및 전체 세션 에이전트
> **관련 문서**: [`docs/ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md), [`opencode.json`](../../opencode.json)

---

## 1. 개요

Cerebras Cloud Inference API를 활용하여 초고속 추론(초당 약 1,800 토큰)이 가능한 **Gemma-4 31B** 모델을 워커 풀로 활용할 수 있도록 환경 및 CLI 구성을 완료하고 실측 점검을 수행했습니다.

---

## 2. 세팅 완료 내역

### 2.1 환경 변수 등록
- `.env`에 `CEREBRAS_API_KEY` 등록 완료 (API Key 발급 및 바인딩)

### 2.2 OpenCode 프로바이더 및 모델 정의 (`opencode.json`)
OpenCode가 OpenAI 호환 규격으로 Cerebras 엔드포인트를 호출할 수 있도록 설정했습니다.

```json
"provider": {
  "cerebras": {
    "npm": "@ai-sdk/openai-compatible",
    "name": "Cerebras",
    "baseURL": "https://api.cerebras.ai/v1",
    "apiKey": "{env:CEREBRAS_API_KEY}",
    "models": {
      "gemma-4-31b": {
        "name": "Gemma 4 31B",
        "limit": {
          "context": 65536,
          "output": 8192
        }
      },
      "gpt-oss-120b": {
        "name": "GPT OSS 120B",
        "limit": {
          "context": 65536,
          "output": 8192
        }
      },
      "zai-glm-4.7": {
        "name": "ZAI GLM 4.7",
        "limit": {
          "context": 65536,
          "output": 8192
        }
      }
    }
  }
}
```

### 2.3 CLI 모델 인식 검증
- `opencode models cerebras` 실행 결과:
  - `cerebras/gemma-4-31b`
  - `cerebras/gpt-oss-120b`
  - `cerebras/zai-glm-4.7`
  정상 인식 확인.

---

## 3. 실측 점검 결과 및 차단 사유 (Gate)

### 3.1 모델 목록 엔드포인트 조회
- 엔드포인트: `GET https://api.cerebras.ai/v1/models`
- 결과: **200 OK** (API 키 유효성 확인, `gemma-4-31b` 실존 확인)

### 3.2 추론 호출 실측
- 요청: `POST https://api.cerebras.ai/v1/chat/completions` (`model: gemma-4-31b`)
- 응답:
  ```json
  {
    "message": "Payment required to access this resource. Visit your billing tab.",
    "type": "payment_required_error",
    "param": "quota",
    "code": "payment_required"
  }
  ```

### 3.3 원인 및 활성화 요건
- **원인**: Cerebras 정책상 초기 가입 시 결제 수단(신용카드) 등록을 Skip한 경우, $5 무료 크레딧 쿼터가 즉시 부여되지 않아 크레딧 잔액 0으로 차단됨.
- **해결 방안**: 사용자가 Cerebras Cloud 콘솔(Billing 탭)에서 결제 수단을 등록하면 $5 무료 크레딧이 계정에 활성화되어 정상 호출 가능해짐.

---

## 4. 코디네이터를 위한 워커 기동 가이드

크레딧 활성화 완료 후, 코디네이터(Claude)는 아래 절차로 워커를 투입할 수 있습니다.

### 4.1 Orca 워커 기동 절차
```bash
# 1. 격리 워크트리 생성
orca worktree create --name <워커명> \
  --repo path:/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box \
  --base-branch main --setup skip --json

# 2. .env 복사 (CEREBRAS_API_KEY 포함)
cp /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box/.env <워크트리경로>/.env

# 3. OpenCode 기반 Gemma-4 워커 터미널 생성
orca terminal create --worktree path:<워크트리경로> \
  --title "<섹션명>" --command "opencode -m cerebras/gemma-4-31b" --json

# 4. Task 주입
orca orchestration dispatch --task <task_id> --to <handle> --inject --json
```

### 4.2 모델 적합도 권장 사항
- **적합 작업**: 대량 프롬프트 생성/변환, 템플릿 코드 작성, 절차적 문서화, 보조 리팩토링 (초당 1,800 토큰 초고속 처리 이점)
- **부적합 작업**: 코디네이터 승격 판단, 복잡한 회귀 검정, main 직접 병합 (상위 모델 또는 코디네이터가 수행)
