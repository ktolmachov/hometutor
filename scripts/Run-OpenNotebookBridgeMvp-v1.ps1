# Run-OpenNotebookBridgeMvp-v1.ps1
# Runs sample OpenNotebook -> HomeTutor Bridge MVP flow.

#requires -Version 5.1

[CmdletBinding()]
param(
    [string]$HomeTutorRoot = "D:\Projects\hometutor",
    [string]$ReportDir = "D:\AI\logs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location $HomeTutorRoot
try {
    Write-Host "OPEN_NOTEBOOK_BRIDGE_MVP_START" -ForegroundColor Cyan

    python .\tests\test_open_notebook_manifest.py `
      --pack .\examples\open_notebook_export_sample

    python .\scripts\import_open_notebook_pack.py `
      --pack .\examples\open_notebook_export_sample `
      --hometutor-root . `
      --target-corpus open_notebook `
      --report-dir $ReportDir

    python .\scripts\run_open_notebook_bridge_gate_v1.py `
      --hometutor-root . `
      --cases .\eval_data\open_notebook_bridge\open_notebook_bridge_cases_v1.json `
      --report-dir $ReportDir

    Write-Host "OPEN_NOTEBOOK_BRIDGE_MVP=PASS" -ForegroundColor Green
}
finally {
    Pop-Location
}
