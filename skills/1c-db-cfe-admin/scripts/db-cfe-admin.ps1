# db-cfe-admin v1.0 - Manage configuration extensions in a 1C infobase via ibcmd
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Управление расширениями конфигурации в информационной базе через ibcmd

.DESCRIPTION
    Список расширений, проверка применимости, изменение свойств и удаление.
    Изменяющие операции отказывают на базе с ролью prod, пока не передан -AllowProd.

.PARAMETER Operation
    list, check, set-properties или delete

.PARAMETER V8Path
    Каталог bin платформы, путь к ibcmd.exe или к 1cv8.exe

.PARAMETER InfoBasePath
    Путь к файловой информационной базе

.PARAMETER InfoBaseServer
    Сервер СУБД (ключ ibcmd --db-server). Вместе с -InfoBaseRef задает серверную цель

.PARAMETER InfoBaseRef
    Имя базы СУБД (ключ ibcmd --db-name)

.PARAMETER AllowProd
    Разрешить изменяющую операцию против базы, помеченной как боевая (role: prod)

.PARAMETER UserName
    Имя пользователя информационной базы

.PARAMETER Password
    Пароль пользователя

.PARAMETER DataPath
    Каталог данных автономного сервера (ключ --data). Без него ibcmd берет каталог по умолчанию

.PARAMETER Dbms
    Тип СУБД: MSSQLServer, PostgreSQL, IBMDB2, OracleDatabase

.PARAMETER WhatIf
    Напечатать команду ibcmd и не запускать ее

.PARAMETER Name
    Имя расширения

.PARAMETER All
    Удалить все расширения (только delete)

.PARAMETER Active
    Активность: yes или no

.PARAMETER SafeMode
    Безопасный режим: yes или no

.PARAMETER SecurityProfileName
    Имя профиля безопасности

.PARAMETER UnsafeActionProtection
    Защита от опасных действий: yes или no

.PARAMETER UsedInDistributedInfobase
    Использование в распределенной информационной базе: yes или no

.PARAMETER Scope
    Область действия: infobase или data-separation

.EXAMPLE
    .\db-cfe-admin.ps1 list -InfoBasePath "C:\Bases\MyDB"

.EXAMPLE
    .\db-cfe-admin.ps1 set-properties -InfoBasePath "C:\Bases\MyDB" -Name "DemoExt" -SafeMode no -Active yes
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('list', 'check', 'set-properties', 'delete')]
    [string]$Operation,

    [string]$V8Path,

    [string]$InfoBasePath,

    [string]$InfoBaseServer,

    [string]$InfoBaseRef,

    [switch]$AllowProd,

    [string]$UserName,

    [string]$Password,

    [string]$DataPath,

    [string]$Dbms,

    [Alias('DryRun', 'dry-run')]
    [switch]$WhatIf,

    [string]$Name,

    [switch]$All,

    [string]$Active,

    [string]$SafeMode,

    [string]$SecurityProfileName,

    [string]$UnsafeActionProtection,

    [string]$UsedInDistributedInfobase,

    [string]$Scope
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

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

# Fail-Ibcmd - сообщение об ошибке параметров и завершение кодом 1.
#
# Параметры: Message - текст без префикса Error.
# Возвращает: управление не возвращается.
function Fail-Ibcmd {
    param([string]$Message)
    [Console]::Error.WriteLine("Error: $Message")
    exit 1
}

