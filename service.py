"""Small request and approval service for the local SaaS lab."""

from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import compare_digest
from urllib.parse import urlsplit
import json
import os
import re
import sqlite3
import uuid


ROOT = Path(__file__).resolve().parent
ACCOUNTS = json.loads((ROOT/'accounts.json').read_text(encoding='utf-8'))
BY_ID = {(account['tenant'], account['id']): account for account in ACCOUNTS}
COMPANIES = {'A': {'name': 'Northstar Services', 'plan': 'Starter', 'limit': 2},
             'B': {'name': 'Horizon Design', 'plan': 'Plus', 'limit': 5}}
OFFICES = {'Berlin': 'Europe', 'Singapore': 'Asia'}
EQUIPMENT = ('Mouse', 'Second monitor', 'Keyboard', 'USB flash drive')
FIELDS = {'equipment', 'employee_name', 'employee_id', 'office', 'reason'}
ITEM_PATH = re.compile(r'/v1/requests/([a-f0-9]{32})(/decision)?')
SCOPE = {'employee': 'employee_id', 'manager': 'manager_id', 'it': 'office'}
STATIC = {'/': ('index.html', 'text/html'), '/app.css': ('app.css', 'text/css'), '/app.js': ('app.js', 'text/javascript')}


class Error(Exception):
    def __init__(self, status, error, **details):
        self.status = status
        self.body = {'error': error, **details}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate_order(account, data):
    if set(data) != FIELDS:
        raise Error(400, 'invalid_fields', required=sorted(FIELDS))
    if any(not isinstance(value, str) for value in data.values()):
        raise Error(400, 'invalid_fields', required=sorted(FIELDS))
    order = {key: ' '.join(value.split()) for key, value in data.items()}
    blank = sorted(key for key, value in order.items() if not value)
    if blank:
        raise Error(400, 'required_fields', fields=blank)
    if order['equipment'] not in EQUIPMENT:
        raise Error(400, 'invalid_equipment')
    if (order['employee_name'].casefold() != account['name'].casefold()
            or order['employee_id'].upper() != account['id']
            or order['office'] != account['office']):
        raise Error(400, 'profile_mismatch')
    if not 15 <= len(order['reason']) <= 300 or len(order['reason'].split()) < 3:
        raise Error(400, 'reason_too_short_or_long', minimum=15, maximum=300)
    return order['equipment'], order['reason']


