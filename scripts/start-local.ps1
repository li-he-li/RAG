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

$backendArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload")
$frontendArgs = @("-m", "http.server", "3000", "--bind", "127.0.0.1", "--directory", "frontend")

$backendProc = Start-Process -FilePath $backendPython -ArgumentList $backendArgs -WorkingDirectory $backendDir -PassThru
$frontendProc = Start-Process -FilePath $frontendPython -ArgumentList $frontendArgs -WorkingDirectory $root -PassThru

Write-Host "Local mode started."
Write-Host "Frontend: http://127.0.0.1:3000/index.html (PID=$($frontendProc.Id))"
Write-Host "Backend:  http://127.0.0.1:8000/api/health (PID=$($backendProc.Id))"
Write-Host "Stop: Stop-Process -Id $($frontendProc.Id),$($backendProc.Id)"
