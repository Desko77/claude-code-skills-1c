# db-load-git v1.3 - Load Git changes into 1C database
# Source: https://github.com/Desko77/claude-code-skills-1c
<#
.SYNOPSIS
    Загрузка изменений из Git в базу 1С

.DESCRIPTION
    Определяет измененные файлы конфигурации по данным Git и выполняет
    частичную загрузку в информационную базу.

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

.PARAMETER ConfigDir
    Каталог XML-выгрузки конфигурации (git-репозиторий)

.PARAMETER Source
    Источник изменений: All, Staged, Unstaged, Commit (по умолчанию All)

.PARAMETER CommitRange
    Диапазон коммитов (для Source=Commit), напр. HEAD~3..HEAD

.PARAMETER Extension
    Имя расширения для загрузки

.PARAMETER AllExtensions
    Загрузить все расширения

.PARAMETER Format
    Формат файлов: Hierarchical или Plain (по умолчанию Hierarchical)

.PARAMETER DryRun
    Только показать что будет загружено (без загрузки)

.EXAMPLE
    .\db-load-git.ps1 -InfoBasePath "C:\Bases\MyDB" -ConfigDir "C:\src" -Source All

.EXAMPLE
    .\db-load-git.ps1 -InfoBasePath "C:\Bases\MyDB" -ConfigDir "C:\src" -Source Commit -CommitRange "HEAD~3..HEAD"

.EXAMPLE
    .\db-load-git.ps1 -InfoBasePath "C:\Bases\MyDB" -ConfigDir "C:\src" -DryRun
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

    [Parameter(Mandatory=$true)]
    [string]$ConfigDir,

    [Parameter(Mandatory=$false)]
    [ValidateSet("All", "Staged", "Unstaged", "Commit")]
    [string]$Source = "All",

    [Parameter(Mandatory=$false)]
    [string]$CommitRange,

    [Parameter(Mandatory=$false)]
    [string]$Extension,

    [Parameter(Mandatory=$false)]
    [switch]$AllExtensions,

    [Parameter(Mandatory=$false)]
    [ValidateSet("Hierarchical", "Plain")]
    [string]$Format = "Hierarchical",

    [Parameter(Mandatory=$false)]
    [switch]$DryRun,

    [Parameter(Mandatory=$false)]
    [switch]$UpdateDB,

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

# --- Защита боевой базы (общий блок, версия 1) ---
# База, помеченная в .v8-project.json как боевая (role: prod), отказывает изменяющей
# операции, пока не передан -AllowProd. Отказ стоит одной команды, а неудачная загрузка в
# боевую базу необратима. Проверка идет до запуска платформы; когда файла настроек нет,
# записи базы нет или роль отличается от prod - поведение прежнее.

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

# Get-InfoBasePathKey - ключ сравнения путей баз.
#
# Приводит путь к виду, в котором два написания одной базы совпадают: полный путь, прямые
# слеши, нижний регистр, без завершающего разделителя. Относительный путь достраивается от
# BaseDir. Существования каталога не проверяет.
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
    try {
        $text = [System.IO.Path]::GetFullPath($text)
    } catch {
        # Путь со символом, который .NET не разбирает: сравниваем написание как есть.
    }
    $text = $text -replace '\\', '/'
    $text = $text.TrimEnd('/')
    if (-not $text) { $text = '/' }
    return $text.ToLowerInvariant()
}

