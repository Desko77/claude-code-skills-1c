# db-update v1.0 - Update 1C database configuration
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Обновление конфигурации базы данных 1С

.DESCRIPTION
    Применяет изменения основной конфигурации к конфигурации базы данных.
    Поддерживает динамическое обновление, обновление расширений.

.PARAMETER V8Path
    Путь к каталогу bin платформы или к 1cv8.exe

.PARAMETER InfoBasePath
    Путь к файловой информационной базе

.PARAMETER InfoBaseServer
    Сервер 1С (для серверной базы)

.PARAMETER InfoBaseRef
    Имя базы на сервере

.PARAMETER UserName
    Имя пользователя 1С

.PARAMETER Password
    Пароль пользователя

.PARAMETER Extension
    Имя расширения для обновления

.PARAMETER AllExtensions
    Обновить все расширения

.PARAMETER Dynamic
    Динамическое обновление: "+" включить, "-" отключить

.PARAMETER Server
    Обновление на стороне сервера

.PARAMETER WarningsAsErrors
    Предупреждения считать ошибками

.EXAMPLE
    .\db-update.ps1 -InfoBasePath "C:\Bases\MyDB"

.EXAMPLE
    .\db-update.ps1 -InfoBasePath "C:\Bases\MyDB" -Dynamic "+" -Extension "МоеРасширение"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$V8Path,

    [Parameter(Mandatory=$false)]
    [string]$InfoBasePath,

    [Parameter(Mandatory=$false)]
    [string]$InfoBaseServer,

    [Parameter(Mandatory=$false)]
    [string]$InfoBaseRef,

    [Parameter(Mandatory=$false)]
    [string]$UserName,

    [Parameter(Mandatory=$false)]
    [string]$Password,

    [Parameter(Mandatory=$false)]
    [string]$Extension,

    [Parameter(Mandatory=$false)]
    [switch]$AllExtensions,

    [Parameter(Mandatory=$false)]
    [ValidateSet("+", "-")]
    [string]$Dynamic,

    [Parameter(Mandatory=$false)]
    [switch]$Server,

    [Parameter(Mandatory=$false)]
    [switch]$WarningsAsErrors,

    [Parameter(Mandatory=$false)]
    [switch]$StrictLog,

    [Parameter(Mandatory=$false)]
    [switch]$CheckApplicability
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- Вердикт платформы (общий блок, версия 1) ---
# Платформа сообщает результат тремя независимыми каналами, и ни один не самодостаточен:
# нулевой код возврата при проваленной операции - ее штатное поведение. Четвертый сигнал -
# постусловие: артефакт операции действительно появился и он от этого запуска.

function Hide-PlatformSecret {
    param([string]$Text)
    if (-not $Text) { return $Text }
    # Ключи с секретом: пароль базы, код разблокировки, пароль хранилища конфигурации.
    # Длинные имена стоят первыми, иначе короткое подойдет как префикс длинного.
    $keys = '(?:^|(?<=\s))(/ConfigurationRepositoryP|/UC|/P)'
    $masked = $Text -replace ($keys + '"[^"]*"'), '$1"***"'
    $masked = $masked -replace ($keys + '([^\s"]\S*)'), '$1***'
    # Утилита администрирования принимает секрет длинным ключом со знаком равенства:
    # --token=, --password=, --db-pwd=. Правило для ключей платформы их не покрывает.
    $longKeys = '(?:^|(?<=\s))(--(?:token|password|db-pwd|pwd)=)'
    $masked = $masked -replace ($longKeys + '"[^"]*"'), '$1"***"'
    $masked = $masked -replace ($longKeys + '([^\s"]\S*)'), '$1***'
    return $masked
}

