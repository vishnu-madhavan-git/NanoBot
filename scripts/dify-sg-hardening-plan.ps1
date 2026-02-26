param(
  [Parameter(Mandatory = $true)]
  [string]$OwnerCidr,

  [string]$Region = "cn-hangzhou",
  [string]$StackName = "",

  [string[]]$AllowedTcpPorts = @("443", "80", "22"),

  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

function Test-Cidr($value) {
  return $value -match '^.+\/[0-9]{1,3}$'
}

function Normalize-Cidr($value) {
  if (Test-Cidr $value) {
    return $value
  }

  if ($value -match '^(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})(?:\.(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}$') {
    return "$value/32"
  }

  if ($value -match '^[0-9A-Fa-f:]+$' -and $value.Contains(':')) {
    return "$value/128"
  }

  throw "Invalid OwnerCidr. Provide IPv4/IPv6 or CIDR."
}

$owner = Normalize-Cidr $OwnerCidr

$rules = @()
foreach ($port in $AllowedTcpPorts) {
  if ($port -notmatch '^[0-9]{1,5}$') {
    throw "Invalid TCP port value: $port"
  }

  $rules += [PSCustomObject]@{
    IpProtocol = "tcp"
    PortRange = "$port/$port"
    SourceCidr = $owner
    Policy = "accept"
    Priority = 1
    Description = "dify-owner-only-$port"
  }
}

$plan = [PSCustomObject]@{
  generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
  region = $Region
  stackName = $StackName
  ownerCidr = $owner
  removeBroadRules = @("0.0.0.0/0", "::/0")
  ingressRules = $rules
  checklist = @(
    "Find Security Group attached to Dify ECS/ACK resources.",
    "Remove broad ingress rules (0.0.0.0/0 and ::/0) unless explicitly required.",
    "Add owner-only ingress rules from this payload.",
    "Validate endpoint is reachable from owner CIDR and blocked from non-owner networks.",
    "If temporary password was used, rotate it and prefer key-based access."
  )
}

$json = $plan | ConvertTo-Json -Depth 8

if ($OutputPath) {
  $dir = Split-Path -Parent $OutputPath
  if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  $json | Out-File -FilePath $OutputPath -Encoding utf8
  Write-Output "Wrote SG hardening plan: $OutputPath"
}

Write-Output $json
