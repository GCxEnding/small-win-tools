# emoji-searcher: Windows 기본 Win+. (이모지 패널) 단축키 끄기
# - 기존 DisabledHotkeys 값은 유지하고, 마침표 키(VK_OEM_PERIOD, 0xBE)만 뒤에 덧붙입니다.
# - 변경 직전 Advanced 키 전체를 registry\backup\ 에 .reg로 백업합니다.
# - HKCU만 건드리므로 관리자 권한은 필요 없습니다.

$ErrorActionPreference = 'Stop'

$KeyPath  = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
$RegPath  = 'HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
$Name     = 'DisabledHotkeys'
$Target   = [string][char]0xBE   # 마침표 키

function Show-Value([string]$v) {
    if ($null -eq $v) { return '(값 없음)' }
    if ($v -eq '')    { return '(빈 문자열)' }
    return ($v -replace [regex]::Escape($Target), '[.]')
}

function Backup-Key {
    $dir = Join-Path $PSScriptRoot 'backup'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $file = Join-Path $dir ("Advanced_{0}.reg" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    & reg.exe export $RegPath $file /y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "백업 실패: $file" }
    return $file
}

function Restart-ExplorerPrompt {
    $ans = Read-Host '적용하려면 Explorer를 재시작해야 합니다. 지금 재시작할까요? (Y/N)'
    if ($ans -match '^[Yy]') {
        Stop-Process -Name explorer -Force
        Start-Sleep -Seconds 2
        if (-not (Get-Process -Name explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
        Write-Host 'Explorer를 재시작했습니다.'
    } else {
        Write-Host '나중에 작업 관리자에서 Windows 탐색기를 다시 시작하거나 로그아웃 후 로그인해 주세요.'
    }
}

$current = (Get-ItemProperty -Path $KeyPath -Name $Name -ErrorAction SilentlyContinue).$Name
Write-Host ("현재 값: {0}" -f (Show-Value $current))

if ($null -ne $current -and $current.Contains($Target)) {
    Write-Host '이미 Win+. 이 꺼져 있습니다. 변경하지 않습니다.'
    exit 0
}

$backup = Backup-Key
Write-Host "백업: $backup"

$new = if ($null -eq $current) { $Target } else { $current + $Target }

if ($null -eq $current) {
    New-ItemProperty -Path $KeyPath -Name $Name -PropertyType String -Value $new | Out-Null
} else {
    Set-ItemProperty -Path $KeyPath -Name $Name -Value $new
}

Write-Host ("변경 후 값: {0}" -f (Show-Value $new))
Restart-ExplorerPrompt
