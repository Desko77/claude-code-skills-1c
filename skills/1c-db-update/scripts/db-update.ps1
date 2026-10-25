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

.PARAMETER AllowProd
    Разрешить изменяющую операцию против базы, помеченной в .v8-project.json как боевая (role: prod)

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
    [switch]$AllowProd,

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

# --- Защита боевой базы (общий блок, версия 2) ---
# База, помеченная в .v8-project.json как боевая (role: prod), отказывает изменяющей
# операции, пока не передан -AllowProd. Отказ стоит одной команды, а неудачная загрузка в
# боевую базу необратима. Проверка идет до запуска платформы; когда файла настроек нет,
# записи базы нет или роль отличается от prod - поведение прежнее.

function Get-InfoBaseStartDir {
    # Провайдер PowerShell читает [ ] в имени каталога как маску и не входит в него:
    # Get-Location тогда указывает не на каталог процесса, и файл настроек не находится.
    try {
        $osDir = [System.IO.Directory]::GetCurrentDirectory()
        if ($osDir) { return $osDir }
    } catch {}
    return (Get-Location).Path
}

function Find-GuardProjectFile {
    param([string]$StartDir)
    # Относительный путь приводится к полному: подъем по строке "build\db" упирается в пустую
    # строку раньше, чем доходит до текущего каталога, и настройки в корне проекта теряются.
    $d = if ([string]::IsNullOrEmpty($StartDir)) {
        Get-InfoBaseStartDir
    } elseif ([System.IO.Path]::IsPathRooted($StartDir)) {
        $StartDir
    } else {
        Join-Path (Get-InfoBaseStartDir) $StartDir
    }
    $d = [System.IO.Path]::GetFullPath($d)
    for ($i = 0; $i -lt 20 -and $d; $i++) {
        $pj = Join-Path $d ".v8-project.json"
        # LiteralPath: квадратные скобки в имени каталога иначе читаются как маска.
        if (Test-Path -LiteralPath $pj) { return $pj }
        $parent = [System.IO.Path]::GetDirectoryName($d)
        if ($parent -eq $d) { break }
        $d = $parent
    }
    return $null
}

# Get-InfoBaseServerKey - ключ сравнения адреса сервера.
#
# Порт кластера по умолчанию 1541 отбрасывается: srv01 и srv01:1541 - одна база.
# Другой порт остается в ключе и отличает базу.
function Get-InfoBaseServerKey {
    param([string]$Value)

    if (-not $Value) { return '' }
    $text = $Value.Trim().ToLowerInvariant()
    $suffix = ':1541'
    if ($text.EndsWith($suffix)) {
        $text = $text.Substring(0, $text.Length - $suffix.Length)
    }
    return $text
}

# Get-InfoBaseRecordKind - вид записи реестра.
#
# Поле type учитывается, когда оно задано (server или file). Иначе серверная запись -
# это пара server и ref, файловая - путь.
function Get-InfoBaseRecordKind {
    param($Db)

    $declared = ("$($Db.type)").Trim().ToLowerInvariant()
    if ($declared -eq 'server' -or $declared -eq 'file') { return $declared }
    if (("$($Db.server)").Trim() -and ("$($Db.ref)").Trim()) { return 'server' }
    if (("$($Db.path)").Trim()) { return 'file' }
    return ''
}

