<#
  Поднять MCP Toolkit HTTP-сервер (headless) по параметрам из .dev.env.
  Автостарт встроенного сервера через /C "startup;mode=embedded;port=N".

  Примеры:
    .\start-mcp.ps1
    .\start-mcp.ps1 -EnvFile D:\proj\.dev.env
    .\start-mcp.ps1 -Port 6004
#>
param([string]$EnvFile, [int]$Port)

. "$PSScriptRoot\_env.ps1"
$e = Import-DevEnv $EnvFile
if (-not $Port) { $Port = [int](Get-EnvVal $e 'TOOLKIT_PORT' '6003') }

$exe = Get-ClientExe $e
$epf = Get-EnvVal $e 'TOOLKIT_EPF'
if (-not $exe -or -not (Test-Path $exe)) { throw "не найден клиент 1С: $exe (проверь PLATFORM_PATH)" }
if (-not $epf -or -not (Test-Path $epf)) { throw "не найден TOOLKIT_EPF: $epf" }

if (Test-TcpPort $Port) { Write-Host "MCP toolkit уже работает: http://localhost:$Port" -ForegroundColor Green; return }

$argList = @(Get-ConnArgs $e) + (Get-AuthArgs $e) + @("/Execute`"$epf`"", "/C`"startup;mode=embedded;port=$Port`"")
$p = Start-Process -FilePath $exe -ArgumentList $argList -PassThru
Write-Host "запуск 1С (PID $($p.Id)), жду сервер на :$Port ..."
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 1500
    if ($p.HasExited) { Write-Warning "1С завершилась код=$($p.ExitCode) — проверь учётные данные/базу"; exit 1 }
    if (Test-TcpPort $Port) { Write-Host "ГОТОВО: http://localhost:$Port/health (PID $($p.Id))" -ForegroundColor Green; return }
}
Write-Warning "сервер не поднялся за 60с (диалог в 1С? занят порт?)"
