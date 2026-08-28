# db-create v1.0 - Create 1C information base
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Создание информационной базы 1С

.DESCRIPTION
    Создает новую информационную базу 1С (файловую или серверную).
    Поддерживает создание из шаблона и добавление в список баз.

.PARAMETER V8Path
    Путь к каталогу bin платформы или к 1cv8.exe

.PARAMETER InfoBasePath
    Путь к файловой информационной базе

.PARAMETER InfoBaseServer
    Сервер 1С (для серверной базы)

.PARAMETER InfoBaseRef
    Имя базы на сервере

.PARAMETER UseTemplate
    Путь к файлу шаблона (.cf или .dt)

.PARAMETER AddToList
    Добавить в список баз 1С

.PARAMETER ListName
    Имя базы в списке

.EXAMPLE
    .\db-create.ps1 -InfoBasePath "C:\Bases\NewDB"

.EXAMPLE
    .\db-create.ps1 -InfoBaseServer "srv01" -InfoBaseRef "MyApp_Test"

.EXAMPLE
    .\db-create.ps1 -InfoBasePath "C:\Bases\NewDB" -UseTemplate "C:\Templates\config.cf" -AddToList -ListName "Новая база"
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
    [string]$UseTemplate,

    [Parameter(Mandatory=$false)]
    [switch]$AddToList,

    [Parameter(Mandatory=$false)]
    [string]$ListName,

    [Parameter(Mandatory=$false)]
    [string]$AdditionalV8Arguments,

    [Parameter(Mandatory=$false)]
    [string]$AdditionalIbcmdArguments,

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

# --- Validate connection ---
if (-not $InfoBasePath -and (-not $InfoBaseServer -or -not $InfoBaseRef)) {
    Write-Host "Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef" -ForegroundColor Red
    exit 1
}

# --- Validate template ---
if ($UseTemplate -and -not (Test-Path $UseTemplate)) {
    Write-Host "Error: template file not found: $UseTemplate" -ForegroundColor Red
    exit 1
}

