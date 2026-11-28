<#
Registers a Windows scheduled task on the RESEARCH machine that runs a stage B session
on a fixed schedule (proposal: "Monthly research sessions, each with a time cap and a
dollar cap"; given the $250/yr break-even at $5k, the default here is quarterly).

Each run: one drill round (planted bad strategies through every defence), then a
research session with the given idea and dollar caps, then the pending queue. The
monthly cap in research/agent/config.py still applies on top.

Run it yourself in PowerShell from the repo root (no admin needed for your own user):
    powershell -ExecutionPolicy Bypass -File deploy\windows\schedule_research.ps1
    powershell -ExecutionPolicy Bypass -File deploy\windows\schedule_research.ps1 -Months 1 -Ideas 10 -BudgetUsd 5
Remove it:
    schtasks /Delete /TN "Quant research session" /F

Needs: ANTHROPIC_API_KEY set as a user environment variable (setx), the `anthropic`
package, Docker in WSL with the sandbox image built. The task runs only while you're
logged on, so it can reach WSL.
#>
param(
    [int]$Months = 3,            # 1 = monthly, 3 = quarterly
    [int]$Ideas = 10,
    [double]$BudgetUsd = 5,
    [int]$Day = 1,
    [string]$Time = "09:00",
    [string]$Python = "C:\Python313\python.exe"
)

$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$wrapper = Join-Path $repo "deploy\windows\research_session.cmd"
$log = Join-Path $repo "research\agent\state\scheduled_runs.log"

schtasks /Create /F /TN "Quant research session" /SC MONTHLY /MO $Months /D $Day /ST $Time `
    /TR "`"$wrapper`" $Ideas $BudgetUsd `"$Python`""
if ($LASTEXITCODE -eq 0) {
    Write-Host "Scheduled: every $Months month(s) on day $Day at $Time, $Ideas ideas, `$$BudgetUsd cap. Log: $log"
}
