# db-load-dt v1.0 - Restore 1C infobase from DT file
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Восстановление информационной базы 1С из DT-файла

.DESCRIPTION
    Загружает DT-файл в информационную базу. Текущее содержимое базы
    (данные, конфигурация, пользователи) полностью замещается.
    Требует монопольного доступа к базе.

.PARAMETER V8Path
    Путь к каталогу bin платформы или к 1cv8.exe

.PARAMETER InfoBasePath
    Путь к файловой информационной базе

.PARAMETER InfoBaseServer
    Сервер 1С (для серверной базы)

.PARAMETER InfoBaseRef
    Имя базы на сервере

.PARAMETER UserName
    Имя пользователя 1С (текущей базы, до восстановления)

.PARAMETER Password
    Пароль пользователя

.PARAMETER InputFile
    Путь к DT-файлу для загрузки

.EXAMPLE
    .\db-load-dt.ps1 -InfoBasePath "C:\Bases\MyDB" -InputFile "C:\backup\MyDB.dt"

.EXAMPLE
    .\db-load-dt.ps1 -InfoBaseServer "srv01" -InfoBaseRef "MyApp_Test" -UserName "Admin" -InputFile "MyApp_Dev.dt"
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
    [string]$InputFile,

    [Parameter(Mandatory=$false)]
    [int]$JobsCount = 0,

    [Parameter(Mandatory=$false)]
    [string]$UnlockCode
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

# --- Validate input file ---
if (-not (Test-Path $InputFile)) {
    Write-Host "Error: DT file not found: $InputFile" -ForegroundColor Red
    exit 1
}

# --- Temp dir ---
$tempDir = Join-Path $env:TEMP "db_load_dt_$(Get-Random)"
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

    if ($UnlockCode) { $arguments += "/UC`"$UnlockCode`"" }

    $arguments += "/RestoreIB", "`"$InputFile`""
    if ($JobsCount -gt 0) { $arguments += "-JobsCount", "$JobsCount" }

    # --- Output ---
    $outFile = Join-Path $tempDir "load_dt_log.txt"
    $arguments += "/Out", "`"$outFile`""
    $arguments += "/DisableStartupDialogs"

    # --- Execute ---
    $display = ($arguments | ForEach-Object {
        if ($_ -like '/P"*') { '/P"***"' } elseif ($_ -like '/UC"*') { '/UC"***"' } else { $_ }
    }) -join ' '
    Write-Host "Running: 1cv8.exe $display"
    $process = Start-Process -FilePath $V8Path -ArgumentList $arguments -NoNewWindow -Wait -PassThru
    $exitCode = $process.ExitCode

    # --- Result ---
    if ($exitCode -eq 0) {
        Write-Host "Infobase restored successfully from: $InputFile" -ForegroundColor Green
    } else {
        Write-Host "Error restoring infobase (code: $exitCode). Check for active sessions - restore needs exclusive access." -ForegroundColor Red
    }

    if (Test-Path $outFile) {
        $logContent = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
        if ($logContent) {
            Write-Host "--- Log ---"
            Write-Host $logContent
            Write-Host "--- End ---"
        }
    }

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
