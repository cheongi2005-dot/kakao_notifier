param()
$ErrorActionPreference = "Stop"
$tmp = $env:TEMP

Write-Host "[1/2] Downloading Python 3.13..."
(New-Object System.Net.WebClient).DownloadFile(
    "https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe",
    "$tmp\python-installer.exe"
)

Write-Host "[2/2] Installing Python..."
$p = Start-Process -FilePath "$tmp\python-installer.exe" `
    -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0" `
    -Wait -PassThru
Remove-Item "$tmp\python-installer.exe" -Force

if ($p.ExitCode -ne 0) {
    Write-Host "ERROR: installer exited with code $($p.ExitCode)"
    exit 1
}

Write-Host "Python setup complete."