# Resolve-IbcmdPath - путь к ibcmd.
#
# Пустой аргумент - поиск ibcmd.exe в каталогах bin установленных платформ.
# Каталог - ibcmd.exe внутри него. Файл 1cv8.exe - ibcmd.exe в том же каталоге.
# Иной существующий файл используется как есть.
#
# Параметры: Path - значение -V8Path.
# Возвращает: путь к исполняемому файлу; при отсутствии завершает процесс кодом 1.
function Resolve-IbcmdPath {
    param([string]$Path)
    if (-not $Path) {
        $found = Get-ChildItem "C:\Program Files\1cv8\*\bin\ibcmd.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName | Select-Object -Last 1
        if (-not $found) { Fail-Ibcmd "ibcmd.exe not found. Specify -V8Path" }
        return $found.FullName
    }
    if (Test-Path -LiteralPath $Path -PathType Container) {
        $candidate = Join-Path $Path "ibcmd.exe"
    } else {
        $base = [System.IO.Path]::GetFileName($Path).ToLowerInvariant()
        if ($base -eq '1cv8.exe' -or $base -eq '1cv8') {
            $candidate = Join-Path ([System.IO.Path]::GetDirectoryName($Path)) "ibcmd.exe"
        } else {
            $candidate = $Path
        }
    }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        Fail-Ibcmd "ibcmd.exe not found at $candidate"
    }
    return $candidate
}

# ConvertTo-IbcmdYesNo - флаг свойства в виде yes или no.
#
# Пустая строка означает, что свойство не задавали.
#
# Параметры: Label - имя параметра скрипта; Value - сырое значение.
# Возвращает: yes, no или пустую строку. Недопустимое значение завершает процесс кодом 1.
function ConvertTo-IbcmdYesNo {
    param([string]$Label, [string]$Value)
    if (-not $Value -or -not $Value.Trim()) { return '' }
    $text = $Value.Trim().ToLowerInvariant()
    if ($text -ne 'yes' -and $text -ne 'no') {
        Fail-Ibcmd "$Label accepts yes or no, got: $Value"
    }
    return $text
}

# ConvertTo-IbcmdScope - область действия: infobase или data-separation.
#
# Параметры: Value - сырое значение -Scope.
# Возвращает: каноническое значение или пустую строку. Иное завершает процесс кодом 1.
function ConvertTo-IbcmdScope {
    param([string]$Value)
    if (-not $Value -or -not $Value.Trim()) { return '' }
    $text = $Value.Trim().ToLowerInvariant()
    if ($text -ne 'infobase' -and $text -ne 'data-separation') {
        Fail-Ibcmd "-Scope accepts infobase or data-separation, got: $Value"
    }
    return $text
}

# ConvertTo-IbcmdDbms - тип СУБД в написании справки ibcmd.
#
# Параметры: Value - сырое значение -Dbms.
# Возвращает: MSSQLServer, PostgreSQL, IBMDB2, OracleDatabase или пустую строку.
function ConvertTo-IbcmdDbms {
    param([string]$Value)
    if (-not $Value -or -not $Value.Trim()) { return '' }
    $text = $Value.Trim()
    foreach ($kind in @('MSSQLServer', 'PostgreSQL', 'IBMDB2', 'OracleDatabase')) {
        if ($text.ToLowerInvariant() -eq $kind.ToLowerInvariant()) { return $kind }
    }
    Fail-Ibcmd "-Dbms accepts MSSQLServer, PostgreSQL, IBMDB2, OracleDatabase, got: $Value"
}

