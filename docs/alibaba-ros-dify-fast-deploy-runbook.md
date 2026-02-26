# Alibaba ROS Dify Panel Runbook (Fast Deploy, Auto-Network, Owner-IP Access)

This runbook implements the approved deployment posture:
- fast first deployment,
- auto-created VPC and vSwitch when the ROS template supports it,
- initial ingress restricted to owner IP/CIDR,
- immediate hardening after first successful validation.

## Scope

In scope:
- ROS console parameter selection sequence.
- VPC/vSwitch consistency checks.
- Security confirmations and SG exposure control.
- Deployment verification and immediate hardening.
- Failure triage for common ROS blockers.

Out of scope:
- Editing ROS template source.
- Dify app-level model/provider setup.
- Full HA re-architecture.

## Defaults and assumptions

- Region baseline: `China (Hangzhou)`.
- Network mode: auto-create VPC/vSwitch if template does not require existing IDs.
- Access mode: owner-IP-only for initial bring-up.
- No template code change in this run.

## Inputs to prepare before opening ROS

- `REGION_ID` (example: Hangzhou region code in your account).
- `OWNER_CIDR` (preferred: single public IP `/32`; use `/128` for IPv6).
- `ZONE_A` and `ZONE_B` (distinct zones when dual-zone is required).
- `INSTANCE_TYPE` (at least 8 vCPU and 16 GiB for Dify baseline).
- `ACK_INSTANCE_PASSWORD` (strong and policy compliant).

Helper:
- Use `scripts/get-owner-cidr.ps1` to generate `OWNER_CIDR` quickly.

## Phase 1: pre-flight checks

1. Confirm region is correct before stack creation.
2. Check ECS stock in candidate zones for your instance family.
3. Check quotas for ECS vCPU, EIP, VPC, and security groups.
4. Confirm owner CIDR value that will be used for ingress allowlist.

## Phase 2: ROS panel inputs

1. Compute and credentials
- Choose worker instance type at or above template recommendation.
- Set `Ack Instance Password` and store it securely.

2. Networking (auto-create path)
- If VPC/vSwitch selectors are absent, keep auto-create behavior.
- If zone selectors exist, choose two distinct zones.
- Validate CIDRs if shown:
  - VPC CIDR e.g. `/16`.
  - Two non-overlapping vSwitch CIDRs e.g. `192.168.1.0/24` and `192.168.2.0/24`.
  - Each vSwitch CIDR must be inside the VPC CIDR.

3. Security confirmations
- Tick all required ROS security confirmation checkboxes.
- Treat any `0.0.0.0/0` default ingress as temporary only.
- If the panel allows source CIDR override now, set it to `OWNER_CIDR`.

## Phase 3: preview and submit

1. Click `Preview Template Resources`.
2. Confirm expected resources are listed (typically ECS/ACK, SG, and optionally VPC/vSwitch/EIP).
3. Submit stack.
4. Start a cost guard loop for the first 15-30 minutes:
- Monitor every 5-10 minutes until status stabilizes.
- Optional helper: `scripts/ros-deploy-cost-guard.ps1`.

## Phase 4: first 15-minute verification

Deployment success criteria:
- ROS stack status is `CREATE_COMPLETE`.
- ECS/ACK compute is `Running` and health checks pass.
- Dify UI is reachable from owner CIDR.
- SSH (if required) is restricted to owner CIDR.
- Core Dify services are healthy.

## Phase 5: immediate hardening after first success

1. Security Group ingress
- Remove broad ingress (especially `0.0.0.0/0`) unless explicitly required.
- Keep only required ports and source CIDRs.
- Typical minimal first-pass rules:
  - `443/tcp` from `OWNER_CIDR`.
  - `80/tcp` from `OWNER_CIDR` only if HTTPS is not yet enabled.
  - `22/tcp` from `OWNER_CIDR` only if SSH is required.

2. Credentials
- Rotate temporary/shared password.
- Move to key-based admin access where applicable.

3. Cost controls
- Clean failed stacks and orphan ECS/EIP/disks/VPCs.
- Enable budget and alert thresholds.

Helper:
- Use `scripts/dify-sg-hardening-plan.ps1` to generate a concrete SG hardening plan payload.

## Failure triage playbook

1. Zone stock failure
- Symptom: ECS creation fails with insufficient capacity.
- Action: keep size, switch one or both zones, retry.

2. CIDR conflict
- Symptom: VPC/vSwitch creation conflict or overlap.
- Action: choose non-overlapping alternate CIDRs; ensure vSwitch CIDRs stay within VPC CIDR.

3. RAM/permission denial
- Symptom: stack fails creating role/policy/resources.
- Action: confirm security confirmations and account permissions; rerun.

4. Overexposed SG
- Symptom: service reachable publicly when not intended.
- Action: immediately narrow ingress to owner CIDR and required ports only.

5. Billing after failure
- Symptom: costs continue after failed deployment.
- Action: inspect resource list and remove leftovers manually.

## Acceptance checks

1. Deployment success test
- Stack reaches `CREATE_COMPLETE` with expected resources.

2. Network correctness test
- vSwitches belong to the stack VPC and CIDRs are non-overlapping.

3. Access control test
- Endpoint is reachable from owner CIDR and blocked from non-owner networks.

4. Service readiness test
- Dify UI and backend are healthy within 15 minutes.

5. Cleanup test
- No orphan billable resources remain after failed deployment cleanup.

## Operator command snippets

Use these local helper scripts from repo root:

```powershell
# 1) Discover your public owner CIDR
powershell -ExecutionPolicy Bypass -File .\\scripts\\get-owner-cidr.ps1 -CopyToClipboard
# If outbound endpoint lookups are blocked, pass it manually:
# powershell -ExecutionPolicy Bypass -File .\\scripts\\get-owner-cidr.ps1 -PublicIp "x.x.x.x" -CopyToClipboard

# 2) Start periodic deployment/cost checks (manual prompts)
powershell -ExecutionPolicy Bypass -File .\\scripts\\ros-deploy-cost-guard.ps1 -StackName "<stack-name>" -Region "cn-hangzhou"

# 3) Generate a security-group hardening plan payload
powershell -ExecutionPolicy Bypass -File .\\scripts\\dify-sg-hardening-plan.ps1 -OwnerCidr "x.x.x.x/32" -Region "cn-hangzhou" -StackName "<stack-name>" -OutputPath .\\sg-hardening-plan.json
```
