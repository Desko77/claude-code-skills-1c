# epf-build v1.0 — Build external data processor or report (EPF/ERF) from XML sources
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Сборка внешней обработки/отчёта 1С из XML-исходников

.DESCRIPTION
    Собирает EPF/ERF-файл из XML-исходников с помощью платформы 1С.
    Общий скрипт для epf-build и erf-build.

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

.PARAMETER SourceFile
    Путь к корневому XML-файлу исходников

.PARAMETER OutputFile
    Путь к выходному EPF/ERF-файлу

.EXAMPLE
    .\epf-build.ps1 -InfoBasePath "C:\Bases\MyDB" -SourceFile "src\МояОбработка.xml" -OutputFile "build\МояОбработка.epf"

.EXAMPLE
    .\epf-build.ps1 -InfoBasePath "C:\Bases\MyDB" -SourceFile "src\МойОтчёт.xml" -OutputFile "build\МойОтчёт.erf"
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

    [Parameter(Mandatory=$true)]
    [string]$SourceFile,

    [Parameter(Mandatory=$true)]
    [string]$OutputFile,

    [Parameter(Mandatory=$false)]
    [string]$AdditionalV8Arguments,

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

# --- Дополнительные аргументы платформы (общий блок, версия 1) ---
# Список разделяется запятой, а не пробелом: аргумент платформы несет пробел внутри значения
# (/C "имя значение", путь с пробелом), и разбор по пробелу разорвал бы такой аргумент.
function Split-PlatformArguments {
    param([string]$Raw)
    if ([string]::IsNullOrWhiteSpace($Raw)) { return @() }
    return @($Raw -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
}

# Настройки проекта ищутся вверх по дереву от целевого каталога: скрипт запускают из любого
# места, а файл настроек лежит в корне проекта. Существование каталога не требуется - подъем
# идет по строке пути, а целевого каталога на момент создания базы еще нет.
function Find-V8ProjectFile {
    param([string]$StartDir)
    # Относительный путь приводится к полному: подъем по строке "build\db" упирается в пустую
    # строку раньше, чем доходит до текущего каталога, и настройки в корне проекта теряются.
    $d = if ([string]::IsNullOrEmpty($StartDir)) {
        (Get-Location).Path
    } elseif ([System.IO.Path]::IsPathRooted($StartDir)) {
        $StartDir
    } else {
        Join-Path (Get-Location).Path $StartDir
    }
    $d = [System.IO.Path]::GetFullPath($d)
    for ($i = 0; $i -lt 20 -and $d; $i++) {
        $pj = Join-Path $d ".v8-project.json"
        if (Test-Path $pj) { return $pj }
        $parent = [System.IO.Path]::GetDirectoryName($d)
        if ($parent -eq $d) { break }
        $d = $parent
    }
    return $null
}

function Get-ProjectPlatformArguments {
    param([string]$StartDir, [string]$Key)
    try {
        $pj = Find-V8ProjectFile $StartDir
        if (-not $pj) { return @() }
        $settings = Get-Content $pj -Raw -Encoding UTF8 | ConvertFrom-Json
        $value = $settings.$Key
        if ($null -eq $value) { return @() }
        if ($value -is [string]) { return Split-PlatformArguments $value }
        return @($value | ForEach-Object { [string]$_ } | Where-Object { $_ -ne '' })
    } catch {
        # Непрочитанные настройки не повод отменять запуск: дополнительные аргументы
        # необязательны, а сам файл проверяет и сообщает о поломке отдельный линтер.
        return @()
    }
}

# Аргументы вызова заменяют значение из настроек проекта целиком, а не дополняют его: при
# сложении снять заданный в проекте аргумент было бы нечем.
#
# $null в Explicit означает, что параметр не задавали, - тогда действуют настройки проекта.
# Пустая строка означает заданное пустое значение и снимает аргументы проекта на этот запуск.
function Resolve-PlatformArguments {
    # Тип у Explicit не объявлен намеренно: объявление [string] превращает $null в пустую
    # строку, и отсутствие параметра стало бы неотличимо от заданного пустого значения.
    param($Explicit, [string]$StartDir, [string]$Key)
    if ($null -ne $Explicit) { return Split-PlatformArguments ([string]$Explicit) }
    return Get-ProjectPlatformArguments -StartDir $StartDir -Key $Key
}
# --- Конец общего блока дополнительных аргументов ---

# --- Вывод платформы (общий блок, версия 1) ---
# Платформа пишет диагностику в кодировке консоли (866 на русской Windows), утилита
# администрирования и часть сборок - в UTF-8. Байты читаются один раз и декодируются по
# факту: перепутанная кодировка превращает сообщение об ошибке в нечитаемое.
function Read-PlatformText {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path $Path)) { return "" }
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
    } catch {
        return ""
    }
    if ($bytes.Length -eq 0) { return "" }
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        return [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    }
    try {
        # Строгий декодер бросает исключение на байтах, недопустимых в UTF-8, - это и есть
        # признак однобайтовой кодировки. Нестрогий подставил бы символ замены молча.
        $strict = New-Object System.Text.UTF8Encoding($false, $true)
        return $strict.GetString($bytes)
    } catch {
        return [System.Text.Encoding]::GetEncoding(866).GetString($bytes)
    }
}