class Store:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, employee_id TEXT NOT NULL,
                    employee_name TEXT NOT NULL, manager_id TEXT NOT NULL, office TEXT NOT NULL,
                    equipment TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending_manager','pending_it','approved','rejected')),
                    manager_decision TEXT, manager_at TEXT, manager_note TEXT,
                    it_decision TEXT, it_at TEXT, it_note TEXT
                );
                CREATE INDEX IF NOT EXISTS requests_usage ON requests(tenant_id, status);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def active(db, tenant):
        return db.execute('''SELECT COUNT(*) FROM requests WHERE tenant_id = ?
                             AND status IN ('pending_manager', 'pending_it')''', (tenant,)).fetchone()[0]

    @staticmethod
    def scope(account, for_decision=False):
        role = account['role']
        rule = 'tenant_id = ? AND '+SCOPE[role]+' = ?'
        value = account['office'] if role == 'it' else account['id']
        if role == 'it' and not for_decision:
            rule += " AND manager_decision = 'approve'"
        return rule, (account['tenant'], value)

    def get_row(self, db, account, item_id, for_decision=False):
        rule, args = self.scope(account, for_decision)
        row = db.execute(f'SELECT * FROM requests WHERE {rule} AND id = ?', (*args, item_id)).fetchone()
        if row is None:
            raise Error(404, 'request_not_found')
        return row

    @staticmethod
    def serialize(row):
        item = dict(row)
        item['manager_name'] = BY_ID[(item['tenant_id'], item['manager_id'])]['name']
        item['it_team'] = item['office']+' IT'
        item['region'] = OFFICES[item['office']]
        return item

    def list(self, account):
        rule, args = self.scope(account)
        with self.connect() as db:
            db.execute('BEGIN')
            rows = db.execute(f'SELECT * FROM requests WHERE {rule} ORDER BY rowid DESC', args).fetchall()
            active = self.active(db, account['tenant'])
        return {'requests': [self.serialize(row) for row in rows], 'open': active,
                **COMPANIES[account['tenant']]}

    def get(self, account, item_id):
        with self.connect() as db:
            return self.serialize(self.get_row(db, account, item_id))

    def create(self, account, data):
        if account['role'] != 'employee':
            raise Error(403, 'employee_role_required')
        equipment, reason = validate_order(account, data)
        company = COMPANIES[account['tenant']]
        item_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = self.active(db, account['tenant'])
            if active >= company['limit']:
                raise Error(409, 'open_request_limit_reached', open=active, limit=company['limit'], plan=company['plan'])
            db.execute('''INSERT INTO requests (id,tenant_id,employee_id,employee_name,manager_id,office,
                          equipment,reason,created_at,status) VALUES (?,?,?,?,?,?,?,?,?,'pending_manager')''',
                       (item_id, account['tenant'], account['id'], account['name'], account['manager'],
                        account['office'], equipment, reason, utc_now()))
            return self.serialize(self.get_row(db, account, item_id))

    def decide(self, account, item_id, data):
        role = account['role']
        if role not in ('manager', 'it'):
            raise Error(403, 'approver_role_required')
        decision, note = data.get('decision'), data.get('note', '')
        if (set(data)-{'decision','note'} or decision not in ('approve','reject')
                or not isinstance(note, str) or len(note) > 200):
            raise Error(400, 'invalid_decision')
        note = note.strip()
        if decision == 'reject' and not note:
            raise Error(400, 'decline_reason_required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.get_row(db, account, item_id, for_decision=True)
            if row['status'] != ('pending_manager' if role == 'manager' else 'pending_it'):
                raise Error(409, 'wrong_approval_stage')
            if decision == 'reject':
                status = 'rejected'
            else:
                status = 'pending_it' if role == 'manager' else 'approved'
            db.execute(f'''UPDATE requests SET status=?, {role}_decision=?, {role}_at=?, {role}_note=?
                           WHERE tenant_id=? AND id=?''',
                       (status, decision, utc_now(), note, account['tenant'], item_id))
            return self.serialize(self.get_row(db, account, item_id, for_decision=True))


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, mime, body):
        self.send_response(status)
        self.send_header('Content-Type', mime+'; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if status == 401:
            self.send_header('WWW-Authenticate', 'Bearer')
        self.end_headers()
        self.wfile.write(body)

    def account(self):
        headers = self.headers.get_all('Authorization') or []
        if len(headers) == 1:
            scheme, _, token = headers[0].partition(' ')
            if scheme.lower() == 'bearer':
                for account in ACCOUNTS:
                    if compare_digest(token.encode(), account['token'].encode()):
                        return account
        raise Error(401, 'invalid_token')

    def read_json(self):
        sizes = self.headers.get_all('Content-Length') or []
        if len(sizes) != 1 or not re.fullmatch(r'[0-9]{1,8}', sizes[0]) or not 0 < int(sizes[0]) <= 4096:
            raise Error(400, 'invalid_body_size')
        if self.headers.get_content_type() != 'application/json':
            raise Error(415, 'expected_json')
        try:
            data = json.loads(self.rfile.read(int(sizes[0])))
        except (ValueError, RecursionError):
            raise Error(400, 'invalid_json') from None
        if not isinstance(data, dict):
            raise Error(400, 'invalid_json')
        return data

    def dispatch(self, method, path):
        if method == 'GET' and path == '/health':
            return 200, {'status': 'ok'}
        if method == 'GET' and path == '/demo/accounts':
            return 200, [{'token': a['token'], 'name': a['name'], 'id': a['id'], 'role': a['role'],
                          'office': a['office'], 'company': COMPANIES[a['tenant']]['name']} for a in ACCOUNTS]
        account = self.account()
        store = self.server.store
        if method == 'GET' and path == '/v1/me':
            profile = {k: v for k, v in account.items() if k != 'token'}
            profile['company'] = COMPANIES[account['tenant']]['name']
            profile['region'] = OFFICES[account['office']]
            if account['role'] == 'employee':
                profile['manager_name'] = BY_ID[(account['tenant'], account['manager'])]['name']
            return 200, {'profile': profile, 'equipment': EQUIPMENT, 'offices': OFFICES}
        if path == '/v1/requests':
            return (200, store.list(account)) if method == 'GET' else (201, store.create(account, self.read_json()))
        match = ITEM_PATH.fullmatch(path)
        if match:
            item_id, decision_path = match.groups()
            if method == 'GET' and not decision_path:
                return 200, store.get(account, item_id)
            if method == 'POST' and decision_path:
                return 200, store.decide(account, item_id, self.read_json())
        raise Error(404, 'route_not_found')

    def handle_api(self, method):
        try:
            path = urlsplit(self.path).path
            if method == 'GET' and path in STATIC:
                asset, mime = STATIC[path]
                return self.send_bytes(200, mime, (ROOT/'public'/asset).read_bytes())
            status, body = self.dispatch(method, path)
        except Error as error:
            status, body = error.status, error.body
        except sqlite3.Error as error:
            self.log_error('Storage error: %s', error)
            status, body = 503, {'error':'storage_unavailable'}
        except ValueError:
            status, body = 400, {'error':'invalid_request'}
        self.send_bytes(status, 'application/json', json.dumps(body).encode('utf-8'))

    def do_GET(self):
        self.handle_api('GET')

    def do_POST(self):
        self.handle_api('POST')


if __name__ == '__main__':
    with ThreadingHTTPServer(('0.0.0.0', 8080), Handler) as server:
        server.store = Store(os.environ.get('DB_PATH', './requests.sqlite'))
        print('IT Equipment Desk is listening on port 8080', flush=True)
        server.serve_forever()
