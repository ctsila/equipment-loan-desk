# Equipment Loan Desk

A small SaaS prototype for workshops that lend shared equipment. Staff can check out an item, view their workshop's loans and record a return. Cloud Computing Practical Works 5 and 6, ITMO University.

- [Lab 5 design](docs/DESIGN.md)
- [Lab 6 test results](docs/RESULTS.md)

## Build and start locally

Use Docker and Python 3.10 or later. The API and test scripts use the standard library. The initial database is empty and the two demo organisations are already configured.

```sh
git clone https://github.com/ctsila/equipment-loan-desk.git
cd equipment-loan-desk
docker pull python:3.12-slim
docker build --pull=false --network=none -t equipment-loan-desk:1 .
docker run --detach --name equipment-loan-desk \
  --publish 127.0.0.1:8080:8080 \
  --mount source=equipment-loans-demo,target=/data equipment-loan-desk:1
curl -fsS http://127.0.0.1:8080/health
```

The build can use a locally loaded base image. The named volume stores `loans.sqlite` and survives a container restart. The tokens below are public demo credentials for the service on localhost.

| Tenant | Fictional organisation | Plan | Maximum active loans | Bearer token |
| --- | --- | --- | ---: | --- |
| A | Northside Media Workshop | Starter | 2 | `demo-northside-token` |
| B | Westbank Makerspace | Plus | 5 | `demo-westbank-token` |

## Run the checks

Run the acceptance script first on a fresh volume. It creates the synthetic data it needs. It writes requests, statuses and JSON responses to `local-evidence/acceptance.json` and exits with an error if a check fails.

```sh
python3 tools/acceptance.py
docker restart equipment-loan-desk
curl -fsS http://127.0.0.1:8080/health
python3 tools/check_persistence.py
```

If the health request runs before the application has restarted, repeat it before running the persistence check. To repeat acceptance, stop and remove the demonstration container with `docker rm -f equipment-loan-desk`. Start it with a new volume name, such as `equipment-loans-demo-2`.

## Try the workflow manually

Start with room under the plan limit. Substitute the real `id` from the checkout response before reading or returning the loan. Each `asset_code` and `borrower_ref` is an uppercase reference of 1 to 32 letters, digits, underscores or hyphens, starting with a letter or digit.

```sh
API=http://127.0.0.1:8080
curl -sSi -H 'Authorization: Bearer demo-northside-token' \
  -H 'Content-Type: application/json' -d '{"asset_code":"CAM-09","borrower_ref":"A-901"}' \
  "$API/v1/loans"
curl -sSi -H 'Authorization: Bearer demo-northside-token' "$API/v1/loans"
ID='<id from the checkout response>'
curl -sSi -H 'Authorization: Bearer demo-northside-token' "$API/v1/loans/$ID"
curl -sSi -X POST -H 'Authorization: Bearer demo-northside-token' "$API/v1/loans/$ID/return"
```

The following uses Tenant B's own workspace and attempts to read A's loan. Compare the status from the last request with A's owned read above.

```sh
curl -sSi -H 'Authorization: Bearer demo-westbank-token' \
  -H 'Content-Type: application/json' -d '{"asset_code":"KIT-09","borrower_ref":"B-901"}' \
  "$API/v1/loans"
curl -sSi -H 'Authorization: Bearer demo-westbank-token' "$API/v1/loans"
curl -sSi -H 'Authorization: Bearer demo-westbank-token' "$API/v1/loans/$ID"
```

| Operation | Success | Relevant rejection |
| --- | --- | --- |
| `POST /v1/loans` | `201`, active loan with server-assigned owner | `409 active_loan_limit_reached` or `409 asset_already_checked_out` |
| `GET /v1/loans` | `200`, owned history and active usage | `401 invalid_token` |
| `GET /v1/loans/{id}` | `200`, owned loan | `404 loan_not_found` |
| `POST /v1/loans/{id}/return` | `200`, returned loan | `404 loan_not_found` |

An active loan occupies one slot. Returning it frees that slot and preserves the completed loan in history. Repeating a return produces the same record and return timestamp. Each tenant can use its own asset codes independently, and an asset can have only one active loan in that tenant.
