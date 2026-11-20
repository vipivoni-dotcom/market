param([int]$Port = 18080, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'vps-connection.ps1')
$ConnectionOptions = @(Get-VpsConnectionOptions)
$Key = Join-Path $env:USERPROFILE '.ssh\relay_key'
if (-not (Test-Path -LiteralPath $Key)) { throw 'Не найден SSH-ключ relay_key.' }
$Url = "http://127.0.0.1:$Port/"
$Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listener) { throw "Порт $Port уже занят. Если туннель уже работает, откройте $Url" }
$TunnelArguments = $ConnectionOptions + @(
    '-i', ('"' + $Key + '"'), '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
    '-L', "127.0.0.1:${Port}:127.0.0.1:8080", 'relay@81.26.189.76')
$Tunnel = Start-Process ssh.exe -WindowStyle Hidden -PassThru -ArgumentList $TunnelArguments
for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    Start-Sleep -Milliseconds 500
    if ($Tunnel.HasExited) { throw 'SSH-туннель завершился. Проверьте соединение с VPS.' }
    try {
        $Response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
        if ($Response.StatusCode -eq 200) {
            if (-not $NoBrowser) { Start-Process $Url }
            Write-Host "Дашборд: $Url (SSH PID $($Tunnel.Id))"
            exit 0
        }
    } catch { }
}
Stop-Process -Id $Tunnel.Id -ErrorAction SilentlyContinue
throw 'Панель не ответила. Туннель остановлен.'
