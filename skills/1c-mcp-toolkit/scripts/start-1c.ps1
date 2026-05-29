<#
.SYNOPSIS
    Запуск 1С тонкого клиента с авто-открытием обработки MCP_Toolkit.epf.

.DESCRIPTION
    Запускает 1cv8c.exe указанной версии платформы для указанной файловой базы
    с автологином и автоматическим открытием MCP_Toolkit.epf (из bin/ скилла).

    После открытия обработка поднимает встроенный HTTP-сервер на порту 6003
    (или указанном в форме обработки), доступный по http://localhost:6003/api/*.

    Без -User и -Password 1С зависает на форме авторизации - HTTP-сервер
    подняться не успеет.

.PARAMETER Platform
    Версия платформы 1С, например "8.3.27.2074". Используется для построения
    пути к 1cv8c.exe: "C:\Program Files\1cv8\<Platform>\bin\1cv8c.exe".

.PARAMETER Database
    Путь к файловой базе (папка с 1Cv8.1CD).

.PARAMETER User
    Имя пользователя для автологина.

.PARAMETER Password
    Пароль для автологина.

.PARAMETER EpfPath
    Путь к MCP_Toolkit.epf. По умолчанию - bin/MCP_Toolkit.epf рядом со скриптом.
    Передай bin/MCP_Toolkit_x86.epf для x86-платформ.

.PARAMETER WaitForReady
    Если указан, скрипт после запуска поллит http://localhost:<Port>/health
    каждые 2 секунды до 60 секунд, и выходит когда сервер ответил 200.

.PARAMETER Port
    Порт для polling готовности (используется только с -WaitForReady).
    По умолчанию 6003.

.EXAMPLE
    .\start-1c.ps1 -Platform "8.3.27.2074" -Database "E:\1C\БазаДанных" -User "Admin" -Password "<пароль>"

.EXAMPLE
    .\start-1c.ps1 -Platform "8.3.27.2074" -Database "E:\1C\MyDatabase" -User "Admin" -Password "<пароль>" -WaitForReady

.NOTES
    Требует PowerShell 5.1+ или PowerShell 7+.
    EPF из ~/.claude/skills/1c-mcp-toolkit/bin/.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Platform,

    [Parameter(Mandatory = $true)]
    [string]$Database,

    [Parameter(Mandatory = $true)]
    [string]$User,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [string]$EpfPath = (Join-Path $PSScriptRoot "..\bin\MCP_Toolkit.epf"),

    [switch]$WaitForReady,

    [int]$Port = 6003
)

$ErrorActionPreference = "Stop"

# 1. Резолвим пути
$exePath = "C:\Program Files\1cv8\$Platform\bin\1cv8c.exe"
$epfFullPath = Resolve-Path -LiteralPath $EpfPath -ErrorAction Stop

if (-not (Test-Path -LiteralPath $exePath)) {
    Write-Error "1cv8c.exe не найден по пути: $exePath. Проверь параметр -Platform."
    exit 1
}

if (-not (Test-Path -LiteralPath $Database)) {
    Write-Error "Файловая база не найдена: $Database"
    exit 1
}

# 2. Запускаем 1С
Write-Host "Запуск 1С..." -ForegroundColor Cyan
Write-Host "  Платформа:    $exePath"
Write-Host "  База:         $Database"
Write-Host "  Пользователь: $User"
Write-Host "  Обработка:    $epfFullPath"

$arguments = @(
    "/F`"$Database`"",
    "/N`"$User`"",
    "/P`"$Password`"",
    "/Execute`"$epfFullPath`""
)

$process = Start-Process -FilePath $exePath -ArgumentList $arguments -PassThru

Write-Host "1С запущена, PID: $($process.Id)" -ForegroundColor Green

# 3. Опционально ждем поднятия HTTP-сервера
if ($WaitForReady) {
    $healthUrl = "http://localhost:$Port/health"
    Write-Host "Ожидание готовности HTTP-сервера на $healthUrl ..." -ForegroundColor Cyan

    $timeout = 60
    $elapsed = 0
    $ready = $false

    while ($elapsed -lt $timeout) {
        Start-Sleep -Seconds 2
        $elapsed += 2

        try {
            $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            # Сервер еще не отвечает, продолжаем ждать
            Write-Host "  ... $elapsed сек, сервер еще не готов" -ForegroundColor DarkGray
        }
    }

    if ($ready) {
        Write-Host "HTTP-сервер готов на $healthUrl" -ForegroundColor Green
    } else {
        Write-Warning "HTTP-сервер не поднялся за $timeout секунд. Проверь форму обработки в 1С: вкладка 'Подключение' -> 'Встроенный сервер' -> 'Запустить сервер'."
    }
}

# 4. Возвращаем PID для возможного использования вызывающим
return $process.Id
