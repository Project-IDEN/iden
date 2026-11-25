# Everything IDEN needs, in Docker on localhost, on the CPU. Needs only Docker.
# The Windows counterpart of local.sh; run it through local.cmd, which gets it past
# PowerShell's execution policy.
#
#   .\local.cmd          build and start everything (safe to re-run)
#   .\local.cmd down     stop it, keeping the data
#   .\local.cmd reset    stop it and delete the data
param([string]$Command = "up")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Docker Desktop ignores file ownership on Windows bind mounts, so the compose
# files' default uid 1000 is fine and IDEN_UID stays unset.
$env:IDEN_BIOMETRIC_ENABLED = "true"

# Windows PowerShell 5.1 does not stop on a native command's exit code.
function Invoke-Checked {
  & $args[0] @($args | Select-Object -Skip 1)
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Invoke-Compose {
  Invoke-Checked docker compose -f deploy/docker-compose.yml `
    -f deploy/docker-compose.engine-cpu.yml `
    -f deploy/docker-compose.kiosk.yml @args
}

function Test-Provider {
  try {
    Invoke-WebRequest http://localhost:8000/health -UseBasicParsing -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

switch ($Command) {
  "down" { Invoke-Compose down; exit }
  "reset" { Invoke-Compose down -v; exit }
  "up" { }
  default { Get-Content $PSCommandPath | Select-Object -Skip 4 -First 3; exit 2 }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Docker is not running. Start Docker Desktop and try again."
  exit 1
}

Write-Host "==> Building images (the first run takes a while)"
Invoke-Compose build

New-Item -ItemType Directory -Force provider/keys, engine/models | Out-Null
if (-not (Test-Path provider/keys/*.pem)) {
  Write-Host "==> Generating keys"
  Invoke-Checked docker run --rm -v "${PSScriptRoot}\provider\keys:/keys" `
    -e IDEN_SIGNING_KEY_DIR=/keys --entrypoint python iden-dev-provider -m scripts.gen_keys
}

Write-Host "==> Fetching face models (about 290 MB, once)"
Invoke-Checked docker run --rm -v "${PSScriptRoot}\engine\models:/app/models" `
  --entrypoint python iden-dev-engine -m scripts.fetch_models

Write-Host "==> Starting"
Invoke-Compose up -d

Write-Host "==> Waiting for the provider"
for ($i = 0; $i -lt 90 -and -not (Test-Provider); $i++) { Start-Sleep 2 }
if (-not (Test-Provider)) {
  Write-Host "The provider did not start. See: docker compose -f deploy/docker-compose.yml logs migrate provider"
  exit 1
}

Write-Host "==> Seeding"
Invoke-Compose exec provider python -m scripts.seed

Write-Host @"

IDEN is running.
  Dashboard     http://localhost:3000/console/
  Sign-in page  http://localhost:4000/auth/login
  Kiosk         http://localhost:8080   (pair it from Dashboard > Administration > Kiosks)
  API docs      http://localhost:8000/docs

Sign in with the administrator printed above. It is shown only on the first run;
if you lose it, run .\local.cmd reset and then .\local.cmd again.
"@