# Get-InfoBaseFinalPath - окончательный путь каталога.
#
# Junction и символическая ссылка приводятся к цели, в том числе в середине пути и когда
# последнего каталога еще нет. Подключенный диск и UNC-путь к тому же каталогу не сводятся.
function Get-InfoBaseFinalPath {
    param([string]$Path)

    if (-not $Path) { return '' }
    $full = $Path
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
    } catch {
        return $Path
    }
    try {
        $rootPath = [System.IO.Path]::GetPathRoot($full)
        if (-not $rootPath) { return $full }
        $rest = $full.Substring($rootPath.Length)
        $current = $rootPath
        foreach ($part in @($rest -split '[\\/]' | Where-Object { $_ })) {
            if ($current.EndsWith('\') -or $current.EndsWith('/')) {
                $next = $current + $part
            } else {
                $next = Join-Path $current $part
            }
            if (-not (Test-Path -LiteralPath $next)) {
                $current = $next
                continue
            }
            $current = $next
            for ($hop = 0; $hop -lt 8; $hop++) {
                try {
                    $item = Get-Item -LiteralPath $next -Force -ErrorAction Stop
                } catch {
                    break
                }
                $reparse = $false
                try {
                    $reparse = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
                } catch {
                    $reparse = $false
                }
                if (-not $reparse) {
                    $current = $item.FullName
                    break
                }
                $target = $item.Target
                if ($target -is [System.Array]) { $target = $target[0] }
                if (-not $target) {
                    $current = $item.FullName
                    break
                }
                $target = "$target".Trim()
                if (-not $target) {
                    $current = $item.FullName
                    break
                }
                if (-not [System.IO.Path]::IsPathRooted($target)) {
                    $parent = [System.IO.Path]::GetDirectoryName($item.FullName)
                    if ($parent) { $target = Join-Path $parent $target }
                }
                try { $target = [System.IO.Path]::GetFullPath($target) } catch {}
                if ($target -eq $next) {
                    $current = $item.FullName
                    break
                }
                $current = $target
                $next = $target
                if (-not (Test-Path -LiteralPath $next)) { break }
            }
        }
        return $current
    } catch {
        return $full
    }
}

# Get-InfoBasePathKey - ключ сравнения путей баз.
#
# Приводит путь к виду, в котором два написания одной базы совпадают: окончательный
# каталог (junction и символическая ссылка), прямые слеши, нижний регистр, без
# завершающего разделителя. Относительный путь достраивается от BaseDir.
# Подключенный диск и UNC-путь к тому же каталогу не сводятся.
#
# Параметры:
#   Value - путь к файловой базе.
#   BaseDir - каталог, от которого достраивается относительный путь.
#
# Возвращает: строку-ключ; пустая строка означает, что путь не задан.
function Get-InfoBasePathKey {
    param([string]$Value, [string]$BaseDir)

    if (-not $Value) { return '' }
    $text = $Value.Trim()
    if (-not $text) { return '' }
    if (-not [System.IO.Path]::IsPathRooted($text) -and $BaseDir) {
        $text = Join-Path $BaseDir $text
    }
    $text = Get-InfoBaseFinalPath -Path $text
    $text = $text -replace '\\', '/'
    $text = $text.TrimEnd('/')
    if (-not $text) { $text = '/' }
    return $text.ToLowerInvariant()
}

# Get-InfoBaseRole - роль целевой базы по настройкам проекта.
#
# Находит ближайший .v8-project.json и в нем запись того же вида, что и цель. Сервер и имя
# вместе - цель серверная, путь в этом запуске не сравнивается. Сервер сравнивается без
# порта 1541. Файловый путь - по окончательному каталогу. Поле type записи учитывается,
# когда оно задано. Сравнение без учета регистра. Читает только имя и роль, остальные
# поля файла не печатает.
#
# Параметры:
#   InfoBasePath - путь к файловой базе (или пустая строка).
#   InfoBaseServer - сервер 1С для серверной базы.
#   InfoBaseRef - имя базы на сервере.
#
# Возвращает: хеш с полями Name (имя записи), Role (роль в нижнем регистре) и ConfigPath
# (путь к файлу настроек). Поля пустые, когда файла нет, запись не найдена или файл не
# разбирается.
function Get-InfoBaseRole {
    param(
        [string]$InfoBasePath,
        [string]$InfoBaseServer,
        [string]$InfoBaseRef
    )

    $state = @{ Name = ''; Role = ''; ConfigPath = '' }
    $startDir = Get-InfoBaseStartDir
    $configPath = Find-GuardProjectFile -StartDir $startDir
    if (-not $configPath) { return $state }
    $state.ConfigPath = $configPath
    try {
        $project = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        # Файл есть, но не разбирается: роль неизвестна. Молчать нельзя - иначе защита не
        # работает, а причина не видна.
        [Console]::Error.WriteLine("[warning] project settings not parsed: $configPath ($($_.Exception.Message))")
        $state.ConfigPath = ''
        return $state
    }
    if (-not $project -or -not $project.databases) { return $state }

    $configDir = Split-Path -Path $configPath -Parent
    $serverKey = Get-InfoBaseServerKey $InfoBaseServer
    $ref = if ($InfoBaseRef) { $InfoBaseRef.Trim().ToLowerInvariant() } else { '' }
    $target = Get-InfoBasePathKey -Value $InfoBasePath -BaseDir $startDir
    # Заданы сервер и имя - цель серверная, даже если рядом передан путь. Как у платформы.
    $serverTarget = [bool]($serverKey -and $ref)

    foreach ($db in @($project.databases)) {
        if (-not $db) { continue }
        $kind = Get-InfoBaseRecordKind -Db $db
        $matched = $false
        if ($serverTarget) {
            if ($kind -eq 'server') {
                $matched = ((Get-InfoBaseServerKey "$($db.server)") -eq $serverKey) -and
                           (("$($db.ref)").Trim().ToLowerInvariant() -eq $ref)
            }
        } elseif ($target -and $kind -eq 'file') {
            $matched = (Get-InfoBasePathKey -Value "$($db.path)" -BaseDir $configDir) -eq $target
        }
        if (-not $matched) { continue }
        if ($db.name) { $state.Name = "$($db.name)" }
        elseif ($db.id) { $state.Name = "$($db.id)" }
        $state.Role = ("$($db.role)").Trim().ToLowerInvariant()
        if ($state.Role -eq 'prod') { return $state }
    }
    return $state
}

