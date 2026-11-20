param([switch]$SkipTests, [switch]$FullTests, [switch]$NoRestart, [switch]$PanelOnly, [switch]$FunpayOnly, [switch]$PublicationOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'vps-connection.ps1')
$ConnectionOptions = @(Get-VpsConnectionOptions)
$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$Key = Join-Path $env:USERPROFILE '.ssh\relay_key'
$Remote = 'relay@81.26.189.76'
$RemoteDir = '/opt/apps/market-arbitrage'
$Stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$Archive = Join-Path $env:TEMP "market-arbitrage-$Stamp.tar.gz"

if (-not (Test-Path -LiteralPath $Key)) { throw "SSH-ключ не найден: $Key" }
Push-Location $Project
try {
if (-not $SkipTests) {
    $TestArgs = if ($FullTests) { @('-m', 'pytest', '-q') } elseif ($PublicationOnly) {
        @('-m', 'pytest', '-q', 'tests/test_publication_recovery.py', 'tests/test_publication_progress.py',
          'tests/test_publication_speed.py', 'tests/test_autopilot.py', 'tests/test_playerok_listing.py',
          'tests/test_review_20261116.py', 'tests/test_panel_preview.py', 'tests/test_deploy_script.py')
    } elseif ($FunpayOnly) {
        @('-m', 'pytest', '-q', 'tests/test_app_startup.py', 'tests/test_funpay_public.py', 'tests/test_deploy_script.py')
    } elseif ($PanelOnly) {
        @('-m', 'pytest', '-q', 'tests/test_mobile_login.py', 'tests/test_panel_preview.py',
          'tests/test_safety.py::test_panel_token', 'tests/test_safety.py::test_panel_rejects_cross_site_post',
          'tests/test_deploy_script.py')
    } else {
        @('-m', 'pytest', '-q', 'tests/test_code_only_audit.py', 'tests/test_scan_queue.py',
          'tests/test_mobile_login.py', 'tests/test_safety.py::test_panel_token',
          'tests/test_paygame_unavailable.py',
          'tests/test_publication_progress.py',
          'tests/test_app_startup.py', 'tests/test_review_20261116.py',
          'tests/test_dev_tools.py',
          'tests/test_chain.py', 'tests/test_playerok_listing.py', 'tests/test_deploy_script.py',
          'tests/test_panel_preview.py',
          'tests/test_sellers.py::test_offline_days_understands_funpay_wording')
    }
    & $Python @TestArgs
    if ($LASTEXITCODE -ne 0) { throw 'Тесты не прошли; выкладка отменена.' }
}
    & $Python scripts/check_project.py
    if ($LASTEXITCODE -ne 0) { throw 'Проверка проекта не прошла; выкладка отменена.' }
    if ($PublicationOnly) {
        tar -czf $Archive arb/engine.py arb/platforms/playerok.py arb/web.py scripts/publication_status.py tests/test_publication_recovery.py docs/publication-recovery-2026-11-16.md docs/project.md docs/state.md
    } elseif ($FunpayOnly) {
        tar -czf $Archive arb/app.py arb/platforms/funpay.py config.example.yaml tests/test_funpay_public.py docs/project.md docs/state.md
    } elseif ($PanelOnly) {
        tar -czf $Archive arb/panel.html arb/login.html docs/mobile-dashboard.md deploy/mobile.Caddyfile
    } else {
        tar --exclude='__pycache__' --exclude='*.pyc' -czf $Archive arb scripts tests docs deploy/panel_preview.py run.py tools.py requirements.txt config.example.yaml README.md AGENTS.md
    }
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось упаковать код; выкладка отменена.' }
$BackupCommand = if ($PublicationOnly) { @'
set -e
mkdir -p '{0}/deploy/backups/{1}'
cd '{0}'
tar -czf 'deploy/backups/{1}/pre-update.tgz' arb/engine.py arb/platforms/playerok.py arb/web.py docs/project.md docs/state.md
'@ -f $RemoteDir, $Stamp
} elseif ($FunpayOnly) { @'
set -e
mkdir -p '{0}/deploy/backups/{1}'
cd '{0}'
tar -czf 'deploy/backups/{1}/pre-update.tgz' arb/app.py arb/platforms/funpay.py config.example.yaml docs/project.md docs/state.md
'@ -f $RemoteDir, $Stamp
} elseif ($PanelOnly) { @'
set -e
mkdir -p '{0}/deploy/backups/{1}'
cd '{0}'
tar -czf 'deploy/backups/{1}/pre-update.tgz' arb/panel.html arb/login.html
'@ -f $RemoteDir, $Stamp
} else { @'
set -e
mkdir -p '{0}/deploy/backups/{1}'
cd '{0}'
set -- arb scripts run.py tools.py requirements.txt config.example.yaml README.md AGENTS.md
for path in tests docs deploy/panel_preview.py; do
    if [ -e "$path" ]; then set -- "$@" "$path"; fi
done
tar --exclude='__pycache__' -czf 'deploy/backups/{1}/pre-update.tgz' "$@"
'@ -f $RemoteDir, $Stamp
}
ssh @ConnectionOptions -i $Key $Remote ($BackupCommand -replace "`r", '')
if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать резервную копию на VPS.' }
scp @ConnectionOptions -i $Key $Archive "${Remote}:/tmp/market-arbitrage-$Stamp.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'Не удалось загрузить архив на VPS.' }
ssh @ConnectionOptions -i $Key $Remote "cd '$RemoteDir' && tar --no-overwrite-dir --no-same-owner --no-same-permissions -xzf '/tmp/market-arbitrage-$Stamp.tar.gz' && rm '/tmp/market-arbitrage-$Stamp.tar.gz'"
if ($LASTEXITCODE -ne 0) { throw 'Не удалось распаковать обновление на VPS.' }
if (-not $NoRestart) {
    ssh @ConnectionOptions -i $Key $Remote "sudo systemctl restart market-arbitrage && sleep 4 && systemctl is-active market-arbitrage && cd '$RemoteDir' && .venv/bin/python scripts/bot_status.py"
    if ($LASTEXITCODE -ne 0) { throw 'Служба после обновления не запустилась.' }
}
Write-Host "Выложено: $Stamp"
}
finally {
    Pop-Location
    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
}
