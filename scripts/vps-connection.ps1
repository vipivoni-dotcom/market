function Get-VpsConnectionOptions {
    # Привязка сокета к физическому интерфейсу не меняет маршруты и настройки VPN.
    # При неоднозначном выборе оставляем штатную маршрутизацию SSH.
    try {
        $Candidates = @(Get-NetIPConfiguration -ErrorAction Stop | Where-Object {
            $_.NetAdapter.HardwareInterface -and $_.NetAdapter.Status -eq 'Up' -and $_.IPv4DefaultGateway
        } | ForEach-Object { $_.IPv4Address } | Where-Object {
            $_.IPAddress -and $_.IPAddress -notlike '169.254.*'
        } | Select-Object -ExpandProperty IPAddress -Unique)
        if ($Candidates.Count -eq 1) {
            '-o'
            "BindAddress=$($Candidates[0])"
        }
    } catch {
        # Например, Get-NetIPConfiguration недоступна вне Windows.
        return
    }
}
