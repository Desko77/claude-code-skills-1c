<#
  Канал КОДА: работа с конфигурацией через Designer-батч по параметрам .dev.env.

    -Action backup   выгрузить конфигурацию в .cf (точка отката) -> BACKUP_DIR\config_baseline.cf
    -Action dump     выгрузить конфигурацию в XML-исходники      -> SRC_DIR\cf
    -Action apply    LoadConfigFromFiles(SRC_DIR\cf) + UpdateDBCfg (ТРЕБУЕТ МОНОПОЛИИ)

  Порядок правки кода:
    1) code-channel.ps1 -Action dump      (свежие исходники!)
    2) править .bsl/.mdo в SRC_DIR\cf
    3) закрыть ВСЕ сеансы 1С (включая toolkit: Stop-Process -Name 1cv8c)
    4) code-channel.ps1 -Action apply
    5) start-mcp.ps1 + проверить через run-bsl.ps1

  ВНИМАНИЕ: apply грузит ВСЮ конфигурацию из SRC_DIR\cf (частичная -File в тек. версии
  игнорируется). Идемпотентно только если SRC_DIR\cf свежий — иначе откатит правки в БД.
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('backup', 'dump', 'apply')][string]$Action,
    [string]$EnvFile,
    [switch]$Force
)

. "$PSScriptRoot\_env.ps1"
$e = Import-DevEnv $EnvFile
$designer = Get-DesignerExe $e
$conn = Get-ConnArgs $e
$auth = Get-AuthArgs $e
$src = Get-EnvVal $e 'SRC_DIR'; if ($src) { $src = Join-Path $src 'cf' }
$bdir = Get-EnvVal $e 'BACKUP_DIR'
if (-not $bdir) { throw 'BACKUP_DIR не задан в .dev.env' }
if (-not (Test-Path $bdir)) { New-Item -ItemType Directory -Path $bdir -Force | Out-Null }

function Invoke-Designer($extra, $logName) {
    $log = Join-Path $bdir $logName
    $a = @('DESIGNER') + $conn + $auth + $extra + @("/Out`"$log`"", '/DisableStartupDialogs')
    $p = Start-Process -FilePath $designer -ArgumentList $a -PassThru
    if (-not $p.WaitForExit(600000)) { Write-Warning 'не завершилось за 10 мин'; try { $p.Kill() } catch {}; return $false }
    Write-Host "код=$($p.ExitCode)"
    if (Test-Path $log) {
        $t = [System.Text.Encoding]::GetEncoding(1251).GetString([System.IO.File]::ReadAllBytes($log))
        Write-Host ('лог (хвост): ' + $t.Substring([Math]::Max(0, $t.Length - 160)))
    }
    return ($p.ExitCode -eq 0)
}

switch ($Action) {
    'backup' {
        $cf = Join-Path $bdir 'config_baseline.cf'
        Invoke-Designer @("/DumpCfg`"$cf`"") 'dumpcfg.log' | Out-Null
        if (Test-Path $cf) { Write-Host ('бэкап: {0} ({1} МБ)' -f $cf, [math]::Round((Get-Item $cf).Length / 1MB, 1)) -ForegroundColor Green }
    }
    'dump' {
        if (-not $src) { throw 'SRC_DIR не задан в .dev.env' }
        if (-not (Test-Path $src)) { New-Item -ItemType Directory -Path $src -Force | Out-Null }
        Write-Host "выгрузка конфигурации в $src ..."
        Invoke-Designer @("/DumpConfigToFiles`"$src`"") 'dumpxml.log' | Out-Null
        if (Test-Path $src) { Write-Host ('файлов: ' + (Get-ChildItem -Recurse $src -File | Measure-Object).Count) -ForegroundColor Green }
    }
    'apply' {
        if (-not $src) { throw 'SRC_DIR не задан в .dev.env' }
        $busy = Get-Process -Name 1cv8, 1cv8c -ErrorAction SilentlyContinue
        if ($busy -and -not $Force) {
            Write-Warning 'Есть сеансы 1С — UpdateDBCfg требует МОНОПОЛИИ. Закрой их (вкл. toolkit: Stop-Process -Name 1cv8c) и повтори. Или -Force.'
            $busy | Select-Object Id, ProcessName | Format-Table -AutoSize | Out-String | Write-Host
            return
        }
        Write-Host 'LoadConfigFromFiles + UpdateDBCfg (монополия)...'
        $ok = Invoke-Designer @("/LoadConfigFromFiles`"$src`"", '/UpdateDBCfg') 'apply.log'
        if ($ok) { Write-Host 'применено. Подними toolkit (start-mcp.ps1) и проверь.' -ForegroundColor Green }
    }
}