# Assert-InfoBaseMutable - отказ изменяющей операции на базе, помеченной боевой.
#
# Ничего не делает, когда передан -AllowProd, когда записи базы нет и когда роль не prod.
# При отказе печатает причину в stderr и завершает процесс кодом 1.
#
# Параметры:
#   InfoBasePath, InfoBaseServer, InfoBaseRef - цель операции, как в параметрах скрипта.
#   AllowProd - явное разрешение работать с боевой базой.
#
# Возвращает: ничего; при отказе управление не возвращается.
function Assert-InfoBaseMutable {
    param(
        [string]$InfoBasePath,
        [string]$InfoBaseServer,
        [string]$InfoBaseRef,
        [switch]$AllowProd
    )

    if ($AllowProd) { return }
    $state = Get-InfoBaseRole -InfoBasePath $InfoBasePath -InfoBaseServer $InfoBaseServer -InfoBaseRef $InfoBaseRef
    if ($state.Role -ne 'prod') { return }
    $name = $state.Name
    if (-not $name) { $name = '<без имени>' }
    [Console]::Error.WriteLine(
        "База '$name' помечена как боевая (role: prod) в $($state.ConfigPath).`n" +
        "Изменяющая операция отменена. Запуск с -AllowProd - только по явной команде пользователя.")
    exit 1
}
# --- Конец общего блока защиты боевой базы ---

# --- Боевая база ---
Assert-InfoBaseMutable -InfoBasePath $InfoBasePath -InfoBaseServer $InfoBaseServer -InfoBaseRef $InfoBaseRef -AllowProd:$AllowProd

# --- Вывод платформы (общий блок, версия 2) ---
# Платформа пишет диагностику в кодировке консоли (866 на русской Windows), утилита
# администрирования и часть сборок - в UTF-8. Байты читаются один раз и декодируются по
# факту: перепутанная кодировка превращает сообщение об ошибке в нечитаемое.
function Read-PlatformText {
    param([string]$Path)
    if (-not $Path -or -not (Test-Path $Path)) { return "" }
    # Файл открывается с разделением записи: процесс, оставленный платформой, может держать
    # его открытым на запись, и ReadAllBytes получил бы отказ в доступе.
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete)
        try {
            $ms = New-Object System.IO.MemoryStream
            $fs.CopyTo($ms)
            $bytes = $ms.ToArray()
        } finally {
            $fs.Dispose()
        }
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
# --- Запуск платформы (общий блок, версия 1) ---
# Платформа 8.5 оставляет после выхода процесс crashpad_handler, который наследует дескрипторы
# запустившего. Start-Process -Wait ждет все дерево потомков, а унаследованный канал вывода
# держит открытым канал вызывающей стороны: скрипт и тот, кто читает его вывод, ждут
# завершения crashpad_handler. Здесь платформа получает ровно три дескриптора - NUL на входе
# и два файла на выходе - и ожидание идет до выхода самого процесса платформы.