# Get-IbcmdArguments - аргументы ibcmd без пути к exe.
#
# Порядок фиксирован: оба порта печатают одну и ту же строку.
# Заданные сервер и имя - цель серверная, путь в команду не попадает.
#
# Возвращает: массив строк-аргументов.
function Get-IbcmdArguments {
    param(
        [string]$Op,
        [string]$ExtName,
        [bool]$AllExtensions,
        [hashtable]$Properties,
        [string]$ExtScope,
        [string]$BasePath,
        [string]$BaseServer,
        [string]$BaseRef,
        [string]$DbmsKind,
        [string]$ServerData,
        [string]$User,
        [string]$Pwd
    )
    $command = @()
    if ($Op -eq 'check') {
        $command = @('infobase', 'config', 'check', "--extension=$ExtName")
    } elseif ($Op -eq 'list') {
        $command = @('infobase', 'config', 'extension', 'list')
    } elseif ($Op -eq 'set-properties') {
        $command = @('infobase', 'config', 'extension', 'update', "--name=$ExtName")
        foreach ($key in @(
            '--active',
            '--safe-mode',
            '--security-profile-name',
            '--unsafe-action-protection',
            '--used-in-distributed-infobase'
        )) {
            if ($Properties.ContainsKey($key) -and $Properties[$key]) {
                $command += "$key=$($Properties[$key])"
            }
        }
        if ($ExtScope) { $command += "--scope=$ExtScope" }
    } elseif ($Op -eq 'delete') {
        $command = @('infobase', 'config', 'extension', 'delete')
        if ($AllExtensions) { $command += '--all' } else { $command += "--name=$ExtName" }
    } else {
        Fail-Ibcmd "unknown operation: $Op"
    }

    $serverTarget = [bool](("$BaseServer".Trim()) -and ("$BaseRef".Trim()))
    if ($serverTarget) {
        $command += "--db-server=$BaseServer"
        $command += "--db-name=$BaseRef"
        if ($DbmsKind) { $command += "--dbms=$DbmsKind" }
    } else {
        $command += "--db-path=$BasePath"
    }
    if ($ServerData) { $command += "--data=$ServerData" }
    if ($User) { $command += "--user=$User" }
    if ($Pwd) { $command += "--password=$Pwd" }
    return $command
}

# Format-IbcmdCommand - строка команды ibcmd для печати.
#
# Значение с пробелом берется в кавычки. Пароль заменяется на ***.
#
# Параметры: Argument - массив аргументов без exe.
# Возвращает: строку, начинающуюся с ibcmd.
function Format-IbcmdCommand {
    param([string[]]$Argument)
    $shown = @()
    foreach ($arg in $Argument) {
        if ($arg.StartsWith('--password=') -or $arg.StartsWith('--db-pwd=')) {
            $shown += ($arg.Split('=', 2)[0] + '=***')
            continue
        }
        if ($arg -match '\s' -and $arg.Contains('=')) {
            $pair = $arg.Split('=', 2)
            $shown += ('{0}="{1}"' -f $pair[0], $pair[1])
            continue
        }
        $shown += $arg
    }
    return 'ibcmd ' + ($shown -join ' ')
}

