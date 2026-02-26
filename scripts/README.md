# ROS Dify helper scripts

These scripts support the Alibaba ROS Dify panel runbook in `docs/alibaba-ros-dify-fast-deploy-runbook.md`.

## 1) get-owner-cidr.ps1

Generates a single-owner CIDR suitable for initial SG allowlisting.

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\get-owner-cidr.ps1 -CopyToClipboard
```

If external IP lookup endpoints are blocked, provide your IP manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\get-owner-cidr.ps1 -PublicIp "x.x.x.x" -CopyToClipboard
```

## 2) ros-deploy-cost-guard.ps1

Prints periodic operator reminders during first deployment to reduce unnoticed cost leakage.

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\ros-deploy-cost-guard.ps1 -StackName "<stack-name>" -Region "cn-hangzhou"
```

## 3) dify-sg-hardening-plan.ps1

Produces a JSON payload describing owner-only SG hardening rules and checklist.

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\dify-sg-hardening-plan.ps1 -OwnerCidr "x.x.x.x/32" -Region "cn-hangzhou" -StackName "<stack-name>" -OutputPath .\\sg-hardening-plan.json
```

This script does not modify Alibaba resources directly; it generates an operator-ready plan payload.