# Get-InfoBaseRole - роль целевой базы по настройкам проекта.
#
# Находит ближайший .v8-project.json и в нем запись, совпадающую с целью: серверная база - по
# server и ref, файловая - по пути. Сравнение без учета регистра. Читает только имя и роль,
# остальные поля файла не печатает.
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
    $startDir = (Get-Location).Path
    $configPath = Find-V8ProjectFile -StartDir $startDir
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
    $server = if ($InfoBaseServer) { $InfoBaseServer.Trim().ToLowerInvariant() } else { '' }
    $ref = if ($InfoBaseRef) { $InfoBaseRef.Trim().ToLowerInvariant() } else { '' }
    $target = Get-InfoBasePathKey -Value $InfoBasePath -BaseDir $startDir

    foreach ($db in @($project.databases)) {
        if (-not $db) { continue }
        # Приоритет тот же, что у платформы: задана пара сервер и имя - целимся в серверную
        # базу, иначе в файловую.
        $matched = $false
        if ($server -and $ref -and $db.server -and $db.ref) {
            $matched = (("$($db.server)").Trim().ToLowerInvariant() -eq $server) -and
                       (("$($db.ref)").Trim().ToLowerInvariant() -eq $ref)
        } elseif ($target -and $db.path) {
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

# --- Боевая база (skip if DryRun) ---
if (-not $DryRun) {
    Assert-InfoBaseMutable -InfoBasePath $InfoBasePath -InfoBaseServer $InfoBaseServer -InfoBaseRef $InfoBaseRef -AllowProd:$AllowProd
}

# --- Helper: map sub-file path (BSL, HTML, etc.) to object XML ---
function Get-ObjectXmlFromSubFile {
    param([string]$RelativePath)

    $parts = $RelativePath -split '[\\/]'
    if ($parts.Count -ge 2) {
        return "$($parts[0])/$($parts[1]).xml"
    }
    return $null
}

# --- Resolve V8Path (skip if DryRun) ---
if (-not $DryRun) {
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
}

# --- Validate connection (skip if DryRun) ---
if (-not $DryRun) {
    if (-not $InfoBasePath -and (-not $InfoBaseServer -or -not $InfoBaseRef)) {
        Write-Host "Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef" -ForegroundColor Red
        exit 1
    }}

# --- Validate config dir ---
if (-not (Test-Path $ConfigDir)) {
    Write-Host "Error: config directory not found: $ConfigDir" -ForegroundColor Red
    exit 1
}

# --- Validate Commit mode ---
if ($Source -eq "Commit" -and -not $CommitRange) {
    Write-Host "Error: -CommitRange required for Source=Commit" -ForegroundColor Red
    exit 1
}

# --- Check git ---
try {
    $null = git --version 2>&1
} catch {
    Write-Host "Error: git not found in PATH" -ForegroundColor Red
    exit 1
}

# --- Get changed files from Git ---
$changedFiles = @()
$ConfigDir = (Resolve-Path $ConfigDir).Path.TrimEnd('\')
$configDirNormalized = $ConfigDir.Replace('\', '/')

# core.quotePath=false: with the git default a path with non-ASCII characters comes back
# quoted and octal-escaped, Test-Path does not find it and the object silently drops out
# of the load list. The output is decoded as UTF-8 explicitly through Process: the console
# code page is not involved, and a process without a console (CI runner) decodes the same way.
function Invoke-GitLines {
    param([string[]]$GitArgs)
    $quoted = @('-c', 'core.quotePath=false') + $GitArgs | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'git'
    $psi.Arguments = $quoted -join ' '
    $psi.WorkingDirectory = (Get-Location).Path
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.CreateNoWindow = $true
    try {
        $proc = [System.Diagnostics.Process]::Start($psi)
    } catch {
        Write-Host "git not started: $($_.Exception.Message)"
        return @()
    }
    # stderr читается до WaitForExit, иначе процесс с полным буфером stderr не завершится.
    $errTask = $proc.StandardError.ReadToEndAsync()
    $out = $proc.StandardOutput.ReadToEnd()
    $proc.WaitForExit()
    if ($proc.ExitCode -ne 0) {
        # Отказ git называется вслух: молчаливый пустой список выглядел бы как "изменений нет".
        Write-Host "git $($GitArgs -join ' ') failed (exit $($proc.ExitCode)): $($errTask.Result.Trim())"
        return @()
    }
    return @($out -split "`r?`n" | Where-Object { $_ -ne '' })
}

Push-Location $ConfigDir
try {
    switch ($Source) {
        "Staged" {
            Write-Host "Getting staged changes..."
            $changedFiles += Invoke-GitLines @("diff", "--cached", "--name-only", "--relative")
        }
        "Unstaged" {
            Write-Host "Getting unstaged changes..."
            $changedFiles += Invoke-GitLines @("diff", "--name-only", "--relative")
            $changedFiles += Invoke-GitLines @("ls-files", "--others", "--exclude-standard")
        }
        "Commit" {
            Write-Host "Getting changes from $CommitRange..."
            $changedFiles += Invoke-GitLines @("diff", "--name-only", "--relative", $CommitRange)
        }
        "All" {
            Write-Host "Getting all uncommitted changes..."
            $changedFiles += Invoke-GitLines @("diff", "--cached", "--name-only", "--relative")
            $changedFiles += Invoke-GitLines @("diff", "--name-only", "--relative")
            $changedFiles += Invoke-GitLines @("ls-files", "--others", "--exclude-standard")
        }
    }
} finally {
    Pop-Location
}

$changedFiles = $changedFiles | Where-Object { $_ -is [string] -and -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

if ($changedFiles.Count -eq 0) {
    Write-Host "No changes found"
    exit 0
}

Write-Host "Git changes detected: $($changedFiles.Count) files"

# --- Filter and map to config files ---
$configFiles = @()

foreach ($file in $changedFiles) {
    $file = $file.Trim().Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($file)) { continue }

    # Skip service files
    if ($file -eq "ConfigDumpInfo.xml") { continue }

    $fullPath = Join-Path $ConfigDir $file

    if ($file -match '\.xml$') {
        # XML file - add directly if exists
        if (Test-Path $fullPath) {
            if ($configFiles -notcontains $file) {
                $configFiles += $file
            }
        }
    }
    else {
        # Non-XML (BSL, HTML, etc.) - map to parent object XML + include all Ext/ files
        $objectXml = Get-ObjectXmlFromSubFile -RelativePath $file
        if ($objectXml) {
            $fullXmlPath = Join-Path $ConfigDir $objectXml
            if (Test-Path $fullXmlPath) {
                if ($configFiles -notcontains $objectXml) {
                    $configFiles += $objectXml
                }
                if ((Test-Path $fullPath) -and $configFiles -notcontains $file) {
                    $configFiles += $file
                }

                # Add all files from Ext/ directory of the object
                $parts = $file -split '[\\/]'
                if ($parts.Count -ge 2) {
                    $extDir = Join-Path (Join-Path $ConfigDir $parts[0]) "$($parts[1])\Ext"
                    if (Test-Path $extDir) {
                        # The relative path is rebuilt from the object parts and the part inside Ext:
                        # FullName is canonical (long form), while $ConfigDir keeps the spelling it was
                        # given, for example a short 8.3 name of the temp folder, so prefix replacement
                        # does not strip it and the absolute path would stay in the list.
                        $extDirFull = (Get-Item -LiteralPath $extDir).FullName
                        Get-ChildItem -Path $extDir -Recurse -File | ForEach-Object {
                            $inside = $_.FullName.Substring($extDirFull.Length).TrimStart('\', '/').Replace('\', '/')
                            $extRelPath = "$($parts[0])/$($parts[1])/Ext/$inside"
                            if ($configFiles -notcontains $extRelPath) {
                                $configFiles += $extRelPath
                            }
                        }
                    }
                }
            }
        }
    }
}

if ($configFiles.Count -eq 0) {
    Write-Host "No configuration files found in changes"
    exit 0
}

Write-Host "Files for loading: $($configFiles.Count)"
foreach ($f in $configFiles) { Write-Host "  $f" }

# --- DryRun: stop here ---
if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun mode - no changes applied"
    exit 0
}

# --- Temp dir ---
$tempDir = Join-Path $env:TEMP "db_load_git_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

try {
    # --- Write list file (UTF-8 with BOM) ---
    $listFile = Join-Path $tempDir "load_list.txt"
    $utf8Bom = New-Object System.Text.UTF8Encoding($true)
    [System.IO.File]::WriteAllLines($listFile, $configFiles, $utf8Bom)

    # --- Build arguments ---
    $arguments = @("DESIGNER")

    if ($InfoBaseServer -and $InfoBaseRef) {
        $arguments += "/S", "`"$InfoBaseServer/$InfoBaseRef`""
    } else {
        $arguments += "/F", "`"$InfoBasePath`""
    }

    if ($UserName) { $arguments += "/N`"$UserName`"" }
    if ($Password) { $arguments += "/P`"$Password`"" }

    $arguments += "/LoadConfigFromFiles", "`"$ConfigDir`""
    $arguments += "-listFile", "`"$listFile`""
    $arguments += "-Format", $Format
    $arguments += "-partial"
    $arguments += "-updateConfigDumpInfo"

    # --- Extensions ---
    if ($Extension) {
        $arguments += "-Extension", "`"$Extension`""
    } elseif ($AllExtensions) {
        $arguments += "-AllExtensions"
    }

    # --- UpdateDB ---
    if ($UpdateDB) {
        $arguments += "/UpdateDBCfg"
    }

    # --- Output ---
    # Каталог временный и уникальный на запуск, поэтому лог и файл результата не могут
    # достаться от прошлого прогона.
    $outFile = Join-Path $tempDir "load_log.txt"
    $resultFile = Join-Path $tempDir "load_result.txt"
    $arguments += "/Out", "`"$outFile`""
    $arguments += "/DumpResult", "`"$resultFile`""
    $arguments += "/DisableStartupDialogs"

    # --- Execute ---
    Write-Host ""
    Write-Host "Executing partial configuration load..."
    Write-Host "Running: 1cv8.exe $(Hide-PlatformSecret ($arguments -join ' '))"

    $process = Start-Process -FilePath $V8Path -ArgumentList $arguments -NoNewWindow -Wait -PassThru
    $exitCode = $process.ExitCode

    # --- Result ---
    Write-Host ""
    $logContent = $null
    if (Test-Path $outFile) {
        $logContent = Get-Content $outFile -Raw -ErrorAction SilentlyContinue
    }

    $exitCode = Write-PlatformVerdict -ExitCode $exitCode -ResultFile $resultFile -LogText $logContent `
        -SuccessMessage "Load completed successfully" `
        -FailureMessage "Error loading configuration" `
        -Strict:$StrictLog

    exit $exitCode

} finally {
    if (Test-Path $tempDir) {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
