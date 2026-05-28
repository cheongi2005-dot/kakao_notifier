$dir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV  = "C:\Users\Public\kakao_notifier_venv"
$env:PLAYWRIGHT_BROWSERS_PATH = "C:\Users\Public\kakao_pw_browsers"
$env:PYTHONHOME = ""
$env:PYTHONPATH = ""

# uv 있으면 우선 사용
if (Get-Command uv -ErrorAction SilentlyContinue) {
    if (-not (Test-Path "$VENV\Scripts\python.exe")) {
        & uv venv --seed $VENV | Out-Null
        & "$VENV\Scripts\python.exe" -m playwright install chromium | Out-Null
    }
    & "$VENV\Scripts\python.exe" -m pip install -q -r "$dir\requirements.txt" 2>$null
    Start-Process "$VENV\Scripts\pythonw.exe" -ArgumentList "`"$dir\ui.py`""
    exit
}

# Python 실행 파일 탐색
$PYEXE = $null
$pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($pyCmd) {
    & python -c "import sys; exit(0 if sys.version_info>=(3,11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $PYEXE = $pyCmd }
}
foreach ($p in @(
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
)) { if (-not $PYEXE -and (Test-Path $p)) { $PYEXE = $p; break } }

if (-not $PYEXE) {
    foreach ($v in '3.13','3.12','3.11') {
        try {
            $r = Get-ItemProperty "HKCU:\Software\Python\PythonCore\$v\InstallPath" -EA Stop
            $b = if ($r.'(default)') { $r.'(default)' } else { $r.InstallPath }
            if ($b -and (Test-Path "${b}python.exe")) { $PYEXE = "${b}python.exe"; break }
        } catch {}
    }
}

if (-not $PYEXE) {
    Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$dir\setup_python.ps1`"" -Wait -WindowStyle Hidden
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )) { if (Test-Path $p) { $PYEXE = $p; break } }
}

if (-not $PYEXE) { exit 1 }

# venv 없으면 생성
if (-not (Test-Path "$VENV\Scripts\python.exe")) {
    & $PYEXE -m venv $VENV | Out-Null
    & "$VENV\Scripts\python.exe" -m playwright install chromium | Out-Null
}

# 패키지 업데이트 (조용히)
& "$VENV\Scripts\pip.exe" install -q -r "$dir\requirements.txt" 2>$null

# 앱 실행 (창 없음)
Start-Process "$VENV\Scripts\pythonw.exe" -ArgumentList "`"$dir\ui.py`""
