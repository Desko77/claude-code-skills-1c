# storage-ops v1.1 - Configuration repository operations
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Операции с хранилищем конфигурации 1С

.DESCRIPTION
    Одна точка входа для операций с хранилищем: отчет по версиям, захват объектов,
    обновление из хранилища, помещение, отмена захвата, выгрузка конфигурации в CF.

    Список объектов передается платформе XML-файлом заданной схемы. Скрипт собирает его
    сам из перечня полных имен и удаляет после операции.

.PARAMETER Operation
    status | lock | update | commit | unlock | dump

.EXAMPLE
    .\storage-ops.ps1 -Operation status -InfoBasePath "C:\Bases\MyDB" -RepositoryPath "C:\Repo" -OutputFile "report.mxl"

.EXAMPLE
    .\storage-ops.ps1 -Operation lock -InfoBasePath "C:\Bases\MyDB" -RepositoryPath "C:\Repo" -Objects "Справочник.Валюты,Документ.Заказ"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("status", "lock", "update", "commit", "unlock", "dump", "bind", "unbind")]
    [string]$Operation,

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

    [Parameter(Mandatory=$true)]
    [string]$RepositoryPath,

    [Parameter(Mandatory=$false)]
    [string]$RepositoryUser,

    [Parameter(Mandatory=$false)]
    [string]$RepositoryPassword,

    [Parameter(Mandatory=$false)]
    [string]$Objects,

    [Parameter(Mandatory=$false)]
    [switch]$IncludeChildObjects,

    [Parameter(Mandatory=$false)]
    [string]$Comment,

    [Parameter(Mandatory=$false)]
    [switch]$KeepLocked,

    [Parameter(Mandatory=$false)]
    [string]$OutputFile,

    [Parameter(Mandatory=$false)]
    [int]$Version,

    [Parameter(Mandatory=$false)]
    [string]$Extension,

    [Parameter(Mandatory=$false)]
    [switch]$Force,

    [Parameter(Mandatory=$false)]
    [switch]$ConfirmForce,

    [Parameter(Mandatory=$false)]
    [switch]$ConfirmDiscardChanges,

    [Parameter(Mandatory=$false)]
    [switch]$ConfirmUnbind,

    [Parameter(Mandatory=$false)]
    [switch]$BindAlreadyBoundUser,

    [Parameter(Mandatory=$false)]
    [switch]$ReplaceLocalConfiguration,

    [Parameter(Mandatory=$false)]
    [switch]$ConfirmReplaceLocalConfiguration,

    [Parameter(Mandatory=$false)]
    [switch]$StrictLog
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


# --- Операции и их отношение к списку объектов ---
# Платформа без списка применяет операцию ко ВСЕЙ конфигурации, поэтому там, где список
# обязателен, его отсутствие - отказ, а не работа по умолчанию.
$objectsRequired = @("lock", "update", "commit", "unlock")
$objectsRejected = @("status", "dump", "bind", "unbind")
$outputRequired = @("status", "dump")

if ($objectsRequired -contains $Operation -and -not $Objects) {
    Write-Host "Error: operation '$Operation' requires -Objects with explicit metadata full names" -ForegroundColor Red
    Write-Host "  Without a list the platform applies the operation to the WHOLE configuration" -ForegroundColor Red
    exit 1
}
if ($objectsRejected -contains $Operation -and $Objects) {
    Write-Host "Error: operation '$Operation' does not take -Objects" -ForegroundColor Red
    exit 1
}
if ($outputRequired -contains $Operation -and -not $OutputFile) {
    Write-Host "Error: operation '$Operation' requires -OutputFile" -ForegroundColor Red
    exit 1
}
if ($Operation -eq "commit" -and -not $Comment) {
    Write-Host "Error: commit requires -Comment (task reference and what changed)" -ForegroundColor Red
    exit 1
}

