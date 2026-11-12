# Faqat tekshirilgan joriy paketdan keyin qayta yaratiladigan build qoldiqlarini tozalaydi.
[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$releaseRoot = Join-Path $projectRoot 'desktop/release'
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'desktop/package.json') -Raw | ConvertFrom-Json).version
$manifest = Get-Content -LiteralPath (Join-Path $releaseRoot 'desktop-update.json') -Raw | ConvertFrom-Json
if ($version -notmatch '^\d+\.\d+\.\d+$' -or $manifest.version -ne $version -or $manifest.filename -ne "TIN-CRM-Setup-$version.exe") {
    throw 'Joriy EXE va manifest versiyalari mos emas. Avval paketni yiging.'
}
$installer = Get-Item -LiteralPath (Join-Path $releaseRoot $manifest.filename)
if ($installer.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Installer symlink bolishi mumkin emas.' }
$hash = [Security.Cryptography.SHA512]::Create()
$stream = $installer.OpenRead()
try { $sha512 = [Convert]::ToBase64String($hash.ComputeHash($stream)) }
finally { $stream.Dispose(); $hash.Dispose() }
if ($installer.Length -ne $manifest.size -or $sha512 -ne $manifest.sha512) { throw 'Joriy installer tekshiruvdan otmadi.' }

$candidates = [Collections.Generic.List[string]]::new()
foreach ($relative in @('backend/build', 'backend/dist', 'backend/marva-backend.spec', 'frontend/dist', 'desktop/release/win-unpacked', 'desktop/release/builder-debug.yml', '.pytest_cache')) {
    $candidates.Add((Join-Path $projectRoot $relative))
}
foreach ($item in Get-ChildItem -LiteralPath $releaseRoot -File) {
    if ($item.Name -match '^(?:TIN-CRM-Setup-(\d+\.\d+\.\d+)\.exe(?:\.sha256|\.blockmap)?|server-(\d+\.\d+\.\d+)\.zip(?:\.sha256)?)$') {
        $oldVersion = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
        if ([version]$oldVersion -lt [version]$version) { $candidates.Add($item.FullName) }
    }
}
foreach ($folder in @('backend/app', 'backend/tests', 'scripts')) {
    $candidates.Add((Join-Path $projectRoot "$folder/__pycache__"))
}

# Barcha yo'llar oldindan tekshiriladi. Junction/symlink orqali tashqariga chiqish yo'q.
$verified = @()
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    $absolute = [IO.Path]::GetFullPath($candidate)
    if (-not $absolute.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Loyiha tashqarisidagi yol: $absolute" }
    $item = Get-Item -LiteralPath $absolute -Force
    $ancestor = $item
    while ($ancestor -and $ancestor.FullName -ne $projectRoot) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Symlink/junction: $($ancestor.FullName)" }
        $ancestor = Get-Item -LiteralPath (Split-Path -Parent $ancestor.FullName) -Force
    }
    $children = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $absolute -Recurse -Force) } else { @() }
    if (@($children | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "Ichki symlink/junction: $absolute" }
    $bytes = if ($item.PSIsContainer) { ($children | Where-Object { -not $_.PSIsContainer } | Measure-Object Length -Sum).Sum } else { $item.Length }
    $verified += [pscustomobject]@{ Path = $absolute; Bytes = [long]$bytes }
}
$verified | Format-Table -AutoSize
if ($Apply) {
    foreach ($item in $verified) { Remove-Item -LiteralPath $item.Path -Recurse -Force }
}
[pscustomobject]@{ Applied = [bool]$Apply; Items = $verified.Count; Bytes = ($verified | Measure-Object Bytes -Sum).Sum; KeptVersion = $version }