# --- Temp dir ---
$tempDir = Join-Path $env:TEMP "db_create_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # --- Build arguments ---
    # Каталог поиска настроек проекта: от места будущей базы вверх по дереву.
    $settingsDir = if ($InfoBasePath) { $InfoBasePath } else { (Get-Location).Path }

    # Утилита администрирования принимает собственный набор ключей и не понимает ни /Out,
    # ни /DumpResult, ни /DisableStartupDialogs - у нее отдельная ветка построения команды.
    $isIbcmd = [System.IO.Path]::GetFileNameWithoutExtension($V8Path) -match '^ibcmd$'

    # Незаданный параметр и заданный пустым - разные случаи: первый оставляет в силе настройки
    # проекта, второй снимает их на этот запуск.
    $explicitV8Args = if ($PSBoundParameters.ContainsKey('AdditionalV8Arguments')) { $AdditionalV8Arguments } else { $null }
    $explicitIbcmdArgs = if ($PSBoundParameters.ContainsKey('AdditionalIbcmdArguments')) { $AdditionalIbcmdArguments } else { $null }

    # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
    # достаться от прошлого прогона. Объявлены до ветвления: ветка утилиты администрирования
    # их не создает, а проверка по неинициализированному пути бросает исключение.
    $outFile = Join-Path $tempDir "create_log.txt"
    $resultFile = Join-Path $tempDir "create_result.txt"

    if ($isIbcmd) {
        if ($InfoBaseServer -and $InfoBaseRef) {
            [Console]::Error.WriteLine("Error: создание серверной базы через ibcmd этим скриптом не поддерживается")
            exit 1
        }
        # Ключи платформы утилита администрирования не понимает. Молча их отбросить нельзя:
        # вызывающий считает, что аргумент действует, и получит поведение, которого не просил.
        # Ключи платформы утилита администрирования не понимает, а шаблон и регистрацию в
        # списке баз она делает другими командами. Молчаливое игнорирование дало бы пустую
        # незарегистрированную базу и отчет об успехе.
        if ($UseTemplate) {
            [Console]::Error.WriteLine("Error: -UseTemplate не поддерживается движком ibcmd")
            exit 1
        }
        if ($AddToList) {
            [Console]::Error.WriteLine("Error: -AddToList не поддерживается движком ibcmd")
            exit 1
        }
        if (Split-PlatformArguments $AdditionalV8Arguments) {
            [Console]::Error.WriteLine("Error: -AdditionalV8Arguments относится к 1cv8.exe, а выбран движок ibcmd. Используйте -AdditionalIbcmdArguments")
            exit 1
        }
        $extra = Resolve-PlatformArguments -Explicit $explicitIbcmdArgs -StartDir $settingsDir -Key "ibcmdargs"
        # Позиционный токен встает в строку как часть команды: "infobase create config" -
        # это уже другая команда, а не создание базы с дополнительным ключом.
        $positional = @($extra | Where-Object { -not $_.StartsWith("-") })
        if ($positional.Count -gt 0) {
            [Console]::Error.WriteLine("Error: позиционный токен в -AdditionalIbcmdArguments меняет команду ibcmd: $($positional -join ', ')")
            exit 1
        }
        $arguments = @("infobase", "create", "--db-path=`"$InfoBasePath`"")
        $arguments += $extra
    } else {

    $arguments = @("CREATEINFOBASE")

    if ($InfoBaseServer -and $InfoBaseRef) {
        $arguments += "Srvr=`"$InfoBaseServer`";Ref=`"$InfoBaseRef`""
    } else {
        $arguments += "File=`"$InfoBasePath`""
    }

    # --- Template ---
    if ($UseTemplate) {
        $arguments += "/UseTemplate", "`"$UseTemplate`""
    }

    # --- Add to list ---
    if ($AddToList) {
        if ($ListName) {
            $arguments += "/AddToList", "`"$ListName`""
        } else {
            $arguments += "/AddToList"
        }
    }

    # --- Output ---
    $arguments += "/Out", "`"$outFile`""
    $arguments += "/DumpResult", "`"$resultFile`""
    $arguments += "/DisableStartupDialogs"
    $arguments += Resolve-PlatformArguments -Explicit $explicitV8Args -StartDir $settingsDir -Key "v8args"

    }

    # --- Execute ---
    # Потоки процесса уходят в файлы: унаследованная консоль отдала бы вывод платформы в
    # кодировке 866 как есть, и кириллица в сообщении об ошибке стала бы нечитаемой.
    $stdoutFile = Join-Path $tempDir "platform_stdout.txt"
    $stderrFile = Join-Path $tempDir "platform_stderr.txt"
    Write-Host "Running: $([System.IO.Path]::GetFileName($V8Path)) $(Hide-PlatformSecret ($arguments -join ' '))"
    $process = Start-Process -FilePath $V8Path -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
    $exitCode = $process.ExitCode
    Show-PlatformOutput @($stdoutFile, $stderrFile)

    # --- Result ---
    $logContent = $null
    if (Test-Path $outFile) {
        $logContent = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
    }

    # Постусловие есть только у файловой базы: серверная база файлом на диске не представлена.
    $artifactPath = $null
    if ($InfoBaseServer -and $InfoBaseRef) {
        $successMessage = "Information base created successfully: $InfoBaseServer/$InfoBaseRef"
    } else {
        $successMessage = "Information base created successfully: $InfoBasePath"
        $artifactPath = Join-Path $InfoBasePath "1Cv8.1CD"
    }

    # У утилиты администрирования нет ни файла результата, ни лога платформы: вердикт
    # опирается на код возврата и постусловие.
    if ($isIbcmd) { $resultFile = $null; $logContent = $null }
    $exitCode = Write-PlatformVerdict -ExitCode $exitCode -ResultFile $resultFile -LogText $logContent `
        -ArtifactPath $artifactPath `
        -SuccessMessage $successMessage `
        -FailureMessage "Error creating information base" `
        -Strict:$StrictLog

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