# --- Подключение и отключение: подтверждения ---
# Отключение обратимо повторным подключением, но до него совместная работа команды через это
# хранилище не идет, а незафиксированные захваты теряются. Замена локальной конфигурации при
# подключении затирает несохраненные правки. Оба действия требуют явного подтверждения.
if ($Operation -eq "unbind" -and -not $ConfirmUnbind) {
    Write-Host "Error: unbind disconnects the infobase from the repository - pass -ConfirmUnbind" -ForegroundColor Red
    Write-Host "  Until it is bound again, nobody works with this repository through this infobase" -ForegroundColor Red
    exit 1
}
if ($ReplaceLocalConfiguration -and -not $ConfirmReplaceLocalConfiguration) {
    Write-Host "Error: -ReplaceLocalConfiguration overwrites the local configuration with the repository one - pass -ConfirmReplaceLocalConfiguration" -ForegroundColor Red
    exit 1
}

# --- Разбор и проверка перечня объектов ---
$objectNames = @()
if ($Objects) {
    foreach ($raw in ($Objects -split ',')) {
        $name = $raw.Trim()
        if (-not $name) { continue }
        if ($name -match '[\*\?]') {
            Write-Host "Error: masks are not allowed in -Objects: '$name'" -ForegroundColor Red
            exit 1
        }
        if ($name -eq 'Конфигурация' -or $name -eq 'Configuration') {
            Write-Host "Error: the configuration root is not an allowed target: '$name'" -ForegroundColor Red
            Write-Host "  Name the objects explicitly - an operation on the root covers everything" -ForegroundColor Red
            exit 1
        }
        if ($name -notmatch '\.') {
            Write-Host "Error: expected a metadata full name like 'Справочник.Валюты', got '$name'" -ForegroundColor Red
            exit 1
        }
        $objectNames += $name
    }
    if ($objectNames.Count -eq 0) {
        Write-Host "Error: -Objects is empty after parsing" -ForegroundColor Red
        exit 1
    }
    $duplicates = $objectNames | Group-Object | Where-Object { $_.Count -gt 1 }
    if ($duplicates) {
        Write-Host "Error: duplicate names in -Objects: $(($duplicates | ForEach-Object { $_.Name }) -join ', ')" -ForegroundColor Red
        exit 1
    }
}

