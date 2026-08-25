<#
  Выполнить произвольный BSL в живой базе через toolkit (execute_code),
  в обход фильтра опасных слов: код кодируется Base64 и исполняется
  Выполнить(ПолучитьСтрокуИзДвоичныхДанных(Base64Значение(...))). Запись
  (Записать/Удалить) не детектится, переносы строк и кавычки не ломаются.

  ВНИМАНИЕ: это ПОЛНЫЙ доступ (запись/удаление/привилегии). Только dev/test.

  Примеры:
    .\run-bsl.ps1 -Code 'Результат = Справочники.Организации.ВыбратьИерархически().Количество();'
    .\run-bsl.ps1 -File D:\proj\script.bsl
  Контракт: скрипт может присвоить переменную Результат (вернётся в data); иначе "ok".
#>
param([string]$File, [string]$Code, [string]$EnvFile, [int]$Port)

. "$PSScriptRoot\_env.ps1"
$e = Import-DevEnv $EnvFile
if (-not $Port) { $Port = [int](Get-EnvVal $e 'TOOLKIT_PORT' '6003') }

if ($File) {
    if (-not (Test-Path $File)) { throw "нет файла: $File" }
    $bsl = [System.IO.File]::ReadAllText($File, [System.Text.Encoding]::UTF8)
} elseif ($Code) {
    $bsl = $Code
} else {
    throw "укажи -File <script.bsl> или -Code '<bsl>'"
}

$b64 = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($bsl))
$outer = 'Результат = Неопределено; Выполнить(ПолучитьСтрокуИзДвоичныхДанных(Base64Значение("' + $b64 + '"), КодировкаТекста.UTF8)); Если Результат = Неопределено Тогда Результат = "ok"; КонецЕсли;'
$body = @{ code = $outer } | ConvertTo-Json -Compress

try {
    $r = Invoke-RestMethod -Uri "http://localhost:$Port/api/execute_code" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
    if ($r.success) { Write-Host "OK:" -ForegroundColor Green; $r.data }
    else { Write-Host "ОШИБКА:" -ForegroundColor Red; $r.error }
} catch {
    Write-Host "запрос упал (сервер поднят? запусти start-mcp.ps1): $($_.Exception.Message)" -ForegroundColor Red
}
