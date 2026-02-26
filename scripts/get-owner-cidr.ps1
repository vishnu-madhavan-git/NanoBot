param(
  [string]$PublicIp = "",
  [switch]$CopyToClipboard,
  [switch]$AsJson
)

$ErrorActionPreference = "Stop"

function Test-IPv4($value) {
  return $value -match '^(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})(?:\.(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}$'
}

function Test-IPv6($value) {
  return $value -match '^[0-9A-Fa-f:]+$' -and $value.Contains(':')
}

$endpoints = @(
  "https://api64.ipify.org?format=text",
  "https://ifconfig.me/ip",
  "https://icanhazip.com"
)

$ip = $null
if ($PublicIp) {
  $candidate = $PublicIp.Trim()
  if (Test-IPv4 $candidate -or Test-IPv6 $candidate) {
    $ip = $candidate
  }
  else {
    Write-Error "Invalid -PublicIp value: $PublicIp"
    exit 1
  }
}
else {
  foreach ($url in $endpoints) {
    try {
      $candidate = (Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 8).ToString().Trim()
      if (Test-IPv4 $candidate -or Test-IPv6 $candidate) {
        $ip = $candidate
        break
      }
    }
    catch {
      continue
    }
  }
}

if (-not $ip) {
  Write-Error "Unable to detect public IP from configured endpoints."
  exit 1
}

$cidr = if (Test-IPv4 $ip) { "$ip/32" } else { "$ip/128" }

if ($CopyToClipboard) {
  try {
    Set-Clipboard -Value $cidr
  }
  catch {
    Write-Warning "Failed to copy to clipboard: $($_.Exception.Message)"
  }
}

if ($AsJson) {
  [PSCustomObject]@{
    publicIp = $ip
    ownerCidr = $cidr
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json -Depth 5
  exit 0
}

Write-Output "Public IP : $ip"
Write-Output "Owner CIDR: $cidr"
if ($CopyToClipboard) {
  Write-Output "Copied owner CIDR to clipboard."
}