# --- Принудительный режим: двое ворот ---
# Долговременное разрешение живет в настройках проекта, подтверждение приходит вызовом.
# Одного ключа мало: принудительная отмена захвата теряет несохраненные изменения.
if ($Force) {
    $projectFile = Join-Path (Get-Location) ".v8-project.json"
    $allowed = $false
    if (Test-Path $projectFile) {
        try {
            $project = Get-Content $projectFile -Raw | ConvertFrom-Json
            $allowed = [bool]$project.repositoryAllowForce
        } catch {
            $allowed = $false
        }
    }
    if (-not $allowed) {
        Write-Host "Error: -Force requires 'repositoryAllowForce': true in .v8-project.json" -ForegroundColor Red
        exit 1
    }
    if ($Operation -eq "unlock") {
        if (-not $ConfirmDiscardChanges) {
            Write-Host "Error: forced unlock discards uncommitted changes - pass -ConfirmDiscardChanges" -ForegroundColor Red
            exit 1
        }
    } elseif (-not $ConfirmForce) {
        Write-Host "Error: -Force requires -ConfirmForce" -ForegroundColor Red
        exit 1
    }
}

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
$tempDir = Join-Path $env:TEMP "storage_ops_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # --- Файл списка объектов ---
    # Схема и имена атрибутов замерены на платформе: простой текст платформа отвергает
    # разбором XML, а атрибут называется includeChildObjects - на includeChildren она
    # отвечает явным сообщением об ожидаемом теге.
    $objectsFile = $null
    if ($objectNames.Count -gt 0) {
        $objectsFile = Join-Path $tempDir "objects.xml"
        $include = if ($IncludeChildObjects) { "true" } else { "false" }
        $lines = @('<?xml version="1.0" encoding="UTF-8"?>',
                   '<Objects xmlns="http://v8.1c.ru/8.3/config/objects" version="1.0">')
        foreach ($name in $objectNames) {
            $escaped = $name.Replace('&', '&amp;').Replace('<', '&lt;').Replace('"', '&quot;')
            $lines += "  <Object fullName=`"$escaped`" includeChildObjects=`"$include`"/>"
        }
        $lines += '</Objects>'
        [System.IO.File]::WriteAllLines($objectsFile, $lines, [System.Text.UTF8Encoding]::new($false))
        Write-Host "Objects ($($objectNames.Count)): $($objectNames -join ', ')"
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

    # --- Repository connection ---
    $arguments += "/ConfigurationRepositoryF", "`"$RepositoryPath`""
    if ($RepositoryUser) { $arguments += "/ConfigurationRepositoryN", "`"$RepositoryUser`"" }
    $arguments += "/ConfigurationRepositoryP", "`"$RepositoryPassword`""

    # --- Operation ---
    $artifactPath = $null
    switch ($Operation) {
        "status" {
            $arguments += "/ConfigurationRepositoryReport", "`"$OutputFile`""
            $artifactPath = $OutputFile
            $successMessage = "Repository report written to: $OutputFile"
            $failureMessage = "Repository report failed"
        }
        "dump" {
            $arguments += "/ConfigurationRepositoryDumpCfg", "`"$OutputFile`""
            if ($PSBoundParameters.ContainsKey("Version")) { $arguments += "-v", "$Version" }
            $artifactPath = $OutputFile
            $successMessage = "Repository configuration dumped to: $OutputFile"
            $failureMessage = "Repository dump failed"
        }
        "lock" {
            $arguments += "/ConfigurationRepositoryLock", "-Objects", "`"$objectsFile`""
            $successMessage = "Objects locked for editing"
            $failureMessage = "Lock failed"
        }
        "update" {
            $arguments += "/ConfigurationRepositoryUpdateCfg", "-Objects", "`"$objectsFile`""
            if ($Force) { $arguments += "-force" }
            $successMessage = "Local configuration updated from the repository"
            $failureMessage = "Update from the repository failed"
        }
        "commit" {
            $arguments += "/ConfigurationRepositoryCommit", "-Objects", "`"$objectsFile`""
            $arguments += "-comment", "`"$Comment`""
            if ($KeepLocked) { $arguments += "-keepLocked" }
            if ($Force) { $arguments += "-force" }
            $successMessage = "Objects committed to the repository"
            $failureMessage = "Commit failed"
        }
        "unlock" {
            $arguments += "/ConfigurationRepositoryUnLock", "-Objects", "`"$objectsFile`""
            if ($Force) { $arguments += "-force" }
            $successMessage = "Locks released"
            $failureMessage = "Unlock failed"
        }
        "bind" {
            $arguments += "/ConfigurationRepositoryBindCfg"
            if ($BindAlreadyBoundUser) { $arguments += "-forceBindAlreadyBindedUser" }
            if ($ReplaceLocalConfiguration) { $arguments += "-forceReplaceCfg" }
            $successMessage = "Infobase bound to the repository"
            $failureMessage = "Bind failed"
        }
        "unbind" {
            $arguments += "/ConfigurationRepositoryUnbindCfg"
            if ($Force) { $arguments += "-force" }
            $successMessage = "Infobase unbound from the repository"
            $failureMessage = "Unbind failed"
        }
    }
    if ($Extension) { $arguments += "-Extension", "`"$Extension`"" }

    # --- Output ---
    # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
    # достаться от прошлого прогона.
    $outFile = Join-Path $tempDir "storage_log.txt"
    $resultFile = Join-Path $tempDir "storage_result.txt"
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
        -ArtifactPath $artifactPath `
        -SuccessMessage $successMessage `
        -FailureMessage $failureMessage `
        -Strict:$StrictLog

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
