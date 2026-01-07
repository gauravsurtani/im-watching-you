# ActivityWatch Export Script for Windows
# Run via Task Scheduler for automatic exports
#
# Task Scheduler setup:
# 1. Open Task Scheduler
# 2. Create Basic Task
# 3. Trigger: Daily or at specific times
# 4. Action: Start a program
# 5. Program: powershell.exe
# 6. Arguments: -ExecutionPolicy Bypass -File "C:\path\to\export_activitywatch.ps1"

param(
    [string]$OutputDir = "$env:USERPROFILE\Syncthing\lifelogger\activity",
    [string]$Host = "localhost",
    [int]$Port = 5600,
    [string]$DeviceId = $env:COMPUTERNAME.ToLower()
)

$ErrorActionPreference = "Stop"

$ApiUrl = "http://${Host}:${Port}/api/0"
$Today = Get-Date -Format "yyyy-MM-dd"
$OutputPath = Join-Path $OutputDir $DeviceId
$OutputFile = Join-Path $OutputPath "$Today.json"

# Ensure output directory exists
New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null

try {
    # Fetch buckets
    $BucketsResponse = Invoke-RestMethod -Uri "$ApiUrl/buckets" -Method Get -TimeoutSec 10

    $AllEvents = @()
    $BucketInfo = @{}

    foreach ($BucketId in $BucketsResponse.PSObject.Properties.Name) {
        $Bucket = $BucketsResponse.$BucketId
        $WatcherType = $Bucket.type

        # Only export relevant watchers
        if ($WatcherType -notmatch "window|web|afk") {
            continue
        }

        $StartDate = (Get-Date).Date.ToUniversalTime().ToString("o")
        $EndDate = (Get-Date).Date.AddDays(1).ToUniversalTime().ToString("o")

        try {
            $Events = Invoke-RestMethod -Uri "$ApiUrl/buckets/$BucketId/events?start=$StartDate&end=$EndDate&limit=-1" -Method Get -TimeoutSec 30

            if ($Events.Count -gt 0) {
                $AllEvents += $Events
                $BucketInfo[$BucketId] = @{
                    type = $WatcherType
                    event_count = $Events.Count
                }
            }
        }
        catch {
            Write-Warning "Failed to fetch $BucketId : $_"
        }
    }

    # Create export object
    $Export = @{
        device_id = $DeviceId
        hostname = $env:COMPUTERNAME
        export_date = $Today
        exported_at = (Get-Date).ToUniversalTime().ToString("o")
        buckets = $BucketInfo
        events = $AllEvents
    }

    # Write to file
    $Export | ConvertTo-Json -Depth 10 | Set-Content -Path $OutputFile -Encoding UTF8

    Write-Host "Exported $Today -> $OutputFile"
}
catch {
    Write-Error "Export failed: $_"
    exit 1
}
