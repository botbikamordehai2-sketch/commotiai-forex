param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("acquire", "release")]
    [string]$Action,

    [string]$ProcessName = "unknown"
)

$ErrorActionPreference = "Stop"

$LockPath = Join-Path $PSScriptRoot "api_fetch.lock"
$MetadataPath = Join-Path $LockPath "metadata.txt"
$MaxAgeMinutes = 10

function Get-LockAgeMinutes {
    if (Test-Path $MetadataPath) {
        $metadata = Get-Content $MetadataPath -ErrorAction SilentlyContinue
        $startedLine = $metadata |
            Where-Object { $_ -like "started_at_utc=*" } |
            Select-Object -First 1

        if ($startedLine) {
            $startedText = $startedLine -replace "^started_at_utc=", ""

            try {
                $startedAt = [datetime]::Parse(
                    $startedText,
                    [Globalization.CultureInfo]::InvariantCulture,
                    [Globalization.DateTimeStyles]::RoundtripKind
                ).ToUniversalTime()

                return (([datetime]::UtcNow - $startedAt).TotalMinutes)
            }
            catch {
            }
        }
    }

    $lockItem = Get-Item $LockPath
    return (([datetime]::UtcNow - $lockItem.LastWriteTimeUtc).TotalMinutes)
}

if ($Action -eq "acquire") {
    try {
        New-Item -ItemType Directory -Path $LockPath -ErrorAction Stop |
            Out-Null

        @(
            "pid=$PID"
            "started_at_utc=$([datetime]::UtcNow.ToString('o'))"
            "process=$ProcessName"
        ) | Set-Content -Path $MetadataPath -Encoding UTF8

        Write-Output (
            "API_LOCK_ACQUIRED pid=$PID process=$ProcessName " +
            "started_at_utc=$([datetime]::UtcNow.ToString('o'))"
        )

        exit 0
    }
    catch {
        if (-not (Test-Path $LockPath)) {
            Write-Output "API_LOCK_ERROR unable_to_create_lock"
            exit 1
        }
    }

    $ageMinutes = Get-LockAgeMinutes

    if ($ageMinutes -lt $MaxAgeMinutes) {
        Write-Output (
            "API_LOCK_BUSY action=SKIP " +
            "age_minutes=$([math]::Round($ageMinutes, 2)) " +
            "max_age_minutes=$MaxAgeMinutes"
        )

        exit 2
    }

    Write-Output (
        "API_LOCK_STALE removing_lock " +
        "age_minutes=$([math]::Round($ageMinutes, 2)) " +
        "max_age_minutes=$MaxAgeMinutes"
    )

    try {
        Remove-Item -Path $LockPath -Recurse -Force -ErrorAction Stop
        New-Item -ItemType Directory -Path $LockPath -ErrorAction Stop |
            Out-Null

        @(
            "pid=$PID"
            "started_at_utc=$([datetime]::UtcNow.ToString('o'))"
            "process=$ProcessName"
        ) | Set-Content -Path $MetadataPath -Encoding UTF8

        Write-Output (
            "API_LOCK_ACQUIRED_AFTER_STALE pid=$PID " +
            "process=$ProcessName"
        )

        exit 0
    }
    catch {
        Write-Output "API_LOCK_ERROR unable_to_replace_stale_lock"
        exit 1
    }
}

if ($Action -eq "release") {
    if (-not (Test-Path $LockPath)) {
        Write-Output "API_LOCK_RELEASE_NOT_NEEDED lock_missing"
        exit 0
    }

    try {
        Remove-Item -Path $LockPath -Recurse -Force -ErrorAction Stop
        Write-Output "API_LOCK_RELEASED process=$ProcessName"
        exit 0
    }
    catch {
        Write-Output "API_LOCK_ERROR unable_to_release_lock"
        exit 1
    }
}