# Запускает программу платформы и ждет выхода ее процесса, не потомков.
# Не читает каналы: потоки вывода пишутся в файлы StdoutFile и StderrFile, показ вывода -
# Show-PlatformOutput. ArgumentList склеивается через пробел, как у Start-Process:
# кавычки внутри значений расставляет вызывающий.
# Параметры:
#   FilePath     - путь к 1cv8.exe, ibcmd.exe или иной программе
#   ArgumentList - аргументы командной строки
#   StdoutFile   - файл для стандартного вывода (перезаписывается)
#   StderrFile   - файл для потока ошибок (перезаписывается)
# Возвращает: код возврата процесса.
function Invoke-PlatformProcess {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$StdoutFile,
        [string]$StderrFile
    )
    $argLine = ($ArgumentList | Where-Object { $null -ne $_ -and $_ -ne "" }) -join ' '
    $onWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    if ($onWindows -and -not ('PlatformProcessV1' -as [type])) {
        try {
            Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public static class PlatformProcessV1 {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO {
        public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct STARTUPINFOEX { public STARTUPINFO StartupInfo; public IntPtr lpAttributeList; }
    [StructLayout(LayoutKind.Sequential)]
    struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }
    [StructLayout(LayoutKind.Sequential)]
    struct SECURITY_ATTRIBUTES { public int nLength; public IntPtr lpSecurityDescriptor; public bool bInheritHandle; }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr CreateFile(string name, uint access, uint share, ref SECURITY_ATTRIBUTES sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool UpdateProcThreadAttribute(IntPtr list, int flags, IntPtr attr, IntPtr value, IntPtr size, IntPtr prev, IntPtr retSize);
    [DllImport("kernel32.dll")]
    static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CreateProcess(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit, int flags, IntPtr env, string cwd, ref STARTUPINFOEX si, out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern int WaitForSingleObject(IntPtr h, int ms);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetExitCodeProcess(IntPtr h, out int code);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr h);

    const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000;
    const uint FILE_SHARE_READ = 1, FILE_SHARE_WRITE = 2, FILE_SHARE_DELETE = 4;
    const uint OPEN_EXISTING = 3, CREATE_ALWAYS = 2, FILE_ATTRIBUTE_NORMAL = 0x80;
    const int STARTF_USESTDHANDLES = 0x100;
    const int EXTENDED_STARTUPINFO_PRESENT = 0x80000;
    const int CREATE_NO_WINDOW = 0x8000000;
    static readonly IntPtr INVALID_HANDLE = new IntPtr(-1);
    static readonly IntPtr PROC_THREAD_ATTRIBUTE_HANDLE_LIST = (IntPtr)0x20002;

    static IntPtr Open(string path, bool write, ref SECURITY_ATTRIBUTES sa) {
        var h = CreateFile(path, write ? GENERIC_WRITE : GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, ref sa,
            write ? CREATE_ALWAYS : OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, IntPtr.Zero);
        if (h == INVALID_HANDLE) {
            var e = new Win32Exception();
            throw new Win32Exception(e.NativeErrorCode, e.Message + ": " + path);
        }
        return h;
    }

    public static int Run(string exe, string arguments, string workDir, string stdoutPath, string stderrPath) {
        var sa = new SECURITY_ATTRIBUTES();
        sa.nLength = Marshal.SizeOf(sa);
        sa.bInheritHandle = true;
        IntPtr hIn = IntPtr.Zero, hOut = IntPtr.Zero, hErr = IntPtr.Zero;
        IntPtr attrs = IntPtr.Zero, handles = IntPtr.Zero;
        bool attrsReady = false;
        var pi = new PROCESS_INFORMATION();
        try {
            hIn = Open("NUL", false, ref sa);
            hOut = Open(stdoutPath, true, ref sa);
            hErr = Open(stderrPath, true, ref sa);

            var size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            attrs = Marshal.AllocHGlobal(size);
            if (!InitializeProcThreadAttributeList(attrs, 1, 0, ref size)) throw new Win32Exception();
            attrsReady = true;
            handles = Marshal.AllocHGlobal(3 * IntPtr.Size);
            Marshal.WriteIntPtr(handles, 0, hIn);
            Marshal.WriteIntPtr(handles, IntPtr.Size, hOut);
            Marshal.WriteIntPtr(handles, 2 * IntPtr.Size, hErr);
            if (!UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles,
                (IntPtr)(3 * IntPtr.Size), IntPtr.Zero, IntPtr.Zero)) throw new Win32Exception();

            var si = new STARTUPINFOEX();
            si.StartupInfo.cb = Marshal.SizeOf(si);
            si.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            si.StartupInfo.hStdInput = hIn;
            si.StartupInfo.hStdOutput = hOut;
            si.StartupInfo.hStdError = hErr;
            si.lpAttributeList = attrs;
            var cmd = new StringBuilder("\"" + exe + "\"" + (string.IsNullOrEmpty(arguments) ? "" : " " + arguments));
            if (!CreateProcess(null, cmd, IntPtr.Zero, IntPtr.Zero, true,
                EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW, IntPtr.Zero, workDir, ref si, out pi)) {
                var e = new Win32Exception();
                throw new Win32Exception(e.NativeErrorCode, e.Message.Replace("%1", exe) + ": " + exe);
            }
        } finally {
            foreach (var h in new[] { hIn, hOut, hErr }) if (h != IntPtr.Zero) CloseHandle(h);
            if (attrsReady) DeleteProcThreadAttributeList(attrs);
            if (attrs != IntPtr.Zero) Marshal.FreeHGlobal(attrs);
            if (handles != IntPtr.Zero) Marshal.FreeHGlobal(handles);
        }
        CloseHandle(pi.hThread);
        try {
            WaitForSingleObject(pi.hProcess, -1);
            int code;
            if (!GetExitCodeProcess(pi.hProcess, out code)) throw new Win32Exception();
            return code;
        } finally {
            CloseHandle(pi.hProcess);
        }
    }
}
'@
        } catch { }
    }
    if ($onWindows -and ('PlatformProcessV1' -as [type])) {
        # Рабочий каталог - текущее расположение PowerShell, как у Start-Process: оно может
        # отличаться от каталога процесса после Set-Location.
        $workDir = (Get-Location -PSProvider FileSystem).ProviderPath
        return [PlatformProcessV1]::Run($FilePath, $argLine, $workDir, $StdoutFile, $StderrFile)
    }
    # Без компилятора C# и вне Windows: процесс получает все наследуемые дескрипторы, но
    # ожидание идет до выхода самого процесса, а не всего дерева потомков.
    $startArgs = @{ FilePath = $FilePath; NoNewWindow = $true; PassThru = $true
        RedirectStandardOutput = $StdoutFile; RedirectStandardError = $StderrFile }
    if ($argLine) { $startArgs.ArgumentList = $argLine }
    $proc = Start-Process @startArgs
    $null = $proc.Handle
    $proc.WaitForExit()
    return $proc.ExitCode
}
# --- Конец общего блока запуска платформы ---
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
        $checkStdout = Join-Path $tempDir "check_stdout.txt"
        $checkStderr = Join-Path $tempDir "check_stderr.txt"
        $checkExit = Invoke-PlatformProcess -FilePath $V8Path -ArgumentList $checkArgs `
            -StdoutFile $checkStdout -StderrFile $checkStderr
        Show-PlatformOutput @($checkStdout, $checkStderr)
        $checkLog = $null
        if (Test-Path $checkOut) {
            $checkLog = Get-Content $checkOut -Raw -ErrorAction SilentlyContinue
        }
        # Строгий режим здесь включен всегда, а не по ключу вызова: смысл проверки в том,
        # чтобы остановить обновление. Отказ платформа сообщает строкой журнала при нулевом
        # коде возврата, и без строгости проверка нашла бы несовместимость и пропустила
        # обновление дальше.
        $checkCode = Write-PlatformVerdict -ExitCode $checkExit -ResultFile $checkResult -LogText $checkLog `
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
    $platformStdout = Join-Path $tempDir "platform_stdout.txt"
    $platformStderr = Join-Path $tempDir "platform_stderr.txt"
    $exitCode = Invoke-PlatformProcess -FilePath $V8Path -ArgumentList $arguments `
        -StdoutFile $platformStdout -StderrFile $platformStderr
    Show-PlatformOutput @($platformStdout, $platformStderr)

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