# Invoke-Ibcmd - запуск ibcmd и показ его вывода.
#
# Параметры: Exe - путь к ibcmd; Argument - аргументы без exe.
# Возвращает: хеш Code (код возврата) и HasOutput (был ли непустой вывод).
function Invoke-Ibcmd {
    param([string]$Exe, [string[]]$Argument)
    $tempDir = Join-Path $env:TEMP ("db_cfe_admin_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $stdoutFile = Join-Path $tempDir "stdout.txt"
    $stderrFile = Join-Path $tempDir "stderr.txt"
    try {
        $exitCode = Invoke-PlatformProcess -FilePath $Exe -ArgumentList $Argument `
            -StdoutFile $stdoutFile -StderrFile $stderrFile
        $hasOutput = [bool]((Read-PlatformText $stdoutFile).Trim() -or (Read-PlatformText $stderrFile).Trim())
        Show-PlatformOutput @($stdoutFile, $stderrFile)
        $code = if ($null -eq $exitCode) { 1 } else { $exitCode }
        return @{ Code = $code; HasOutput = $hasOutput }
    } finally {
        if (Test-Path -LiteralPath $tempDir) {
            Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$serverText = "$InfoBaseServer".Trim()
$refText = "$InfoBaseRef".Trim()
$pathText = "$InfoBasePath".Trim()
$serverTarget = [bool]($serverText -and $refText)
if (-not $serverTarget -and -not $pathText) {
    Fail-Ibcmd "specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef"
}
$dbmsKind = ConvertTo-IbcmdDbms $Dbms
if ($dbmsKind -and -not $serverTarget) {
    Fail-Ibcmd "-Dbms requires -InfoBaseServer and -InfoBaseRef"
}

$extName = if ($Name) { $Name.Trim() } else { '' }
if ($All -and $Operation -ne 'delete') { Fail-Ibcmd "-All is valid only for delete" }
if ($Operation -eq 'list' -and ($extName -or $All)) { Fail-Ibcmd "list does not take -Name or -All" }
if ($Operation -eq 'check' -and -not $extName) { Fail-Ibcmd "check requires -Name" }
if ($Operation -eq 'set-properties' -and -not $extName) { Fail-Ibcmd "set-properties requires -Name" }
if ($Operation -eq 'delete' -and $All -and $extName) { Fail-Ibcmd "delete accepts either -Name or -All" }
if ($Operation -eq 'delete' -and -not $All -and -not $extName) { Fail-Ibcmd "delete requires -Name or -All" }

$properties = @{}
$activeValue = ConvertTo-IbcmdYesNo '-Active' $Active
if ($activeValue) { $properties['--active'] = $activeValue }
$safeValue = ConvertTo-IbcmdYesNo '-SafeMode' $SafeMode
if ($safeValue) { $properties['--safe-mode'] = $safeValue }
$unsafeValue = ConvertTo-IbcmdYesNo '-UnsafeActionProtection' $UnsafeActionProtection
if ($unsafeValue) { $properties['--unsafe-action-protection'] = $unsafeValue }
$distributedValue = ConvertTo-IbcmdYesNo '-UsedInDistributedInfobase' $UsedInDistributedInfobase
if ($distributedValue) { $properties['--used-in-distributed-infobase'] = $distributedValue }
if ($SecurityProfileName -and $SecurityProfileName.Trim()) {
    $properties['--security-profile-name'] = $SecurityProfileName.Trim()
}
$extScope = ConvertTo-IbcmdScope $Scope
if ($Operation -eq 'set-properties' -and $properties.Count -eq 0 -and -not $extScope) {
    Fail-Ibcmd "set-properties requires at least one property"
}
if ($Operation -ne 'set-properties' -and ($properties.Count -gt 0 -or $extScope)) {
    Fail-Ibcmd "property parameters are valid only for set-properties"
}

if ($Operation -eq 'set-properties' -or $Operation -eq 'delete') {
    Assert-InfoBaseMutable -InfoBasePath $InfoBasePath -InfoBaseServer $InfoBaseServer `
        -InfoBaseRef $InfoBaseRef -AllowProd:$AllowProd
}

$arguments = Get-IbcmdArguments -Op $Operation -ExtName $extName -AllExtensions ([bool]$All) `
    -Properties $properties -ExtScope $extScope -BasePath $InfoBasePath -BaseServer $InfoBaseServer `
    -BaseRef $InfoBaseRef -DbmsKind $dbmsKind -ServerData $DataPath -User $UserName -Pwd $Password
$command = Format-IbcmdCommand -Argument $arguments
if ($WhatIf) {
    Write-Host $command
    exit 0
}

$exe = Resolve-IbcmdPath $V8Path
Write-Host "Running: $command"
$result = Invoke-Ibcmd -Exe $exe -Argument $arguments
if ($result.Code -ne 0) {
    [Console]::Error.WriteLine("Error: ibcmd finished with code $($result.Code)")
    exit 1
}

if ($Operation -eq 'list') {
    if (-not $result.HasOutput) { Write-Host "Расширений нет" }
    Write-Host "Список расширений получен"
} elseif ($Operation -eq 'check') {
    Write-Host "Проверка расширения завершена: $extName"
} elseif ($Operation -eq 'set-properties') {
    Write-Host "Свойства расширения обновлены: $extName"
} else {
    $target = if ($All) { 'все' } else { $extName }
    Write-Host "Расширение удалено: $target"
}
exit 0
