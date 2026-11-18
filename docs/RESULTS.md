# Lab 6 — IT Equipment Desk results

The Docker run on 18 November 2026 passed all three assignment checks and both decline paths across 68 HTTP exchanges. A second container with a fresh volume served the browser demonstration from the same image.

| Check | Expected | Observed |
| --- | --- | --- |
| Normal use | Each company can submit a request and complete both approvals in order. | Northstar completed one request in Berlin and another in Singapore. Horizon completed one in Singapore. The requests went through `pending_manager`, `pending_it` and `approved`. IT attempts before manager approval got 409. An unassigned manager and the wrong IT office got 404. |
| Tenant isolation | A cannot read or approve B’s request, and B can still retrieve it. | A’s employee, manager and Singapore IT attempts got 404. B’s before and after records matched and the request still awaited IT. |
| Plan limit | Starter blocks its next request at 2/2. Plus permits a third. | Northstar reached 2/2 across its two offices, and its third submission got 409 with no change. Horizon’s third got 201 and reached 3/5. After IT declined an open request, Northstar retried successfully. |
| Decline with explanation | Missing comments leave requests pending. A valid comment closes the request and is visible to the employee. | A missing manager comment and a whitespace-only IT comment each returned 400. Both requests stayed in their stage. Each decline with a reason returned 200. The keyboard request skipped IT after the manager declined. The USB drive request retained its manager approval after IT declined it. |

The server rejected a missing employee ID, a short reason and a mismatched office with HTTP 400. In the browser I submitted and approved a second monitor at both steps. I also declined a keyboard as Nora Weber and a USB flash drive as Berlin IT after Nora approved it. Alex’s request list showed both decline explanations under the reviewer who entered them.

The workflow and limits follow the Lab 5 design. I used one account file for the demo identities and office assignments, then added separate browser views for employees, managers and IT. I put the decline form inside the review card so the reviewer could still see the request while writing the reason.

## Recorded evidence

- [Build](../evidence/build.txt), [VM and source hashes](../evidence/environment.txt), [Running container](../evidence/container.txt)
- [Input validation](../evidence/validation.json), [Northstar Berlin](../evidence/northstar-berlin.json), [Northstar Singapore](../evidence/northstar-singapore.json), [Horizon Singapore](../evidence/horizon-singapore.json)
- [Tenant isolation](../evidence/tenant-isolation.json), [Plan limit](../evidence/plan-limit.json), [Decline checks](../evidence/declines.json), [Browser flow](../evidence/browser-flow.json)
