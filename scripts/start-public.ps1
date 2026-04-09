$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $root "backend"

$backendPython = if ($env:LEGAL_BACKEND_PYTHON) { $env:LEGAL_BACKEND_PYTHON } else { "D:\Anaconda\envs\legal-search\python.exe" }
$frontendPython = if ($env:LEGAL_FRONTEND_PYTHON) { $env:LEGAL_FRONTEND_PYTHON } else { "D:\Anaconda\python.exe" }

if (!(Test-Path $backendPython)) {
  throw "Backend python not found: $backendPython"
}
if (!(Test-Path $frontendPython)) {
  throw "Frontend python not found: $frontendPython"
}

$backendArgs = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000")
$frontendArgs = @("-m", "http.server", "3000", "--bind", "0.0.0.0", "--directory", "frontend")

$backendProc = Start-Process -FilePath $backendPython -ArgumentList $backendArgs -WorkingDirectory $backendDir -PassThru
$frontendProc = Start-Process -FilePath $frontendPython -ArgumentList $frontendArgs -WorkingDirectory $root -PassThru

Write-Host "Public mode started."
Write-Host "LAN Frontend: http://<your-lan-ip>:3000/index.html (PID=$($frontendProc.Id))"
Write-Host "LAN Backend:  http://<your-lan-ip>:8000/api/health (PID=$($backendProc.Id))"
Write-Host "If using router NAT, forward TCP 3000 and 8000 to this machine."
Write-Host "Stop: Stop-Process -Id $($frontendProc.Id),$($backendProc.Id)"
