# Upload new or changed files to the R2 bucket: map tiles (tiles/), painted squares (painted/detail/)
# and the style reference (style/ref.png). The last two let contributors paint with seam context.
# Tracks what was sent in deploy/.synced.json.
#   pwsh deploy/sync_tiles.ps1            (set $env:WRANGLER to a wrangler binary; default: npx wrangler)
param([int]$Parallel = 8)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$bucket = 'slc-miniworld-tiles'
$state = Join-Path $PSScriptRoot '.synced.json'
$sent = @{}
if (Test-Path $state) { (Get-Content $state -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $sent[$_.Name] = $_.Value } }

$sources = @(
    @{ Dir = 'tiles'; Prefix = ''; Filter = '*.jpg'; Type = 'image/jpeg'; Recurse = $true },
    @{ Dir = 'painted\detail'; Prefix = 'painted/detail/'; Filter = 'r*_c*.png'; Type = 'image/png'; Recurse = $false },
    @{ Dir = 'style'; Prefix = 'style/'; Filter = 'ref.png'; Type = 'image/png'; Recurse = $false }
)
$todo = foreach ($s in $sources) {
    $dir = Join-Path $root $s.Dir
    if (-not (Test-Path $dir)) { continue }
    Get-ChildItem $dir -File -Filter $s.Filter -Recurse:$s.Recurse | ForEach-Object {
        $key = $s.Prefix + $_.FullName.Substring($dir.Length + 1).Replace('\', '/')
        $sig = "$($_.Length)-$($_.LastWriteTimeUtc.Ticks)"
        if ($sent[$key] -ne $sig) { [pscustomobject]@{ Key = $key; Path = $_.FullName; Sig = $sig; Type = $s.Type } }
    }
}
$todo = @($todo)
"$($todo.Count) files to upload"
if (-not $todo.Count) { return }

$w = if ($env:WRANGLER) { $env:WRANGLER } else { 'npx' }
$wArgs = if ($env:WRANGLER) { @() } else { @('--yes', 'wrangler') }
$results = $todo | ForEach-Object -ThrottleLimit $Parallel -Parallel {
    $out = & $using:w @using:wArgs r2 object put "$using:bucket/$($_.Key)" --file $_.Path --content-type $_.Type --remote 2>&1
    [pscustomobject]@{ Key = $_.Key; Sig = $_.Sig; Ok = ($LASTEXITCODE -eq 0); Err = ($out | Select-Object -Last 1) }
}
$ok = @($results | Where-Object Ok)
foreach ($r in $ok) { $sent[$r.Key] = $r.Sig }
$sent | ConvertTo-Json -Depth 2 | Set-Content $state
"$($ok.Count) uploaded, $(@($results | Where-Object { -not $_.Ok }).Count) failed"
$results | Where-Object { -not $_.Ok } | Select-Object -First 3 | ForEach-Object { "  $($_.Key): $($_.Err)" }
