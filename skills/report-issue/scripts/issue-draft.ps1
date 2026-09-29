# issue-draft v1.0 - Check an issue draft for private data and build a GitHub new-issue link
param(
	[string]$Repo = "",
	[string]$Title = "",
	[string]$BodyFile = "",
	[string]$Labels = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:urlLimit = 8000
$script:allowedHosts = @("github.com", "t.me", "its.1c.ru", "v8.1c.ru", "1c.ru", "docs.anthropic.com",
	"cursor.com", "localhost", "127.0.0.1")
$script:allowedIps = @("127.0.0.1", "0.0.0.0")

$script:patterns = @(
	@{ Kind = "путь"; Re = [regex]'(?<![\w/])[A-Za-z]:[\\/][^\s"''`|*?]*' },
	@{ Kind = "сетевой путь"; Re = [regex]'(?<![\w\\/])\\\\[\w.$-]+\\[^\s"''`|]*' },
	@{ Kind = "домашний каталог"; Re = [regex]'(?<![\w.])/(?:home|Users)/[\w.-]+' },
	@{ Kind = "IP-адрес"; Re = [regex]'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])' },
	@{ Kind = "адрес почты"; Re = [regex]'[\w.+-]+@[\w-]+(?:\.[\w-]+)+' },
	@{ Kind = "секрет"; Re = [regex]'(?i)\b(?:password|passwd|pwd|token|secret|api[_-]?key|пароль)\s*[:=]\s*\S+' },
	@{ Kind = "токен"; Re = [regex]'\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_]{16,}|\bBearer\s+[A-Za-z0-9._-]{16,}' },
	@{ Kind = "строка соединения"; Re = [regex]'(?i)\b(?:Srvr|Ref|Usr|Pwd)\s*=\s*"?[^;"\s]+' },
	@{ Kind = "UUID"; Re = [regex]'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b' },
	@{ Kind = "ссылка"; Re = [regex]'https?://[^\s)>\]"''`]+' }
)

function Test-Allowed {
	# Обобщенные значения, которые находкой не считаются.
	param([string]$Kind, [string]$Text)
	switch ($Kind) {
		"путь" {
			$normalized = $Text.Replace('\', '/').ToLowerInvariant()
			return ($normalized.StartsWith("c:/projects/") -or $normalized -eq "c:/projects" -or $Text.Contains("<"))
		}
		"IP-адрес" { return ($script:allowedIps -ccontains $Text) }
		"UUID" { return (($Text -replace '[0-]', '') -eq '') }
		"ссылка" {
			$hostName = ""
			$uri = $null
			if ([Uri]::TryCreate($Text, [UriKind]::Absolute, [ref]$uri)) { $hostName = $uri.Host.ToLowerInvariant() }
			foreach ($h in $script:allowedHosts) {
				if ($hostName -eq $h -or $hostName.EndsWith("." + $h)) { return $true }
			}
			return $false
		}
	}
	return $false
}

function Get-Findings {
	# Находки черновика: место, вид, значение - в порядке строк и позиций.
	param([string]$TitleText, [string]$Body)
	$findings = New-Object System.Collections.Generic.List[object]
	$lines = New-Object System.Collections.Generic.List[object]
	$lines.Add(@("заголовок", $TitleText))
	$number = 0
	foreach ($line in $Body.Split("`n")) {
		$number++
		$lines.Add(@("строка $number", $line))
	}
	foreach ($entry in $lines) {
		$place = $entry[0]
		$line = $entry[1]
		$hits = New-Object System.Collections.Generic.List[object]
		foreach ($pattern in $script:patterns) {
			foreach ($match in $pattern.Re.Matches($line)) {
				$value = $match.Value.TrimEnd('.', ',', ';', ':')
				if (-not (Test-Allowed -Kind $pattern.Kind -Text $value)) {
					$hits.Add([pscustomobject]@{ Start = $match.Index; Kind = $pattern.Kind; Value = $value })
				}
			}
		}
		$hits.Sort([System.Comparison[object]] {
			param($a, $b)
			if ($a.Start -ne $b.Start) { return $a.Start.CompareTo($b.Start) }
			$byKind = [string]::CompareOrdinal($a.Kind, $b.Kind)
			if ($byKind -ne 0) { return $byKind }
			return [string]::CompareOrdinal($a.Value, $b.Value)
		})
		$covered = New-Object System.Collections.Generic.List[object]
		foreach ($hit in $hits) {
			$end = $hit.Start + $hit.Value.Length
			$inside = $false
			foreach ($span in $covered) {
				if ($span[0] -le $hit.Start -and $end -le $span[1]) { $inside = $true; break }
			}
			if ($inside) { continue }
			$covered.Add(@($hit.Start, $end))
			$findings.Add(@($place, $hit.Kind, $hit.Value))
		}
	}
	return , $findings
}

function Build-IssueUrl {
	# Ссылка на новую issue; тело не входит, если ссылка длиннее предела GitHub.
	param([string]$RepoName, [string]$TitleText, [string]$Body, [string[]]$LabelList)
	$base = "https://github.com/$RepoName/issues/new?title=$([Uri]::EscapeDataString($TitleText))"
	$tail = ""
	if ($LabelList.Count -gt 0) { $tail = "&labels=$([Uri]::EscapeDataString($LabelList -join ','))" }
	$full = $base + "&body=$([Uri]::EscapeDataString($Body))" + $tail
	if ($full.Length -le $script:urlLimit) { return @($full, $true) }
	return @(($base + $tail), $false)
}

function Write-Err([string]$Text) {
	# Строка в stderr в UTF-8.
	[Console]::Error.WriteLine($Text)
}

if ($Repo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
	Write-Err "Неверный репозиторий: $Repo (нужно владелец/имя)"
	exit 2
}
$titleText = $Title.Trim()
if (-not $titleText) {
	Write-Err "Пустой заголовок"
	exit 2
}
if (-not $BodyFile -or -not (Test-Path -LiteralPath $BodyFile -PathType Leaf)) {
	Write-Err "Файл текста не читается: $BodyFile"
	exit 2
}
$body = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $BodyFile).Path, [System.Text.Encoding]::UTF8)
if ($body.Length -gt 0 -and $body[0] -eq [char]0xFEFF) { $body = $body.Substring(1) }
$body = $body.Replace("`r`n", "`n").Replace("`r", "`n").Trim("`n")
$labelList = @($Labels.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })

$findings = Get-Findings -TitleText $titleText -Body $body
if ($findings.Count -gt 0) {
	Write-Err "Находок: $($findings.Count)"
	foreach ($finding in $findings) { Write-Err "  $($finding[0]): $($finding[1]) - $($finding[2])" }
	Write-Err "Черновик не отправлять: замените находки обобщенными значениями и повторите проверку."
	exit 1
}

$result = Build-IssueUrl -RepoName $Repo -TitleText $titleText -Body $body -LabelList $labelList
Write-Output "Проверка на приватные данные: находок нет."
if (-not $result[1]) {
	Write-Output "Текст длиннее, чем принимает ссылка GitHub ($($script:urlLimit) символов): в ссылке только заголовок и метки, текст вставьте вручную либо создайте issue через gh issue create --body-file."
}
Write-Output "Ссылка для создания issue:"
Write-Output $result[0]
exit 0
