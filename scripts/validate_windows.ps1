param(
    [string]$ProjectName = "refac-bid-box-windows-validation",
    [switch]$KeepStack
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "필수 명령을 찾을 수 없습니다: $Name"
    }
}

Require-Command "uv"
Require-Command "make"
Require-Command "docker"

uv sync
make test
make -n dev
docker compose config --quiet

try {
    docker compose -p $ProjectName up --build -d
    docker compose -p $ProjectName ps
    docker compose -p $ProjectName exec -T app python -m alembic upgrade head
    docker compose -p $ProjectName exec -T app python scripts/check_schema_drift.py

    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 30
    if ($health.status -ne "ok") {
        throw "FastAPI 헬스체크가 정상 상태를 반환하지 않았습니다."
    }
}
finally {
    if (-not $KeepStack) {
        docker compose -p $ProjectName down
    }
}
