param(
  [Parameter(Mandatory=$true)][string]$Owner,
  [Parameter(Mandatory=$true)][string]$Repo,
  [string]$Branch = 'main',
  [Parameter(Mandatory=$true)][string]$Message
)
$ErrorActionPreference = 'Stop'
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { $gh = Join-Path $env:LOCALAPPDATA 'Programs\GitHub CLI\bin\gh.exe' }
if (-not (Test-Path -LiteralPath $gh)) { throw 'GitHub CLI is not installed.' }
$tempJson = Join-Path $env:TEMP ("ai-market-github-api-" + [guid]::NewGuid().ToString('N') + '.json')

function Invoke-GhJson([string]$Endpoint, [hashtable]$Body, [string]$Method = 'POST') {
  [IO.File]::WriteAllText($tempJson, ($Body | ConvertTo-Json -Depth 20 -Compress), (New-Object Text.UTF8Encoding($false)))
  $output = & $gh api --method $Method $Endpoint --input $tempJson
  if ($LASTEXITCODE -ne 0) { throw "GitHub API request failed: $Endpoint" }
  return $output | ConvertFrom-Json
}

try {
  $isEmpty = (& $gh repo view "$Owner/$Repo" --json isEmpty --jq .isEmpty).Trim()
  if ($isEmpty -eq 'true') {
    $bootstrap = Invoke-GhJson "repos/$Owner/$Repo/contents/.bootstrap" @{ message='initialize repository'; content=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('bootstrap')); branch=$Branch } 'PUT'
    Write-Output 'Initialized empty GitHub repository.'
  }
  $entries = @()
  $files = @(git ls-files)
  foreach ($file in $files) {
    $bytes = [IO.File]::ReadAllBytes((Join-Path (Get-Location) $file))
    $blob = Invoke-GhJson "repos/$Owner/$Repo/git/blobs" @{ content=[Convert]::ToBase64String($bytes); encoding='base64' }
    $entries += @{ path=($file -replace '\\','/'); mode='100644'; type='blob'; sha=$blob.sha }
    Write-Output ("Uploaded blob: " + $file)
  }
  $tree = Invoke-GhJson "repos/$Owner/$Repo/git/trees" @{ tree=$entries }
  $parent = ''
  $oldPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $parent = (& $gh api "repos/$Owner/$Repo/git/ref/heads/$Branch" --jq .object.sha 2>$null)
  $ErrorActionPreference = $oldPreference
  $commitBody = @{ message=$Message; tree=$tree.sha }
  if ($parent) { $commitBody.parents = @([string]$parent) }
  $commit = Invoke-GhJson "repos/$Owner/$Repo/git/commits" $commitBody
  if ($parent) {
    Invoke-GhJson "repos/$Owner/$Repo/git/refs/heads/$Branch" @{ sha=$commit.sha; force=$false } 'PATCH' | Out-Null
  } else {
    Invoke-GhJson "repos/$Owner/$Repo/git/refs" @{ ref="refs/heads/$Branch"; sha=$commit.sha } | Out-Null
  }
  Write-Output ("GitHub API push complete: " + $commit.sha)
} finally {
  if (Test-Path -LiteralPath $tempJson) { Remove-Item -LiteralPath $tempJson -Force }
}
