# Lab 6 — Equipment Loan Desk results

The image was built and run in Docker on 18 November 2026. All three required checks passed in 36 HTTP exchanges. An additional restart check compared the complete loan lists for both tenants.

| Parameter | Value |
| --- | --- |
| VM | CC-PW56, VirtualBox 7.2.22, 1 vCPU, 2 GiB RAM, 8 GiB virtual disk |
| Guest | Alpine Linux 3.24.3, Linux kernel 6.18.58-0-virt, x86-64 |
| Docker | 29.9.3 client and server |
| Container | Python 3.12.16, SQLite 3.46.1, Linux/amd64 |
| Image | `equipment-loan-desk:1`, `sha256:4859a0637ea761a14bd290e50aa323be20ab42744ab8700dd456cacc8dcc560b` |
| Data volume | `loan-evidence-20261118140052`, mounted at `/data` |

## Acceptance results

| Check | Expected | Observed |
| --- | --- | --- |
| Normal use | A and B independently check out, view and return an item. Each history retains the returned loan. | **Pass.** Both checkouts returned `201`. Owned read, list and return requests returned `200`. Both moved from one active loan to zero with one returned record. The same `CAM-01` code worked under both tenants. A second active loan for A's own `CAM-01` returned `409 asset_already_checked_out`. Repeating A's return preserved the original timestamp. |
| Tenant isolation | A cannot read or return B's loan. B's loan stays active and unchanged. | **Pass.** Both attempts using A's token returned `404 loan_not_found`, the same error returned for a random ID. B received `200` before and after with identical bodies. A's list contained only its own records. |
| Plan limit | A's third active loan fails at 2/2, B's third succeeds and A can reuse a freed slot. | **Pass.** A received `409 active_loan_limit_reached` and its complete list was unchanged. B received `201` for its third checkout and reached 3/5. A returned one loan, dropped to 1/2, and the same previously refused checkout then returned `201`. |

After `docker restart equipment-loan-desk`, A still had two active loans out of four rows, and B still had three active loans out of four rows. The complete `GET /v1/loans` response for each tenant was equal to its pre-restart response, including returned rows and timestamps.

## Implementation refinements

The prototype follows the design workflow and uses the same tenant scopes and plan allowances. Implementation uses a tenant-specific SQLite uniqueness constraint for active assets and a transaction for allowance enforcement. The test scripts record an explicit return retry, demonstrate reuse of capacity and compare the stored records across a restart.

## Evidence

- [All acceptance requests and responses](../evidence/acceptance.json)
- [Environment and verified source hashes](../evidence/environment.txt), [Build log](../evidence/build.txt) and [Container start](../evidence/docker-run.txt)
- [Records before and after restart](../evidence/persistence.json) and [Restart output](../evidence/restart.txt)
- VM screenshots of [Normal use](../evidence/screenshots/02-normal.png), [Isolation](../evidence/screenshots/03-isolation.png), [Plan limit](../evidence/screenshots/04-limit.png) and [Persistence](../evidence/screenshots/05-persistence.png). The Word report also shows the Docker build and health check.
