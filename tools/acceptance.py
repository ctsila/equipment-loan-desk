"""Demonstrate checkout, tenant isolation and active-loan allowances over HTTP."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json

from client import LOANS, request


def require(condition, explanation):
    if not condition:
        raise AssertionError(explanation)


def item(asset_code, borrower_ref):
    return {'asset_code': asset_code, 'borrower_ref': borrower_ref}


class AcceptanceRun:
    def __init__(self, url):
        self.url = url
        self.evidence = {'started_utc': datetime.now(timezone.utc).isoformat(), 'url': url,
                         'results': {}, 'exchanges': []}

    def call(self, label, method, path, tenant=None, body=None, expected=200):
        response = request(self.url, method, path, tenant, body)
        self.evidence['exchanges'].append({'check': label, 'request': {'method': method, 'path': path,
            'tenant_credential': tenant, 'json': body}, 'expected_http': expected, 'response': response})
        require(response['status'] == expected, f"{label}: expected {expected}, received {response}")
        return response['json']

    def pass_check(self, key, text):
        self.evidence['results'][key] = text


def normal_use(run):
    call = run.call
    opened = {}
    for tenant in ('A', 'B'):
        initial = call(f'normal.{tenant}.initial', 'GET', LOANS, tenant)
        require(initial['loans'] == [] and initial['active'] == 0, 'Use a fresh Docker volume for this test')
        loan = call(f'normal.{tenant}.checkout', 'POST', LOANS, tenant, item('CAM-01', f'{tenant}-101'), 201)
        require(loan['tenant_id'] == tenant and loan['status'] == 'active' and loan['returned_at'] is None,
                'New loan should be owned and active')
        opened[tenant] = loan

    dup = call('normal.A.duplicate', 'POST', LOANS, 'A', item('CAM-01', 'A-102'), 409)
    require(dup == {'error': 'asset_already_checked_out'}, 'Same tenant double checkout should fail')

    for tenant, loan in opened.items():
        path = f"{LOANS}/{loan['id']}"
        require(call(f'normal.{tenant}.read', 'GET', path, tenant) == loan, 'Owned read differs from checkout')
        listing = call(f'normal.{tenant}.list_active', 'GET', LOANS, tenant)
        require(listing['loans'] == [loan] and listing['active'] == 1, 'Active list contains unexpected rows')
        returned = call(f'normal.{tenant}.return', 'POST', path+'/return', tenant)
        require(returned['status'] == 'returned' and returned['returned_at'] and returned['id'] == loan['id'],
                'Return must close the same loan')
        if tenant == 'A':
            retry = call('normal.A.return_retry', 'POST', path+'/return', tenant)
            require(retry == returned, 'Return retry changed the record')
        after = call(f'normal.{tenant}.history', 'GET', LOANS, tenant)
        require(after['active'] == 0 and after['loans'] == [returned], 'Return should free capacity and keep history')
    run.pass_check('normal', 'PASS: Both tenants checked out, read and returned CAM-01 in their own workspaces.')


def isolation(run):
    call = run.call
    owner = call('isolation.B.checkout', 'POST', LOANS, 'B', item('SOLDER-01', 'B-201'), 201)
    path = f"{LOANS}/{owner['id']}"
    before = call('isolation.B.before', 'GET', path, 'B')
    foreign = call('isolation.A.read', 'GET', path, 'A', expected=404)
    missing = call('isolation.A.unknown', 'GET', f'{LOANS}/{uuid4().hex}', 'A', expected=404)
    refused_return = call('isolation.A.return', 'POST', path+'/return', 'A', expected=404)
    after = call('isolation.B.after', 'GET', path, 'B')
    require(foreign == missing == refused_return == {'error': 'loan_not_found'}, 'Foreign lookup disclosed data')
    require(before == after == owner and after['returned_at'] is None, 'Tenant B loan changed')
    listing = call('isolation.A.list', 'GET', LOANS, 'A')
    require(all(row['tenant_id'] == 'A' and row['id'] != owner['id'] for row in listing['loans']),
            'Tenant A list included tenant B data')
    run.pass_check('isolation', 'PASS: A received 404 for B’s loan on read and return. B’s before and after records matched.')


def plan_limit(run):
    call = run.call
    first = call('limit.A.first', 'POST', LOANS, 'A', item('CAM-02', 'A-201'), 201)
    call('limit.A.second', 'POST', LOANS, 'A', item('MIC-01', 'A-202'), 201)
    before = call('limit.A.before', 'GET', LOANS, 'A')
    require((before['plan'], before['active'], before['limit']) == ('Starter', 2, 2), 'Starter did not reach 2/2')
    candidate = item('LIGHT-01', 'A-203')
    denial = call('limit.A.third', 'POST', LOANS, 'A', candidate, 409)
    require(denial == {'error': 'active_loan_limit_reached', 'plan': 'Starter', 'limit': 2, 'active': 2},
            'Unexpected quota error')
    require(call('limit.A.after', 'GET', LOANS, 'A') == before, 'Rejected checkout changed A’s list')

    call('limit.B.second', 'POST', LOANS, 'B', item('DRILL-01', 'B-202'), 201)
    call('limit.B.third', 'POST', LOANS, 'B', item('MULTI-01', 'B-203'), 201)
    b = call('limit.B.after', 'GET', LOANS, 'B')
    require((b['plan'], b['active'], b['limit']) == ('Plus', 3, 5), 'Plus did not reach 3/5')
    require(all(row['tenant_id'] == 'B' for row in b['loans']), 'Tenant B list included foreign rows')

    call('limit.A.free_slot', 'POST', f"{LOANS}/{first['id']}/return", 'A')
    available = call('limit.A.freed', 'GET', LOANS, 'A')
    require(available['active'] == 1 and len(available['loans']) == len(before['loans']),
            'Return should free one slot and preserve history')
    created = call('limit.A.retry_checkout', 'POST', LOANS, 'A', candidate, 201)
    require(created['status'] == 'active' and created['asset_code'] == 'LIGHT-01', 'Retried checkout did not create the requested loan')
    final = call('limit.A.final', 'GET', LOANS, 'A')
    require(final['active'] == 2 and len(final['loans']) == len(before['loans'])+1, 'New checkout did not reuse freed capacity')
    run.pass_check('limit', 'PASS: A’s third checkout was refused at 2/2. B reached 3/5. A reused a slot after a return.')


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--output', type=Path, default=Path('local-evidence/acceptance.json'))
    args = parser.parse_args()
    run = AcceptanceRun(args.url)
    try:
        run.call('health', 'GET', '/health')
        run.call('auth.missing_token', 'GET', LOANS, expected=401)
        run.call('auth.reject_owner_input', 'POST', LOANS, 'A',
                 {**item('FAKE-01', 'A-100'), 'tenant_id': 'B'}, 400)
        normal_use(run)
        isolation(run)
        plan_limit(run)
    except Exception as error:
        run.evidence['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(run.evidence, indent=2)+'\n', encoding='utf-8')
    for result in run.evidence['results'].values():
        print(result)
    print(f"Recorded {len(run.evidence['exchanges'])} HTTP exchanges in {args.output}")


if __name__ == '__main__':
    main()
