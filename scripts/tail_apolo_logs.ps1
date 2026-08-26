param(
    [string]$Path = "C:\apolo\logs\apolo.log",
    [int]$Tail = 120
)

if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    New-Item -ItemType File -Force -Path $Path | Out-Null
}

Get-Content -LiteralPath $Path -Tail $Tail -Wait
