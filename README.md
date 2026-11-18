# IT Equipment Desk

A small internal request portal for mice, second monitors, keyboards and USB flash drives. An employee sends a request to their direct manager. After manager approval it goes to the IT team for the employee’s office. The manager or IT can decline at their step by giving a reason that the employee can see. This prototype uses two fictional companies and synthetic accounts for Cloud Computing Practical Works 5 and 6.

- [Lab 5 design](docs/DESIGN.md)
- [Lab 6 results](docs/RESULTS.md)

## Run locally

Use Docker and Python 3.10 or newer for the acceptance script. The service has no Python package dependencies.

```sh
git clone --branch it-equipment-desk https://github.com/ctsila/equipment-loan-desk.git it-equipment-desk
cd it-equipment-desk
docker pull python:3.12-slim
docker build --pull=false --network=none -t it-equipment-desk:1 .
docker run --detach --name it-equipment-desk --publish 127.0.0.1:8080:8080 \
  --mount source=it-desk-demo,target=/data it-equipment-desk:1
```

Open `http://127.0.0.1:8080/`. The first run creates an empty database in `it-desk-demo`. The account switcher uses public, preconfigured **demo** tokens. Use these synthetic profiles in the form.

| Company | Employee and ID | Office | Assigned manager | IT team |
| --- | --- | --- | --- | --- |
| A · Northstar Services | Alex Morgan · `A101` | Berlin | Nora Weber | Berlin IT |
| A · Northstar Services | Priya Rao · `A102` | Singapore | Daniel Lee | Singapore IT |
| B · Horizon Design | Maya Lim · `B201` | Singapore | Riley Chen | Singapore IT |

For example, select Alex and request a second monitor. Enter `Alex Morgan`, `A101`, Berlin, and a reason such as “I need a second screen to compare tickets with system logs.” Submit, select Nora Weber and approve. Select Berlin IT under Northstar and approve again. Switch back to Alex to see the final status. Horizon’s Singapore IT is a separate account from Northstar’s Singapore IT.

To try a decline, submit another request. In the manager’s queue choose **Decline**, explain the decision and click **Confirm decline**. The request closes without going to IT. For an IT decline, approve a new request as the manager and then follow the same steps in the local IT queue. The employee can see the comment next to the reviewer who declined.

## API and checks

```sh
curl -fsS http://127.0.0.1:8080/health
curl -fsS -H 'Authorization: Bearer demo-alex' http://127.0.0.1:8080/v1/requests
curl -fsS -H 'Authorization: Bearer demo-maya' http://127.0.0.1:8080/v1/requests
```

`POST /v1/requests` accepts `equipment`, `employee_name`, `employee_id`, `office` and `reason`. `GET /v1/requests/{id}` retrieves a scoped record. The assigned manager and correct IT account use `POST /v1/requests/{id}/decision` with `{"decision":"approve"}` or `{"decision":"reject","note":"Your current keyboard can be repaired."}`. A decline requires a non-blank note of up to 200 characters. A missing or blank note returns `400 decline_reason_required` and leaves the request in its current stage. The API represents a declined request with status `rejected`. Account tokens and office assignments are in [accounts.json](accounts.json).

Run `python3 tools/acceptance.py` against a fresh database. The runner creates synthetic requests and saves the exchanges in `local-evidence/acceptance.json`. Use a separate fresh volume for this run if the form already has records. To start with a different volume, remove the demo container and rerun the Docker command with a new volume name.

## Evidence

The [evidence folder](evidence/) contains the VM build, server startup, browser actions and HTTP exchanges. Lab 6 includes screenshots of the form, review queues and employee status.
