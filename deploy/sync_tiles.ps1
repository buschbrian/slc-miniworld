# Upload new or changed tiles under tiles/ to the R2 bucket. Tracks what was sent in deploy/.synced.json.
#   pwsh deploy/sync_tiles.ps1            (set $env:WRANGLER to a wrangler binary; default: npx wrangler)
param([int]$Parallel = 8)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$bucket = 'slc-miniworld-tiles'
$state = Join-Path $PSScriptRoot '.synced.json'
$sent = @{}
if (Test-Path $state) { (Get-Content $state -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $sent[$_.Name] = $_.Value } }

$tilesDir = Join-Path $root 'tiles'
$todo = Get-ChildItem $tilesDir -Recurse -File -Filter *.jpg | ForEach-Object {
    $key = $_.FullName.Substring($tilesDir.Length + 1).Replace('\', '/')
    $sig = "$($_.Length)-$($_.LastWriteTimeUtc.Ticks)"
    if ($sent[$key] -ne $sig) { [pscustomobject]@{ Key = $key; Path = $_.FullName; Sig = $sig } }
}
$todo = @($todo)
"$($todo.Count) tiles to upload"
if (-not $todo.Count) { return }

$w = if ($env:WRANGLER) { $env:WRANGLER } else { 'npx' }
$wArgs = if ($env:WRANGLER) { @() } else { @('--yes', 'wrangler') }
$results = $todo | ForEach-Object -ThrottleLimit $Parallel -Parallel {
    $out = & $using:w @using:wArgs r2 object put "$using:bucket/$($_.Key)" --file $_.Path --content-type image/jpeg --remote 2>&1
    [pscustomobject]@{ Key = $_.Key; Sig = $_.Sig; Ok = ($LASTEXITCODE -eq 0); Err = ($out | Select-Object -Last 1) }
}
$ok = @($results | Where-Object Ok)
foreach ($r in $ok) { $sent[$r.Key] = $r.Sig }
$sent | ConvertTo-Json -Depth 2 | Set-Content $state
"$($ok.Count) uploaded, $(@($results | Where-Object { -not $_.Ok }).Count) failed"
$results | Where-Object { -not $_.Ok } | Select-Object -First 3 | ForEach-Object { "  $($_.Key): $($_.Err)" }
