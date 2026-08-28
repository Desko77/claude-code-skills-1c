# db-run v1.0 - Launch 1C:Enterprise
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Запуск 1С:Предприятие

.DESCRIPTION
    Запускает информационную базу в режиме 1С:Предприятие (пользовательский режим).
    Запуск в фоне - не ждет завершения процесса.

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

.PARAMETER Execute
    Путь к внешней обработке для запуска

.PARAMETER CParam
    Параметр запуска (/C)

.PARAMETER URL
    Навигационная ссылка (e1cib/...)

.EXAMPLE
    .\db-run.ps1 -InfoBasePath "C:\Bases\MyDB"

.EXAMPLE
    .\db-run.ps1 -InfoBasePath "C:\Bases\MyDB" -Execute "C:\epf\МояОбработка.epf"

.EXAMPLE
    .\db-run.ps1 -InfoBasePath "C:\Bases\MyDB" -CParam "ЗапуститьОбновление"
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
    [string]$Execute,

    [Parameter(Mandatory=$false)]
    [string]$CParam,

    [Parameter(Mandatory=$false)]
    [string]$URL,

    [Parameter(Mandatory=$false)]
    [string]$AdditionalV8Arguments,

    [Parameter(Mandatory=$false)]
    [int]$StartupCheckSeconds = 3
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

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

# Пароль приходит ключом /P и уходит в протокол вместе со строкой запуска.
function Hide-RunSecret {
    param([string]$Text)
    if (-not $Text) { return $Text }
    $masked = $Text -replace '(?:^|(?<=\s))(/P)"[^"]*"', '$1"***"'
    return $masked -replace '(?:^|(?<=\s))(/P)([^\s"]\S*)', '$1***'
}

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

# --- Build arguments as single string ---
# Note: Start-Process without -NoNewWindow uses ShellExecute.
# Passing ArgumentList as array can corrupt Cyrillic when ShellExecute
# re-joins elements. Single string avoids this.
$argString = "ENTERPRISE"

if ($InfoBaseServer -and $InfoBaseRef) {
    $argString += " /S `"$InfoBaseServer/$InfoBaseRef`""
} else {
    $argString += " /F `"$InfoBasePath`""
}

if ($UserName) { $argString += " /N`"$UserName`"" }
if ($Password) { $argString += " /P`"$Password`"" }

# --- Optional params ---
if ($Execute) {
    $ext = [System.IO.Path]::GetExtension($Execute).ToLower()
    if ($ext -eq ".erf") {
        Write-Host "[WARN] /Execute не поддерживает ERF-файлы (внешние отчеты)." -ForegroundColor Yellow
        Write-Host "       Откройте отчет через 'Файл -> Открыть': $Execute" -ForegroundColor Yellow
        Write-Host "       Запускаю базу без /Execute." -ForegroundColor Yellow
        $Execute = ""
    }
}
if ($Execute) {
    $argString += " /Execute `"$Execute`""
}
if ($CParam) {
    $argString += " /C `"$CParam`""
}
if ($URL) {
    $argString += " /URL `"$URL`""
}

$argString += " /DisableStartupDialogs"

$settingsDir = if ($InfoBasePath) { $InfoBasePath } else { (Get-Location).Path }
$explicitV8Args = if ($PSBoundParameters.ContainsKey('AdditionalV8Arguments')) { $AdditionalV8Arguments } else { $null }
foreach ($extra in (Resolve-PlatformArguments -Explicit $explicitV8Args -StartDir $settingsDir -Key "v8args")) {
    $argString += " $extra"
}

# --- Execute (background, no wait) ---
Write-Host "Running: 1cv8.exe $(Hide-RunSecret $argString)"
$process = Start-Process -FilePath $V8Path -ArgumentList $argString -PassThru
if (-not $process) {
    Write-Host "Error: не удалось запустить $V8Path" -ForegroundColor Red
    exit 1
}

# Контрольное окно: платформа с отвергнутыми параметрами завершается почти сразу, и
# сообщение о запуске было бы ложным. Ожидание прерывается, как только процесс завершился,
# поэтому полный интервал ждет только успешный запуск. Длину окна задает -StartupCheckSeconds:
# на загруженной машине трех секунд не хватает даже на старт процесса.
$null = $process.WaitForExit($StartupCheckSeconds * 1000)
if ($process.HasExited -and $process.ExitCode -ne 0) {
    Write-Host "Error: платформа завершилась сразу после запуска, код возврата $($process.ExitCode)" -ForegroundColor Red
    exit 1
}

Write-Host "1C:Enterprise launched" -ForegroundColor Green
