<#
.SYNOPSIS
    Запуск 1С тонкого клиента с авто-открытием обработки MCP_Toolkit.epf.

.DESCRIPTION
    Запускает 1cv8c.exe указанной версии платформы для указанной файловой базы
    с автологином и автоматическим открытием MCP_Toolkit.epf (из bin/ скилла).

    Два режима поднятия HTTP-сервера:

    1. Ручной (по умолчанию): обработка открывается, сервер поднимается кнопкой
       "Запустить сервер" на форме. С -WaitForReady скрипт поллит /health.

    2. Автостарт (-AutoStart): через параметр запуска /C "autostart;<timestamp>;<params.json>"
       обработка сама поднимает встроенный сервер при открытии (порт и режим берет
       из сохраненных настроек ХранилищаОбщихНастроек - их надо один раз задать на форме).
       Скрипт генерирует nonce/params/signal-файлы и поллит signal-файл до "ready"/"failed:".

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

.PARAMETER AutoStart
    Если указан, сервер поднимается автоматически через механизм autostart обработки
    (параметр запуска /C). Не требует ручного нажатия "Запустить сервер".
    Скрипт ждет сигнала готовности (signal-файл) до -AutoStartTimeoutSec секунд.
    Порт и режим (встроенный сервер) обработка берет из сохраненных настроек -
    они должны быть заданы на форме хотя бы раз (порт сохраняется автоматически).

.PARAMETER AutoStartTimeoutSec
    Таймаут ожидания сигнала готовности autostart (по умолчанию 90).

.PARAMETER AllowWrite
    Только с -AutoStart. Выставляет на форме флаг "Разрешить Записать" (auto_allow_write
    в autostart-params). Без него execute_code с ключевым словом Записать блокируется.

.PARAMETER AllowPrivileged
    Только с -AutoStart. Выставляет флаг "Разрешить УстановитьПривилегированныйРежим"
    (auto_allow_privileged). Без него execute_code с УстановитьПривилегированныйРежим блокируется.

.PARAMETER WaitForReady
    Если указан (без -AutoStart), скрипт поллит http://localhost:<Port>/health
    каждые 2 секунды до 60 секунд, и выходит когда сервер ответил 200.

.PARAMETER Port
    Порт для polling готовности /health (с -WaitForReady или -AutoStart как доп. проверка).
    По умолчанию 6003. ВАЖНО: при -AutoStart порт сервера определяется сохраненными
    настройками обработки, а не этим параметром - этот порт только для финальной проверки /health.

.EXAMPLE
    .\start-1c.ps1 -Platform "8.3.27.2074" -Database "E:\1C\БазаДанных" -User "Admin" -Password "<пароль>"

.EXAMPLE
    .\start-1c.ps1 -Platform "8.3.27.2074" -Database "E:\1C\MyDatabase" -User "Admin" -Password "<пароль>" -AutoStart -Port 6004

.NOTES
    Запускать через PowerShell 7 (pwsh), НЕ через powershell.exe (5.1):
    PS 5.1 ломается на кириллице в JSON-телах toolkit. Из Bash tool -
    '/c/Program Files/PowerShell/7/pwsh.exe' -NoProfile -File "...start-1c.ps1" ...
    EPF из bin/ скилла.

    Автостарт-механизм (по исходникам обработки, Forms/Форма/Ext/Form/Module.bsl:244):
    - /C "autostart;<timestamp ГГГГММДДЧЧММСС>;<путь к params.json>"
    - timestamp свежее 300 секунд (иначе autostart игнорируется)
    - nonce-файл должен СУЩЕСТВОВАТЬ на момент ПриОткрытии (валидность владения)
    - обработка пишет в signal-файл "ready" при успехе или "failed:<текст>" при ошибке
    - флаги "Разрешить Записать/УстановитьПривилегированныйРежим" автостартом НЕ
      выставляются (дефолт формы) - для операций записи задать их на форме вручную.
#>

