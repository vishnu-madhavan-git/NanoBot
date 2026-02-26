param(
  [Parameter(Mandatory = $true)]
  [string]$StackName,

  [Parameter(Mandatory = $true)]
  [string]$Region,

  [ValidateRange(1, 30)]
  [int]$IntervalMinutes = 5,

  [ValidateRange(1, 24)]
  [int]$Checks = 6
)

$ErrorActionPreference = "Stop"

$start = Get-Date
Write-Output "ROS deploy cost guard started at $($start.ToString('u'))"
Write-Output "Stack: $StackName"
Write-Output "Region: $Region"
Write-Output "Checks: $Checks, every $IntervalMinutes minute(s)"
Write-Output ""

for ($i = 1; $i -le $Checks; $i++) {
  $now = Get-Date
  Write-Output "[$($now.ToString('u'))] Check $i/$Checks"
  Write-Output "- Validate ROS stack status (expected: CREATE_COMPLETE)."
  Write-Output "- Validate ECS/ACK health checks are passing."
  Write-Output "- Validate Dify endpoint access from owner CIDR only."
  Write-Output "- If failed, inspect and delete orphan ECS/EIP/disk resources."

  if ($i -lt $Checks) {
    Start-Sleep -Seconds ($IntervalMinutes * 60)
  }
}

$end = Get-Date
$elapsed = New-TimeSpan -Start $start -End $end
Write-Output ""
Write-Output "Cost guard finished at $($end.ToString('u'))"
Write-Output "Elapsed: $($elapsed.ToString())"
