# Faqat markaz bazasi ataylab noldan boshlanganidan keyin, EXE 0.5.0+ uchun.
# Oldingi lokal baza yo'qolmaydi: profil qo'shni arxiv papkasiga ko'chiriladi.
[CmdletBinding()]
param(
    [string]$DataDirectory = $(if ($env:MARVA_DATA_DIR) { $env:MARVA_DATA_DIR } else { Join-Path $env:APPDATA 'Marva CRM\branch' }),
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$legacyPath = [IO.Path]::GetFullPath($DataDirectory)
$centersPath = [IO.Path]::GetFullPath((Join-Path $legacyPath 'centers'))
$targetPath = [IO.Path]::GetFullPath((Join-Path $centersPath 'tincrm-uz-v1'))
if (-not (Test-Path -LiteralPath $targetPath)) {
    Write-Output "Eski markaz profili yo'q. EXE 0.5.0 yoki yangiroq versiyani oching."
    return
}
# Reparse pointlar orqali boshqa papkaga chiqmasin.
$part = $targetPath
while ($part) {
    $entry = Get-Item -LiteralPath $part -Force
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Symlink/junction profilini avtomatik ko'chirish rad etildi." }
    $parent = [IO.Directory]::GetParent($part)
    if (-not $parent) { break }
    $part = $parent.FullName
}
$archivePath = [IO.Path]::GetFullPath((Join-Path $centersPath ('retired-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))))
$expectedPrefix = $centersPath.TrimEnd('\') + '\'
if (-not $targetPath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    -not $archivePath.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($targetPath) -ne 'tincrm-uz-v1') {
    throw "Profil/arxiv yo'li kutilgan markaz papkasidan tashqarida."
}
Write-Output ('Eski profil: ' + $targetPath)
Write-Output ('Saqlanadigan arxiv: ' + $archivePath)
if (-not $Apply) {
    Write-Output "Faqat tekshirildi. EXEni yoping; markaz reset qilingan bo'lsa shu buyruqni -Apply bilan bajaring."
    return
}
$running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(TIN[- ]?CRM|Marva[- ]?CRM|marva-backend)$' }
if ($running) { throw "Avval barcha TIN/Marva EXE oynalarini yoping. Eski baza ishlayotgan paytda profil ko'chirilmaydi." }
Move-Item -LiteralPath $targetPath -Destination $archivePath
Write-Output 'Eski baza va navbat arxivda saqlandi. Endi EXE 0.5.0+ ni ochib hisobingiz bilan kiring.'
Write-Output "Retired papkani yangi markazga qayta ko'chirmang: undagi yozuvlar eski davrga tegishli."