function Get-PlatformLogProblems {
    param([string]$LogText)
    $problems = @()
    if (-not $LogText) { return $problems }
    # Фразы, которыми платформа сообщает об ОТСУТСТВИИ проблем. Сверяются раньше диагностики
    # и целиком: строка "операция завершена с ошибками" не должна попасть под "операция завершена".
    $cleanPhrases = @(
        'ошибок не обнаружено',
        'ошибки не обнаружены',
        'предупреждений не обнаружено',
        'ошибок: 0',
        'предупреждений: 0',
        'errors were not found',
        '0 errors'
    )
    # Сообщения, при которых операция провалена, даже если код возврата нулевой.
    $fatalPhrases = @(
        'неверное свойство объекта метаданных',
        'не входит в состав объекта метаданных',
        'неизвестное имя типа',
        'неизвестный объект метаданных',
        'ни один из документов не является регистратором для регистра',
        'неверное значение перечисления',
        'не может быть приведен к типу',
        'необходима версия платформы не меньше',
        'не найден метод',
        'не может быть применен'
    )
    foreach ($line in ($LogText -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }
        $lower = $trimmed.ToLowerInvariant()
        $isClean = $false
        foreach ($phrase in $cleanPhrases) {
            if ($lower.Contains($phrase)) { $isClean = $true; break }
        }
        if ($isClean) { continue }
        foreach ($phrase in $fatalPhrases) {
            if ($lower.Contains($phrase)) { $problems += $trimmed; break }
        }
    }
    return $problems
}

function Get-PlatformResultCode {
    param([string]$ResultFile)
    if (-not $ResultFile -or -not (Test-Path $ResultFile)) { return $null }
    $raw = (Get-Content $ResultFile -Raw -ErrorAction SilentlyContinue)
    if ($null -eq $raw) { return $null }
    $raw = $raw.Trim()
    if ($raw -eq '') { return $null }
    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed)) { return $parsed }
    return $null
}

function Write-PlatformVerdict {
    param(
        [int]$ExitCode,
        [string]$ResultFile,
        [string]$LogText,
        [string]$ArtifactPath,
        [string]$SuccessMessage,
        [string]$FailureMessage,
        [switch]$Strict
    )
    $finalCode = $ExitCode
    $resultCode = Get-PlatformResultCode -ResultFile $ResultFile
    if ($null -ne $resultCode -and $resultCode -ne 0 -and $finalCode -eq 0) {
        Write-Host "[error] platform result code: $resultCode" -ForegroundColor Red
        $finalCode = 1
    }
    if ($finalCode -eq 0) {
        Write-Host $SuccessMessage -ForegroundColor Green
    } else {
        Write-Host "$FailureMessage (code: $finalCode)" -ForegroundColor Red
    }
    if ($LogText) {
        Write-Host "--- Log ---"
        Write-Host $LogText
        Write-Host "--- End ---"
    }
    $problems = @(Get-PlatformLogProblems -LogText $LogText)
    if ($problems.Count -gt 0) {
        Write-Host "[warning] platform reported success, but the log contains $($problems.Count) problem(s):" -ForegroundColor Yellow
        foreach ($problem in $problems) { Write-Host "  $problem" -ForegroundColor Yellow }
        if ($Strict -and $finalCode -eq 0) { $finalCode = 1 }
    }
    if ($ArtifactPath -and $finalCode -eq 0 -and -not (Test-Path $ArtifactPath)) {
        Write-Host "[error] platform reported success, but the expected result is missing: $ArtifactPath" -ForegroundColor Red
        $finalCode = 1
    }
    return $finalCode
}
# --- Конец общего блока вердикта платформы ---
# --- Resolve V8Path ---
if (-not $V8Path) {
    $found = Get-ChildItem "C:\Program Files\1cv8\*\bin\1cv8.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) {
        $V8Path = $found.FullName
    } else {
        Write-Host "Error: 1cv8.exe not found. Specify -V8Path" -ForegroundColor Red
        exit 1
    }
} elseif (Test-Path $V8Path -PathType Container) {
    $V8Path = Join-Path $V8Path "1cv8.exe"
}

if (-not (Test-Path $V8Path)) {
    Write-Host "Error: 1cv8.exe not found at $V8Path" -ForegroundColor Red
    exit 1
}

# --- Validate connection ---
if (-not $InfoBasePath -and (-not $InfoBaseServer -or -not $InfoBaseRef)) {
    Write-Host "Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef" -ForegroundColor Red
    exit 1
}

