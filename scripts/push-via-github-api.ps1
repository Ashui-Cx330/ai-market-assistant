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

function Invoke-GhText([string[]]$Arguments, [string]$Endpoint) {
  for ($attempt = 1; $attempt -le 5; $attempt++) {
    $output = & $gh @Arguments
    if ($LASTEXITCODE -eq 0) { return ($output -join "`n") }
    if ($attempt -eq 5) { throw "GitHub API request failed after $attempt attempts: $Endpoint" }
    $delay = [Math]::Min(12, [Math]::Pow(2, $attempt))
    Write-Warning "GitHub connection failed for $Endpoint; retry $($attempt + 1)/5 in $delay seconds."
    Start-Sleep -Seconds $delay
  }
}

function Invoke-GhJson([string]$Endpoint, [hashtable]$Body, [string]$Method = 'POST') {
  [IO.File]::WriteAllText($tempJson, ($Body | ConvertTo-Json -Depth 20 -Compress), (New-Object Text.UTF8Encoding($false)))
  $output = Invoke-GhText -Arguments @('api','--method',$Method,$Endpoint,'--input',$tempJson) -Endpoint $Endpoint
  return $output | ConvertFrom-Json
}

try {
  $localCommit = (& git rev-parse HEAD).Trim()
  $localParent = (& git rev-parse 'HEAD^').Trim()
  $remoteParent = (Invoke-GhText -Arguments @('api',"repos/$Owner/$Repo/git/ref/heads/$Branch",'--jq','.object.sha') -Endpoint "refs/heads/$Branch").Trim()
  if ($localParent -ne $remoteParent) {
    throw "API fallback refuses a non-fast-forward push: local parent $localParent, remote $remoteParent"
  }
  $baseTree = (Invoke-GhText -Arguments @('api',"repos/$Owner/$Repo/git/commits/$remoteParent",'--jq','.tree.sha') -Endpoint "commits/$remoteParent").Trim()
  $entries = @()
  foreach ($line in @(git diff-tree --no-commit-id --name-status -r HEAD)) {
    $parts = $line -split "`t"
    $status = $parts[0]
    $file = $parts[$parts.Count - 1]
    $repoPath = $file -replace '\\','/'
    if ($status.StartsWith('D')) {
      $entries += @{ path=$repoPath; mode='100644'; type='blob'; sha=$null }
      continue
    }
    $bytes = [IO.File]::ReadAllBytes((Join-Path (Get-Location) $file))
    $blob = Invoke-GhJson "repos/$Owner/$Repo/git/blobs" @{ content=[Convert]::ToBase64String($bytes); encoding='base64' }
    $index = (& git ls-files -s -- $file | Select-Object -First 1)
    $mode = if ($index -match '^(\d{6})\s') { $Matches[1] } else { '100644' }
    $entries += @{ path=$repoPath; mode=$mode; type='blob'; sha=$blob.sha }
    Write-Output ("Uploaded changed blob: " + $file)
  }
  $tree = Invoke-GhJson "repos/$Owner/$Repo/git/trees" @{ base_tree=$baseTree; tree=$entries }
  $expectedTree = (& git rev-parse 'HEAD^{tree}').Trim()
  if ($tree.sha -ne $expectedTree) { throw "Remote tree $($tree.sha) does not match local tree $expectedTree" }

  $author = @{ name=(& git show -s --format=%an HEAD); email=(& git show -s --format=%ae HEAD); date=(& git show -s --format=%aI HEAD) }
  $committer = @{ name=(& git show -s --format=%cn HEAD); email=(& git show -s --format=%ce HEAD); date=(& git show -s --format=%cI HEAD) }
  $commit = Invoke-GhJson "repos/$Owner/$Repo/git/commits" @{ message=$Message; tree=$tree.sha; parents=@($remoteParent); author=$author; committer=$committer }
  if ($commit.sha -ne $localCommit) {
    # GitHub normalizes ISO-8601 timezone offsets to UTC when it creates a
    # commit through the Git Data API. Recreate that byte-identical commit
    # locally before moving either ref so the local and remote histories stay
    # identical instead of leaving a hidden API-only commit behind.
    $savedEnvironment = @{}
    foreach ($name in @('GIT_AUTHOR_NAME','GIT_AUTHOR_EMAIL','GIT_AUTHOR_DATE','GIT_COMMITTER_NAME','GIT_COMMITTER_EMAIL','GIT_COMMITTER_DATE')) {
      $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
      $env:GIT_AUTHOR_NAME = [string]$commit.author.name
      $env:GIT_AUTHOR_EMAIL = [string]$commit.author.email
      $env:GIT_AUTHOR_DATE = [string]$commit.author.date
      $env:GIT_COMMITTER_NAME = [string]$commit.committer.name
      $env:GIT_COMMITTER_EMAIL = [string]$commit.committer.email
      $env:GIT_COMMITTER_DATE = [string]$commit.committer.date
      $normalizedCommit = (& git commit-tree $tree.sha -p $remoteParent -m $Message).Trim()
      if ($LASTEXITCODE -ne 0) { throw 'git commit-tree failed while normalizing the API commit' }
      if ($normalizedCommit -ne $commit.sha) {
        # The REST API stores the supplied message without Git's conventional
        # trailing LF. hash-object lets us reproduce that valid form exactly.
        # The commit hash preserves the offsets submitted to GitHub even though
        # the response renders both timestamps as UTC.
        $authorStamp = [DateTimeOffset]::Parse([string]$author.date)
        $committerStamp = [DateTimeOffset]::Parse([string]$committer.date)
        $authorZone = $authorStamp.ToString('zzz').Replace(':','')
        $committerZone = $committerStamp.ToString('zzz').Replace(':','')
        $rawCommit = "tree $($tree.sha)`nparent $remoteParent`nauthor $($commit.author.name) <$($commit.author.email)> $($authorStamp.ToUnixTimeSeconds()) $authorZone`ncommitter $($commit.committer.name) <$($commit.committer.email)> $($committerStamp.ToUnixTimeSeconds()) $committerZone`n`n$Message"
        $tempCommit = Join-Path $env:TEMP ("ai-market-commit-" + [guid]::NewGuid().ToString('N'))
        try {
          [IO.File]::WriteAllText($tempCommit, $rawCommit, (New-Object Text.UTF8Encoding($false)))
          $normalizedCommit = (& git hash-object -t commit -w $tempCommit).Trim()
        } finally {
          if (Test-Path -LiteralPath $tempCommit) { Remove-Item -LiteralPath $tempCommit -Force }
        }
      }
      if ($normalizedCommit -ne $commit.sha) {
        throw "Unable to reproduce GitHub commit $($commit.sha) locally (created $normalizedCommit)"
      }
      & git update-ref "refs/heads/$Branch" $normalizedCommit $localCommit
      if ($LASTEXITCODE -ne 0) { throw "Unable to update local $Branch to normalized commit $normalizedCommit" }
      $localCommit = $normalizedCommit
      Write-Output ("Normalized local commit timezone: " + $localCommit)
    } finally {
      foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
      }
    }
  }
  Invoke-GhJson "repos/$Owner/$Repo/git/refs/heads/$Branch" @{ sha=$commit.sha; force=$false } 'PATCH' | Out-Null
  Write-Output ("GitHub API fast-forward complete: " + $commit.sha)
} finally {
  if (Test-Path -LiteralPath $tempJson) { Remove-Item -LiteralPath $tempJson -Force }
}
