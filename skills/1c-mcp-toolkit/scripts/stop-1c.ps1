<#
.SYNOPSIS
    Закрытие 1С через MCP Toolkit (execute_code, клиентский контекст).

.DESCRIPTION
    Отправляет POST /api/execute_code с BSL-кодом
    "ЗавершитьРаботуСистемы(Ложь, Ложь);" в клиентском контексте.

    После этого процесс 1cv8c.exe корректно завершается, освобождая блокировки
    БД (нужно для последующего deploy через EDT update_database).

    Если штатное закрытие не сработало (нет ответа на curl), используй -Force:
    тогда скрипт делает Stop-Process 1cv8c.exe.

.PARAMETER Port
    Порт HTTP-сервера MCP Toolkit. По умолчанию 6003.

.PARAMETER Channel
    Channel для multi-database routing. По умолчанию "default".

.PARAMETER Force
    Если штатный curl не помог - принудительно убить процессы 1cv8c.exe.
    Безопасно для одиночной сессии, опасно при нескольких запущенных клиентах
    (убьет все).

.PARAMETER TimeoutSec
    Таймаут ожидания ответа на curl. По умолчанию 10 секунд.

.EXAMPLE
    .\stop-1c.ps1

.EXAMPLE
    .\stop-1c.ps1 -Port 6003 -Channel "dev"

.EXAMPLE
    .\stop-1c.ps1 -Force

.NOTES
    execution_context="client" обязателен - ЗавершитьРаботуСистемы доступна
    только на клиенте.
#>

[CmdletBinding()]
param(
    [int]$Port = 6003,
    [string]$Channel = "default",
    [switch]$Force,
    [int]$TimeoutSec = 10
)

$ErrorActionPreference = "Stop"

$url = "http://localhost:$Port/api/execute_code?channel=$Channel"
$body = '{"code":"ЗавершитьРаботуСистемы(Ложь, Ложь); Результат=\"OK\";","execution_context":"client"}'

Write-Host "Отправка ЗавершитьРаботуСистемы на $url ..." -ForegroundColor Cyan

$success = $false
try {
    $response = Invoke-RestMethod -Uri $url `
        -Method Post `
        -Body $body `
        -ContentType "application/json; charset=utf-8" `
        -TimeoutSec $TimeoutSec

    if ($response.success) {
        Write-Host "1С закрывается, ответ: $($response.data)" -ForegroundColor Green
        $success = $true
    } else {
        Write-Warning "MCP вернул success=false: $($response.error)"
    }
} catch {
    Write-Warning "Не удалось достучаться до $url : $($_.Exception.Message)"
}

# Ждем пока процессы реально закроются (до 10 сек)
if ($success) {
    $waited = 0
    while ($waited -lt 10) {
        $procs = Get-Process -Name "1cv8c" -ErrorAction SilentlyContinue
        if (-not $procs) {
            Write-Host "Все процессы 1cv8c.exe завершены за $waited сек" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
        $waited++
    }
    Write-Warning "Процесс 1cv8c.exe еще жив через 10 сек после команды. Возможно зависла модальная форма."
}

# Принудительное закрытие
if ($Force) {
    Write-Host "Принудительное закрытие процессов 1cv8c.exe ..." -ForegroundColor Yellow
    $procs = Get-Process -Name "1cv8c" -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | Stop-Process -Force
        Write-Host "Завершено процессов: $($procs.Count)" -ForegroundColor Green
    } else {
        Write-Host "Процессов 1cv8c.exe не обнаружено" -ForegroundColor DarkGray
    }
} elseif (-not $success) {
    Write-Host ""
    Write-Host "Для принудительного закрытия запусти с флагом -Force:" -ForegroundColor Yellow
    Write-Host "  .\stop-1c.ps1 -Force" -ForegroundColor Yellow
    exit 1
}
