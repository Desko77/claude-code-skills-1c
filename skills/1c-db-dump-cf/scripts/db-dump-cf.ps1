# db-dump-cf v1.0 - Dump 1C configuration to CF file
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Выгрузка конфигурации 1С в CF-файл

.DESCRIPTION
    Выгружает конфигурацию информационной базы в бинарный CF-файл.
    Поддерживает выгрузку расширений.

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

.PARAMETER OutputFile
    Путь к выходному CF-файлу

.PARAMETER Extension
    Имя расширения для выгрузки

.PARAMETER AllExtensions
    Выгрузить все расширения

.EXAMPLE
    .\db-dump-cf.ps1 -InfoBasePath "C:\Bases\MyDB" -OutputFile "config.cf"

.EXAMPLE
    .\db-dump-cf.ps1 -InfoBasePath "C:\Bases\MyDB" -OutputFile "ext.cfe" -Extension "МоеРасширение"
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
    [string]$OutputFile,

    [Parameter(Mandatory=$false)]
    [string]$Extension,

    [Parameter(Mandatory=$false)]
    [switch]$AllExtensions,

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

# --- Ensure output directory exists ---
$outDir = Split-Path $OutputFile -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

# --- Temp dir ---
$tempDir = Join-Path $env:TEMP "db_dump_cf_$(Get-Random)"
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

    $arguments += "/DumpCfg", "`"$OutputFile`""

    # --- Extensions ---
    if ($Extension) {
        $arguments += "-Extension", "`"$Extension`""
    } elseif ($AllExtensions) {
        $arguments += "-AllExtensions"
    }

    # --- Output ---
    # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
    # достаться от прошлого прогона.
    $outFile = Join-Path $tempDir "dump_cf_log.txt"
    $resultFile = Join-Path $tempDir "dump_cf_result.txt"
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
        -ArtifactPath $OutputFile `
        -SuccessMessage "Configuration dumped successfully to: $OutputFile" `
        -FailureMessage "Error dumping configuration" `
        -Strict:$StrictLog

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
