"""Exercise the demo through the same HTTP API used by the web interface."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json


REQUESTS = '/v1/requests'
ACCOUNTS = json.loads((Path(__file__).resolve().parents[1]/'accounts.json').read_text())
DEMO = {account['token']: account for account in ACCOUNTS}


def order(token, equipment):
    account = DEMO[token]
    return {'equipment': equipment, 'employee_name': account['name'], 'employee_id': account['id'],
            'office': account['office'], 'reason': f'I need a {equipment.lower()} for my regular workstation tasks.'}


class Run:
    def __init__(self, url):
        self.url = url.rstrip('/')
        self.evidence = {'started_utc': datetime.now(timezone.utc).isoformat(), 'url': self.url,
                         'results': {}, 'exchanges': []}

    def call(self, key, method, path, token=None, payload=None, expected=200):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer '+token
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.url+path, method=method, headers=headers, data=data)
        try:
            response = urlopen(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            status, body = response.status, json.load(response)
        self.evidence['exchanges'].append({'check': key, 'method': method, 'path': path,
                                          'account': token, 'request': payload, 'expected_http': expected,
                                          'http': status, 'response': body})
        assert status == expected, (key, expected, status, body)
        return body

    def submit(self, key, token, equipment, expected=201):
        return self.call(key, 'POST', REQUESTS, token, order(token, equipment), expected)

    def decide(self, key, token, item, decision='approve', expected=200, *, note=None):
        payload = {'decision': decision}
        if note is not None:
            payload['note'] = note
        return self.call(key, 'POST', f"{REQUESTS}/{item['id']}/decision", token, payload, expected)


def validation(run):
    call = run.call
    call('validation.health', 'GET', '/health')
    call('validation.unauthenticated', 'GET', REQUESTS, expected=401)
    input_data = order('demo-alex', 'Second monitor')
    missing_id = dict(input_data)
    del missing_id['employee_id']
    assert call('validation.missing_id', 'POST', REQUESTS, 'demo-alex', missing_id, 400)['error'] == 'invalid_fields'
    assert call('validation.short_reason', 'POST', REQUESTS, 'demo-alex', {**input_data, 'reason':'Need it'}, 400)['error'] == 'reason_too_short_or_long'
    assert call('validation.wrong_office', 'POST', REQUESTS, 'demo-alex', {**input_data, 'office':'Singapore'}, 400)['error'] == 'profile_mismatch'
    assert call('validation.empty_a', 'GET', REQUESTS, 'demo-alex')['requests'] == []
    assert call('validation.empty_b', 'GET', REQUESTS, 'demo-maya')['requests'] == []


def normal(run, label, employee, manager, it, equipment, wrong_manager=None, wrong_it=None):
    prefix = 'normal.'+label
    token = DEMO[employee]
    item = run.submit(prefix+'.submit', employee, equipment)
    assert item['status'] == 'pending_manager' and item['manager_id'] == DEMO[manager]['id']
    assert item['employee_id'] == token['id'] and item['office'] == DEMO[it]['office']
    assert item['region'] == ('Europe' if token['office'] == 'Berlin' else 'Asia')
    queue = run.call(prefix+'.manager_queue', 'GET', REQUESTS, manager)
    assert item in queue['requests']
    it_queue = run.call(prefix+'.it_before', 'GET', REQUESTS, it)
    assert item['id'] not in [row['id'] for row in it_queue['requests']]
    assert run.decide(prefix+'.it_early', it, item, expected=409) == {'error':'wrong_approval_stage'}
    if wrong_manager:
        assert run.decide(prefix+'.wrong_manager', wrong_manager, item, expected=404) == {'error':'request_not_found'}
    interim = run.decide(prefix+'.manager_approves', manager, item)
    assert interim['status'] == 'pending_it' and interim['manager_decision'] == 'approve' and interim['manager_at']
    assert interim['it_decision'] is None
    assert interim in run.call(prefix+'.it_queue', 'GET', REQUESTS, it)['requests']
    if wrong_it:
        assert run.decide(prefix+'.wrong_it', wrong_it, item, expected=404) == {'error':'request_not_found'}
    final = run.decide(prefix+'.it_approves', it, item)
    assert final['status'] == 'approved' and final['it_decision'] == 'approve' and final['it_at']
    assert final == run.call(prefix+'.employee_final', 'GET', f'{REQUESTS}/{item["id"]}', employee)
    return final


def isolation(run):
    item = run.submit('isolation.b_submit', 'demo-maya', 'Mouse')
    before = run.decide('isolation.b_manager', 'demo-riley', item)
    path = f"{REQUESTS}/{item['id']}"
    assert run.call('isolation.a_employee', 'GET', path, 'demo-priya', expected=404) == {'error':'request_not_found'}
    assert run.decide('isolation.a_manager', 'demo-daniel', item, expected=404) == {'error':'request_not_found'}
    assert run.decide('isolation.a_it_same_office', 'demo-a-singapore-it', item, expected=404) == {'error':'request_not_found'}
    after = run.call('isolation.b_after', 'GET', path, 'demo-maya')
    assert before == after and after['status'] == 'pending_it' and after['it_decision'] is None
    a_queue = run.call('isolation.a_queue', 'GET', REQUESTS, 'demo-a-singapore-it')
    assert item['id'] not in [row['id'] for row in a_queue['requests']]


def declines(run):
    required = {'error': 'decline_reason_required'}
    manager_reason = 'Your current keyboard can be repaired by the service desk.'
    item = run.submit('decline.manager_submit', 'demo-alex', 'Keyboard')
    path = f"{REQUESTS}/{item['id']}"
    assert run.decide('decline.manager_missing', 'demo-nora', item, 'reject', 400) == required
    assert run.call('decline.manager_unchanged', 'GET', path, 'demo-alex') == item
    closed = run.decide('decline.manager_with_reason', 'demo-nora', item, 'reject', note=manager_reason)
    assert closed['status'] == 'rejected' and closed['manager_decision'] == 'reject'
    assert closed['manager_note'] == manager_reason and closed['manager_at']
    assert closed['it_decision'] is None and closed['it_note'] is None
    assert run.call('decline.manager_employee_view', 'GET', path, 'demo-alex') == closed
    queue = run.call('decline.manager_it_queue', 'GET', REQUESTS, 'demo-a-berlin-it')
    assert all(row['id'] != item['id'] for row in queue['requests'])
    assert run.decide('decline.manager_terminal', 'demo-nora', item, expected=409) == {'error':'wrong_approval_stage'}

    it_reason = 'This office requires an encrypted USB drive from the approved catalogue.'
    item = run.submit('decline.it_submit', 'demo-alex', 'USB flash drive')
    path = f"{REQUESTS}/{item['id']}"
    pending = run.decide('decline.it_manager_approves', 'demo-nora', item)
    assert run.decide('decline.it_blank', 'demo-a-berlin-it', item, 'reject', 400, note=' \t\n ') == required
    assert run.decide('decline.it_too_long', 'demo-a-berlin-it', item, 'reject', 400,
                      note='x'*201) == {'error': 'invalid_decision'}
    assert run.call('decline.it_unchanged', 'GET', path, 'demo-alex') == pending
    closed = run.decide('decline.it_with_reason', 'demo-a-berlin-it', item, 'reject', note=f'  {it_reason}  ')
    assert closed['status'] == 'rejected' and closed['manager_decision'] == 'approve'
    assert closed['it_decision'] == 'reject' and closed['it_note'] == it_reason and closed['it_at']
    assert run.call('decline.it_employee_view', 'GET', path, 'demo-alex') == closed
    assert run.decide('decline.it_terminal', 'demo-a-berlin-it', item, expected=409) == {'error':'wrong_approval_stage'}


def limits(run):
    a1 = run.submit('limit.a_first', 'demo-alex', 'Keyboard')
    run.decide('limit.a_first_manager', 'demo-nora', a1)
    run.submit('limit.a_second', 'demo-priya', 'Mouse')
    before = run.call('limit.a_before', 'GET', REQUESTS, 'demo-alex')
    assert (before['open'], before['limit']) == (2, 2)
    refused = run.submit('limit.a_third', 'demo-alex', 'USB flash drive', 409)
    assert refused == {'error':'open_request_limit_reached','open':2,'limit':2,'plan':'Starter'}
    assert run.call('limit.a_after', 'GET', REQUESTS, 'demo-alex') == before
    run.submit('limit.b_second', 'demo-maya', 'Second monitor')
    run.submit('limit.b_third', 'demo-maya', 'Keyboard')
    b = run.call('limit.b_usage', 'GET', REQUESTS, 'demo-maya')
    assert (b['open'], b['limit']) == (3, 5)
    closed = run.decide('limit.a_close', 'demo-a-berlin-it', a1, 'reject',
                        note='The office has a spare keyboard that can be used instead.')
    assert closed['status'] == 'rejected' and closed['it_decision'] == 'reject'
    freed = run.call('limit.a_freed', 'GET', REQUESTS, 'demo-alex')
    assert freed['open'] == 1 and closed in freed['requests']
    retry = run.submit('limit.a_retry', 'demo-alex', 'USB flash drive')
    assert retry['status'] == 'pending_manager'
    assert run.call('limit.a_final', 'GET', REQUESTS, 'demo-alex')['open'] == 2


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--output', type=Path, default=Path('local-evidence/acceptance.json'))
    args = parser.parse_args()
    run = Run(args.url)
    try:
        validation(run)
        normal(run, 'berlin', 'demo-alex', 'demo-nora', 'demo-a-berlin-it', 'Second monitor',
               wrong_manager='demo-daniel', wrong_it='demo-a-singapore-it')
        normal(run, 'singapore', 'demo-priya', 'demo-daniel', 'demo-a-singapore-it', 'Keyboard')
        normal(run, 'horizon', 'demo-maya', 'demo-riley', 'demo-b-singapore-it', 'USB flash drive')
        run.evidence['results']['normal'] = 'PASS: both tenants completed manager and local IT approval. Northstar used Berlin and Singapore.'
        isolation(run)
        run.evidence['results']['isolation'] = 'PASS: A was refused B’s request, including with an IT account in the same city. B’s record stayed intact.'
        declines(run)
        run.evidence['results']['declines'] = 'PASS: manager and IT declines require a reason. The employee can see the decision and reason.'
        limits(run)
        run.evidence['results']['limit'] = 'PASS: Starter stayed at 2/2 after refusal. Plus reached 3/5. Closing a request let Starter retry.'
    except Exception as error:
        run.evidence['failure'] = repr(error)
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(run.evidence, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    for result in run.evidence['results'].values():
        print(result)
    print(f"Captured {len(run.evidence['exchanges'])} HTTP exchanges.")


if __name__ == '__main__':
    main()