# Вывод показывается и при успешном завершении: платформа сообщает предупреждения, не меняя
# код возврата, и потерянное предупреждение обходится дороже лишних строк в протоколе.
function Show-PlatformOutput {
    param([string[]]$Path)
    $chunks = @()
    foreach ($p in $Path) {
        $text = (Read-PlatformText $p).Trim()
        if ($text) { $chunks += $text }
    }
    if ($chunks.Count -eq 0) { return }
    Write-Host "--- Вывод платформы ---"
    foreach ($chunk in $chunks) { Write-Host $chunk }
}
# --- Конец общего блока вывода платформы ---
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

# Каталог поиска настроек проекта - рядом с исходниками обработки. Объявлен до цепочки
# временной базы: аргументы нужны обоим запускам.
$settingsDir = Split-Path $SourceFile -Parent

# Незаданный параметр и заданный пустым - разные случаи: первый оставляет в силе настройки
# проекта, второй снимает их на этот запуск.
$explicitV8Args = if ($PSBoundParameters.ContainsKey('AdditionalV8Arguments')) { $AdditionalV8Arguments } else { $null }

# --- Auto-create stub database if no connection specified ---
$autoCreatedBase = $null
if (-not $InfoBasePath -and (-not $InfoBaseServer -or -not $InfoBaseRef)) {
    $sourceDir = Split-Path $SourceFile -Parent
    $autoBasePath = Join-Path $env:TEMP "epf_stub_db_$(Get-Random)"
    $stubScript = Join-Path $PSScriptRoot "stub-db-create.ps1"
    Write-Host "No database specified. Creating temporary stub database..."
    $stubArgs = "-SourceDir `"$sourceDir`" -V8Path `"$V8Path`" -TempBasePath `"$autoBasePath`""
    # Аргументы разрешаются ДО цепочки: заданные только в настройках проекта иначе не дошли бы
    # до создания временной базы, и она упала бы там же, где нужен лицензионный ключ.
    $resolvedStubArgs = Resolve-PlatformArguments -Explicit $explicitV8Args -StartDir $settingsDir -Key "v8args"
    if ($resolvedStubArgs.Count -gt 0) {
        $stubArgs += " -AdditionalV8Arguments `"$($resolvedStubArgs -join ',')`""
    }
    # Тот же интерпретатор, что запустил этот скрипт: имя powershell.exe выбирает версию 5.1,
    # которая ломается на кириллице в путях и в теле скрипта.
    $hostExe = (Get-Process -Id $PID).Path
    if (-not $hostExe) { $hostExe = "pwsh.exe" }
    $stubProc = Start-Process -FilePath $hostExe -ArgumentList "-NoProfile -File `"$stubScript`" $stubArgs" -NoNewWindow -Wait -PassThru
    if ($stubProc.ExitCode -ne 0) {
        Write-Host "Error: failed to create stub database" -ForegroundColor Red
        exit 1
    }
    $InfoBasePath = $autoBasePath
    $autoCreatedBase = $autoBasePath
}

# --- Validate source file ---
if (-not (Test-Path $SourceFile)) {
    Write-Host "Error: source file not found: $SourceFile" -ForegroundColor Red
    exit 1
}

# --- Ensure output directory exists ---
$outDir = Split-Path $OutputFile -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

# --- Temp dir ---
$tempDir = Join-Path $env:TEMP "epf_build_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # --- Build arguments ---
    $arguments = @("DESIGNER")

    if ($InfoBaseServer -and $InfoBaseRef) {
        $arguments += "/S", "`"$InfoBaseServer/$InfoBaseRef`""
    } else {
        $arguments += "/F", "`"$InfoBasePath`""
    }

    if ($UserName) { $arguments += "/N`"$UserName`"" }
    if ($Password) { $arguments += "/P`"$Password`"" }

    $arguments += "/LoadExternalDataProcessorOrReportFromFiles", "`"$SourceFile`"", "`"$OutputFile`""

    # --- Output ---
    # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
    # достаться от прошлого прогона.
    $outFile = Join-Path $tempDir "build_log.txt"
    $resultFile = Join-Path $tempDir "build_result.txt"
    $arguments += "/Out", "`"$outFile`""
    $arguments += "/DumpResult", "`"$resultFile`""
    $arguments += "/DisableStartupDialogs"
    $arguments += Resolve-PlatformArguments -Explicit $explicitV8Args -StartDir $settingsDir -Key "v8args"

    # --- Execute ---
    # Потоки процесса уходят в файлы: унаследованная консоль отдала бы вывод платформы в
    # кодировке 866 как есть, и кириллица в сообщении об ошибке стала бы нечитаемой.
    $stdoutFile = Join-Path $tempDir "platform_stdout.txt"
    $stderrFile = Join-Path $tempDir "platform_stderr.txt"
    Write-Host "Running: 1cv8.exe $(Hide-PlatformSecret ($arguments -join ' '))"
    $process = Start-Process -FilePath $V8Path -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
    $exitCode = $process.ExitCode
    Show-PlatformOutput @($stdoutFile, $stderrFile)

    # --- Result ---
    $logContent = $null
    if (Test-Path $outFile) {
        $logContent = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
    }

    $exitCode = Write-PlatformVerdict -ExitCode $exitCode -ResultFile $resultFile -LogText $logContent `
        -ArtifactPath $OutputFile `
        -SuccessMessage "Build completed successfully: $OutputFile" `
        -FailureMessage "Error building" `
        -Strict:$StrictLog

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if ($autoCreatedBase -and (Test-Path $autoCreatedBase)) {
        Remove-Item -Path $autoCreatedBase -Recurse -Force -ErrorAction SilentlyContinue
    }
}
