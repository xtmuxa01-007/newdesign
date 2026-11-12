# venv yaratilmaydi: barcha xizmatlar Docker orqali ishlaydi.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $projectRoot
try {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    $dockerPath = if ($dockerCommand) { $dockerCommand.Source } else { Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe' }
    if (-not (Test-Path -LiteralPath $dockerPath)) { throw 'Docker Desktop oʻrnatilmagan. Uni oʻrnatib, Linux containers rejimida ishga tushiring.' }
    if (-not (Test-Path -LiteralPath '.env')) { throw '.env.example faylidan .env nusxa yarating va ikkala parolni oʻzgartiring. README.md faylida tartibi yozilgan.' }
    & $dockerPath compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker xizmatlari ishga tushmadi. Yuqoridagi xatoni tekshiring.' }
    & $dockerPath compose ps
    Write-Host 'Standart manzil: http://127.0.0.1:8784 (.env ichidagi APP_PORT qiymatini tekshiring).'
} finally { Pop-Location }
