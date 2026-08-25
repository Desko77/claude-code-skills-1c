# _env.ps1 — общий загрузчик .dev.env и хелперы. Подключается через dot-source:
#   . "$PSScriptRoot\_env.ps1"
# Совместим с Windows PowerShell 5.1 и PowerShell 7+.

function Import-DevEnv {
    param([string]$Path)
    if (-not $Path) {
        foreach ($c in @((Join-Path (Get-Location).Path '.dev.env'), (Join-Path $PSScriptRoot '.dev.env'))) {
            if (Test-Path $c) { $Path = $c; break }
        }
    }
    if (-not $Path -or -not (Test-Path $Path)) {
        throw ".dev.env не найден. Укажи -EnvFile <путь> или положи .dev.env рядом со скриптом / в текущий каталог."
    }
    $h = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if ($t.Length -eq 0 -or $t[0] -eq '#') { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $h[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
    }
    $h['_PATH'] = $Path
    return $h
}

function Get-EnvVal($e, $k, $def = $null) {
    if ($e.ContainsKey($k) -and $e[$k]) { return $e[$k] } else { return $def }
}

function Get-ClientExe($e) {
    $b = Get-EnvVal $e 'PLATFORM_PATH'
    if (-not $b) { throw 'PLATFORM_PATH не задан в .dev.env' }
    if ($b -match '(?i)1cv8c?\.exe$') { return $b }
    return (Join-Path $b '1cv8c.exe')
}

function Get-DesignerExe($e) {
    $b = Get-EnvVal $e 'PLATFORM_PATH'
    if (-not $b) { throw 'PLATFORM_PATH не задан в .dev.env' }
    if ($b -match '(?i)1cv8\.exe$') { return $b }
    if ($b -match '(?i)1cv8c\.exe$') { return ($b -replace '(?i)1cv8c\.exe$', '1cv8.exe') }
    return (Join-Path $b '1cv8.exe')
}

function Get-ConnArgs($e) {
    if ((Get-EnvVal $e 'INFOBASE_KIND' 'File') -eq 'Server') {
        $s = Get-EnvVal $e 'INFOBASE_SERVER'
        if (-not $s) { throw 'INFOBASE_KIND=Server, но INFOBASE_SERVER не задан (формат: сервер\база)' }
        return @("/S`"$s`"")
    }
    $p = Get-EnvVal $e 'INFOBASE_PATH'
    if (-not $p) { throw 'INFOBASE_PATH не задан в .dev.env' }
    return @("/F`"$p`"")
}

function Get-AuthArgs($e) {
    $a = @()
    $u = Get-EnvVal $e 'IB_USER'
    $w = Get-EnvVal $e 'IB_PASSWORD'
    if ($u) { $a += "/N`"$u`"" }
    if ($w) { $a += "/P`"$w`"" }
    return $a
}

function Test-TcpPort([int]$Port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', $Port); return $c.Connected } catch { return $false } finally { $c.Dispose() }
}