# --- Temp dir ---
$tempDir = Join-Path $env:TEMP "db_update_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # --- Проверка применимости расширения ---
    # Перехватчик расширения, который ссылается на метод, переименованный поставщиком,
    # не виден ни синтаксическому контролю, ни проверке XML: исходники корректны. Отказ
    # обнаруживается только этой проверкой и только против конкретной базы.
    if ($CheckApplicability -and -not ($Extension -or $AllExtensions)) {
        Write-Host "Error: -CheckApplicability requires -Extension or -AllExtensions" -ForegroundColor Red
        exit 1
    }

    if ($CheckApplicability) {
        $checkArgs = @("DESIGNER")
        if ($InfoBaseServer -and $InfoBaseRef) {
            $checkArgs += "/S", "`"$InfoBaseServer/$InfoBaseRef`""
        } else {
            $checkArgs += "/F", "`"$InfoBasePath`""
        }
        if ($UserName) { $checkArgs += "/N`"$UserName`"" }
        if ($Password) { $checkArgs += "/P`"$Password`"" }
        $checkArgs += "/CheckCanApplyConfigurationExtensions"
        if ($Extension) { $checkArgs += "-Extension", "`"$Extension`"" }
        $checkOut = Join-Path $tempDir "check_apply_log.txt"
        $checkResult = Join-Path $tempDir "check_apply_result.txt"
        $checkArgs += "/Out", "`"$checkOut`""
        $checkArgs += "/DumpResult", "`"$checkResult`""
        $checkArgs += "/DisableStartupDialogs"

        Write-Host "Running: 1cv8.exe $(Hide-PlatformSecret ($checkArgs -join ' '))"
        $checkProc = Start-Process -FilePath $V8Path -ArgumentList $checkArgs -NoNewWindow -Wait -PassThru
        $checkLog = $null
        if (Test-Path $checkOut) {
            $checkLog = Get-Content $checkOut -Raw -ErrorAction SilentlyContinue
        }
        # Строгий режим здесь включен всегда, а не по ключу вызова: смысл проверки в том,
        # чтобы остановить обновление. Отказ платформа сообщает строкой журнала при нулевом
        # коде возврата, и без строгости проверка нашла бы несовместимость и пропустила
        # обновление дальше.
        $checkCode = Write-PlatformVerdict -ExitCode $checkProc.ExitCode -ResultFile $checkResult -LogText $checkLog `
            -SuccessMessage "Extension applicability check passed" `
            -FailureMessage "Extension applicability check failed" `
            -Strict
        if ($checkCode -ne 0) {
            Write-Host "Database configuration was NOT updated: the extension cannot be applied to this infobase" -ForegroundColor Red
            exit $checkCode
        }
    }

    # --- Build arguments ---
    $arguments = @("DESIGNER")

    if ($InfoBaseServer -and $InfoBaseRef) {
        $arguments += "/S", "`"$InfoBaseServer/$InfoBaseRef`""
    } else {
        $arguments += "/F", "`"$InfoBasePath`""
    }

    if ($UserName) { $arguments += "/N`"$UserName`"" }
    if ($Password) { $arguments += "/P`"$Password`"" }

    $arguments += "/UpdateDBCfg"

    # --- Options ---
    if ($Dynamic) {
        $arguments += "-Dynamic$Dynamic"
    }
    if ($Server) {
        $arguments += "-Server"
    }
    if ($WarningsAsErrors) {
        $arguments += "-WarningsAsErrors"
    }

    # --- Extensions ---
    if ($Extension) {
        $arguments += "-Extension", "`"$Extension`""
    } elseif ($AllExtensions) {
        $arguments += "-AllExtensions"
    }

    # --- Output ---
    # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
    # достаться от прошлого прогона.
    $outFile = Join-Path $tempDir "update_log.txt"
    $resultFile = Join-Path $tempDir "update_result.txt"
    $arguments += "/Out", "`"$outFile`""
    $arguments += "/DumpResult", "`"$resultFile`""
    $arguments += "/DisableStartupDialogs"

    # --- Execute ---
    Write-Host "Running: 1cv8.exe $(Hide-PlatformSecret ($arguments -join ' '))"
    $process = Start-Process -FilePath $V8Path -ArgumentList $arguments -NoNewWindow -Wait -PassThru
    $exitCode = $process.ExitCode

    # --- Result ---
    $logContent = $null
    if (Test-Path $outFile) {
        $logContent = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
    }

    $exitCode = Write-PlatformVerdict -ExitCode $exitCode -ResultFile $resultFile -LogText $logContent `
        -SuccessMessage "Database configuration updated successfully" `
        -FailureMessage "Error updating database configuration" `
        -Strict:$StrictLog

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
