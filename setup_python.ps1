param()
$ErrorActionPreference = "Stop"
$tmp = $env:TEMP

Write-Host "[1/2] Downloading Python 3.13..."
Invoke-WebRequest "https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe" `
    -OutFile "$tmp\python-installer.exe" -UseBasicParsing

Write-Host "[2/2] Installing Python..."
$p = Start-Process -FilePath "$tmp\python-installer.exe" `
    -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0" `
    -Wait -PassThru
Remove-Item "$tmp\python-installer.exe" -Force

if ($p.ExitCode -ne 0) {
    Write-Host "ERROR: installer exited with code $($p.ExitCode)"
    exit 1
}

# Find where Python actually installed
$pyExe = $null
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "C:\Python313\python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $pyExe = $c; break }
}

if (-not $pyExe) {
    foreach ($ver in @("3.13","3.12","3.11")) {
        $reg = Get-ItemProperty "HKCU:\Software\Python\PythonCore\$ver\InstallPath" -ErrorAction SilentlyContinue
        if ($reg) {
            $base = $reg."(default)"
            if (-not $base) { $base = $reg.InstallPath }
            if ($base -and (Test-Path "$base\python.exe")) {
                $pyExe = "$base\python.exe"; break
            }
        }
    }
}

if (-not $pyExe) {
    Write-Host "ERROR: python.exe not found after install"
    exit 1
}

Write-Host "Python found: $pyExe"
[System.IO.File]::WriteAllText("$tmp\kakao_pyexe.txt", $pyExe, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Python setup complete."
