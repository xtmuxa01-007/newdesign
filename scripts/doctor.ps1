# Muhitni faqat tekshiradi. Parollarni chiqarib bermaydi va xizmatlarni oʻzgartirmaydi.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$failed = $false
Push-Location -LiteralPath $projectRoot
try {
    $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
    $dockerPath = if ($dockerCommand) { $dockerCommand.Source } else {
        $userDocker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
        if (Test-Path -LiteralPath $userDocker) { $userDocker } else { 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' }
    }
    if (-not (Test-Path -LiteralPath $dockerPath)) {
        Write-Host 'XATO: Docker Desktop oʻrnatilmagan yoki docker.exe topilmadi.'
        Write-Host 'Docker Desktop va WSL 2 tayyor boʻlgach ushbu tekshiruvni qayta bajaring.'
        $failed = $true
    } else {
        & $dockerPath version --format '{{.Server.Version}}'
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'XATO: Docker engine ishlamayapti. Docker Desktopni ishga tushiring.'
            $failed = $true
        } else { Write-Host 'OK: Docker engine mavjud.' }
        & $dockerPath compose version
        if ($LASTEXITCODE -ne 0) { $failed = $true }
    }
    if (-not (Test-Path -LiteralPath '.env')) {
        Write-Host 'XATO: .env yoʻq. .env.example dan nusxa oling va parollarni belgilang.'
        $failed = $true
    } elseif (Test-Path -LiteralPath $dockerPath) {
        & $dockerPath compose config --quiet
        if ($LASTEXITCODE -ne 0) { $failed = $true } else { Write-Host 'OK: Docker Compose sozlamalari oʻqildi.' }
        if (Select-String -LiteralPath '.env' -Pattern 'CHANGE_THIS' -Quiet) {
            Write-Host 'XATO: .env da namunaviy parollar qolgan.'
            $failed = $true
        }
    }
    if ($failed) { Write-Host 'Muhit hali tayyor emas. Yuqoridagi holatlarni tuzating.'; exit 1 }
    Write-Host 'Muhit tayyor. scripts/start.ps1 orqali CRMni ishga tushiring.'
} finally { Pop-Location }
