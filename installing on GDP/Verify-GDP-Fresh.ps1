$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$manifest = Join-Path $root 'SHA256SUMS-FRESH.txt'
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw "Fresh-install checksum manifest is missing: $manifest"
}
$verified = 0
foreach ($line in Get-Content -LiteralPath $manifest) {
    if ($line -cnotmatch '^([0-9a-f]{64})  ([A-Za-z0-9_. /-]+)$') {
        throw "Invalid fresh-install manifest line: $line"
    }
    $expected = $Matches[1]
    $relative = $Matches[2]
    if ($relative -match '(^|/)\.\.(/|$)' -or $relative.StartsWith('/')) {
        throw "Unsafe manifest path: $relative"
    }
    $path = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Fresh-install package file is missing: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $expected) {
        throw "Fresh-install package checksum failed: $relative"
    }
    $verified++
}
if ($verified -lt 25) {
    throw "Fresh-install manifest is incomplete: $verified files"
}
Write-Output "GDP FRESH INSTALL VERIFIED: $verified files."
