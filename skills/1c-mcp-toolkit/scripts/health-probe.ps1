# Быстрая проверка, на каких портах жив MCP Toolkit.
# Вместо вопроса пользователю "какой порт?" - пробуем известные порты и докладываем.
# Использование:
#   pwsh scripts/health-probe.ps1                      # дефолтный набор портов
#   pwsh scripts/health-probe.ps1 -Ports 6003,6023     # свой набор
# Выход: таблица порт/TCP/HTTP + код 0 если жив хотя бы один.

param(
    [int[]]$Ports = @(6003, 6004, 6005, 6010, 6013, 6023, 6033, 7003),
    [int]$TimeoutMs = 700
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$alive = 0
$rows = foreach ($p in $Ports) {
    $tcp = $false; $http = "-"
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $p)
        if ($task.Wait($TimeoutMs) -and $client.Connected) { $tcp = $true }
    } catch {} finally { $client.Dispose() }

    if ($tcp) {
        $url = "http://localhost:$p/health"
        try {
            $resp = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            $http = "OK($($resp.StatusCode))"
        } catch {
            $code = $_.Exception.Response.StatusCode.value__
            $http = if ($code) { "HTTP($code)" } else { "conn-fail" }
        }
        $alive++
    }
    [pscustomobject]@{ Port = $p; TCP = $(if ($tcp) { "open" } else { "-" }); HTTP = $http }
}

$rows | Format-Table -AutoSize | Out-String | Write-Output
if ($alive -gt 0) {
    Write-Output "ALIVE: $alive порт(ов). Использовать живой порт, не переспрашивая."
    exit 0
} else {
    Write-Output "ALIVE: 0. Toolkit не запущен - поднять через scripts/start-1c.ps1 (или спросить пользователя, если базы неизвестны)."
    exit 1
}
