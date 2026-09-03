param([string]$BaseUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Stop'
$baseUrl = $BaseUrl.TrimEnd('/')
$results = @()

$health = Invoke-RestMethod "$baseUrl/api/health"
$results += [pscustomobject]@{ Test = 'API health'; Pass = $health.status -eq 'ok'; Detail = $health.phase }

$page = Invoke-WebRequest "$baseUrl/" -UseBasicParsing
$results += [pscustomobject]@{ Test = 'Vue production page'; Pass = $page.StatusCode -eq 200 -and $page.Content -match 'id="app"'; Detail = "$($page.RawContentLength) bytes" }

$overview = Invoke-RestMethod "$baseUrl/api/market/overview" -TimeoutSec 40
$crypto = @($overview.items | Where-Object { $_.asset_type -eq 'crypto' -and $_.available })
$stocks = @($overview.items | Where-Object { $_.asset_type -ne 'crypto' -and $_.available })
$results += [pscustomobject]@{ Test = 'Real crypto quotes'; Pass = $crypto.Count -ge 2; Detail = (($crypto | ForEach-Object { "$($_.symbol)@$($_.source)" }) -join ', ') }
$results += [pscustomobject]@{ Test = 'Real A-share quotes'; Pass = $stocks.Count -ge 5; Detail = (($stocks | ForEach-Object { "$($_.symbol)@$($_.source)" }) -join ', ') }

$body = @{ symbol = 'SOL'; asset_type = 'crypto' } | ConvertTo-Json
Invoke-RestMethod "$baseUrl/api/watchlist" -Method Post -ContentType 'application/json' -Body $body | Out-Null
$created = @((Invoke-RestMethod "$baseUrl/api/watchlist").items | Where-Object { $_.symbol -eq 'SOL' }).Count -eq 1
Invoke-RestMethod "$baseUrl/api/watchlist/SOL" -Method Delete | Out-Null
$deleted = @((Invoke-RestMethod "$baseUrl/api/watchlist").items | Where-Object { $_.symbol -eq 'SOL' }).Count -eq 0
$results += [pscustomobject]@{ Test = 'SQLite watchlist CRUD'; Pass = $created -and $deleted; Detail = 'add/read/delete SOL' }

$results | Format-Table -AutoSize
if ($results.Pass -contains $false) { exit 1 }