[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', '', Justification = 'Пароль передается в 1cv8c.exe /P как plain-text; SecureString конвертировался бы обратно немедленно')]
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

    [switch]$AutoStart,

    [int]$AutoStartTimeoutSec = 90,

    [switch]$AllowWrite,

    [switch]$AllowPrivileged,

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

# 2. Готовим аргументы запуска (+ autostart-файлы при -AutoStart)
$arguments = @(
    "/F`"$Database`"",
    "/N`"$User`"",
    "/P`"$Password`"",
    "/Execute`"$epfFullPath`""
)

$signalPath = $null
if ($AutoStart) {
    $workDir = Join-Path $env:TEMP "mcp-toolkit-autostart"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null

    $stamp = Get-Date -Format "yyyyMMddHHmmss"
    $noncePath  = Join-Path $workDir "nonce_$stamp.txt"
    $signalPath = Join-Path $workDir "signal_$stamp.txt"
    $claimedPath = Join-Path $workDir "claimed_$stamp.txt"
    $paramsPath = Join-Path $workDir "params_$stamp.json"

    # nonce должен существовать на момент ПриОткрытии (обработка проверяет .Существует()).
    # signal/claimed обработка создает сама - убираем возможные старые.
    Set-Content -LiteralPath $noncePath -Value "1" -NoNewline -Encoding utf8
    Remove-Item -LiteralPath $signalPath -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $claimedPath -ErrorAction SilentlyContinue

    # params.json: формат из обработки (ПрочитатьJSON2 в ПриОткрытии).
    # ConvertTo-Json экранирует обратные слеши путей в \\ - 1С ПрочитатьJSON2 их разворачивает.
    # auto_allow_* - принудительно выставить флаги авторазрешения операций при старте
    # (обработка применяет их в блоке autostart перед запуском сервера). Нужно для
    # автоматических сценариев с записью/привилегированным режимом без ручных чекбоксов.
    $params = [ordered]@{
        signal_path          = $signalPath
        nonce_path           = $noncePath
        claimed_path         = $claimedPath
        mappings_path        = ""
        mcp_sessions         = @()
        restart_password     = ""
        auto_allow_write     = [bool]$AllowWrite
        auto_allow_privileged = [bool]$AllowPrivileged
    }
    # -Compress: однострочный JSON. utf8 в pwsh7 = без BOM (1С ЧтениеТекста UTF8 ждет без BOM).
    ($params | ConvertTo-Json -Compress) | Set-Content -LiteralPath $paramsPath -Encoding utf8 -NoNewline

    $cParam = "autostart;$stamp;$paramsPath"
    $arguments += "/C`"$cParam`""
}

# 3. Запускаем 1С
Write-Host "Запуск 1С..." -ForegroundColor Cyan
Write-Host "  Платформа:    $exePath"
Write-Host "  База:         $Database"
Write-Host "  Пользователь: $User"
Write-Host "  Обработка:    $epfFullPath"
if ($AutoStart) {
    Write-Host "  Режим:        АВТОСТАРТ (сервер поднимется сам, порт из настроек обработки)" -ForegroundColor Yellow
}

$process = Start-Process -FilePath $exePath -ArgumentList $arguments -PassThru

Write-Host "1С запущена, PID: $($process.Id)" -ForegroundColor Green

# 4. Ожидание готовности
if ($AutoStart) {
    Write-Host "Ожидание сигнала готовности autostart ($signalPath) ..." -ForegroundColor Cyan

    $elapsed = 0
    $interval = 2
    $result = $null

    while ($elapsed -lt $AutoStartTimeoutSec) {
        Start-Sleep -Seconds $interval
        $elapsed += $interval

        if (Test-Path -LiteralPath $signalPath) {
            $content = (Get-Content -LiteralPath $signalPath -Raw -ErrorAction SilentlyContinue)
            if ($null -ne $content) { $content = $content.Trim() }

            if ($content -eq "ready") {
                $result = "ready"
                break
            } elseif ($content -like "failed:*") {
                $result = $content
                break
            }
        }
        Write-Host "  ... $elapsed сек, жду сигнал" -ForegroundColor DarkGray
    }

    if ($result -eq "ready") {
        Write-Host "Сервер поднят автостартом (signal=ready)." -ForegroundColor Green
        # Доп. проверка /health (порт из настроек обработки; -Port для проверки)
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "  /health на порту $Port отвечает 200 OK." -ForegroundColor Green
            }
        } catch {
            Write-Warning "signal=ready, но /health на порту $Port не ответил. Возможно сервер на другом порту (проверь сохраненный порт в обработке)."
        }
    } elseif ($null -ne $result) {
        Write-Warning "Автостарт не удался: $result"
        Write-Warning "Процесс 1С оставлен запущенным (PID $($process.Id))."
        exit 1
    } else {
        Write-Warning "Сигнал готовности не получен за $AutoStartTimeoutSec сек. Проверь: 1) сохранен ли в обработке режим 'Встроенный сервер'; 2) свежесть timestamp; 3) форму обработки в 1С."
        Write-Warning "Процесс 1С оставлен запущенным (PID $($process.Id))."
        exit 1
    }
}
elseif ($WaitForReady) {
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
            Write-Host "  ... $elapsed сек, сервер еще не готов" -ForegroundColor DarkGray
        }
    }

    if ($ready) {
        Write-Host "HTTP-сервер готов на $healthUrl" -ForegroundColor Green
    } else {
        Write-Warning "HTTP-сервер не поднялся за $timeout секунд. Проверь форму обработки в 1С: вкладка 'Подключение' -> 'Встроенный сервер' -> 'Запустить сервер'."
        Write-Warning "Процесс 1С оставлен запущенным (PID $($process.Id))."
        exit 1
    }
}

# 5. Возвращаем PID для возможного использования вызывающим
return $process.Id
