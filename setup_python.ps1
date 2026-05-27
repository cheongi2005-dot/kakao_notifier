param()
$ErrorActionPreference = "Stop"
$dest = Join-Path $PSScriptRoot "python-embed"
$tmp  = $env:TEMP

Write-Host "[1/4] Downloading Python 3.13 embeddable..."
Invoke-WebRequest "https://www.python.org/ftp/python/3.13.3/python-3.13.3-embed-amd64.zip" `
    -OutFile "$tmp\py-embed.zip" -UseBasicParsing

Write-Host "[2/4] Extracting..."
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
Expand-Archive "$tmp\py-embed.zip" $dest -Force
Remove-Item "$tmp\py-embed.zip" -Force

Write-Host "[3/4] Enabling pip..."
$pth = Get-ChildItem "$dest\python3*._pth" | Select-Object -First 1
(Get-Content $pth.FullName -Raw) -replace '#import site','import site' |
    Set-Content $pth.FullName -Encoding UTF8

Write-Host "[4/4] Installing pip..."
Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" `
    -OutFile "$tmp\get-pip.py" -UseBasicParsing
$env:PYTHONHOME = ""
$env:PYTHONPATH = ""
& "$dest\python.exe" "$tmp\get-pip.py" --no-warn-script-location
Remove-Item "$tmp\get-pip.py" -Force

Write-Host "Python setup complete."
