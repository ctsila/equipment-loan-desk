"""Local SaaS prototype for checking out and returning equipment."""

from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Tenant:
    id: str
    name: str
    plan: str
    loan_limit: int
    demo_token: str


TENANTS = (
    Tenant('A', 'Northside Media Workshop', 'Starter', 2, 'demo-northside-token'),
    Tenant('B', 'Westbank Makerspace', 'Plus', 5, 'demo-westbank-token'),
)
LOAN_PATH = re.compile(r'/v1/loans/([0-9a-f]{32})(/return)?')
REFERENCE = re.compile(r'[A-Z0-9][A-Z0-9_-]{0,31}')


class ApiError(Exception):
    def __init__(self, status, error, **details):
        self.status = status
        self.body = {'error': error, **details}


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def serialize(row):
    return {**dict(row), 'status': 'active' if row['returned_at'] is None else 'returned'}


class Loans:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS loans (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL CHECK (tenant_id IN ('A', 'B')),
                asset_code TEXT NOT NULL,
                borrower_ref TEXT NOT NULL,
                checked_out_at TEXT NOT NULL,
                returned_at TEXT
            )''')
            db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan_per_asset
                          ON loans(tenant_id, asset_code) WHERE returned_at IS NULL''')
            db.execute('CREATE INDEX IF NOT EXISTS loans_by_tenant ON loans(tenant_id)')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def owned_row(self, db, tenant, loan_id):
        row = db.execute('SELECT * FROM loans WHERE tenant_id = ? AND id = ?',
                         (tenant.id, loan_id)).fetchone()
        if row is None:
            raise ApiError(404, 'loan_not_found')
        return row

    def list(self, tenant):
        with self.connection() as db:
            rows = db.execute('SELECT * FROM loans WHERE tenant_id = ? ORDER BY checked_out_at, id',
                              (tenant.id,)).fetchall()
        loans = [serialize(row) for row in rows]
        return {'tenant_id': tenant.id, 'organisation': tenant.name, 'plan': tenant.plan,
                'limit': tenant.loan_limit, 'active': sum(loan['status'] == 'active' for loan in loans),
                'loans': loans}

    def get(self, tenant, loan_id):
        with self.connection() as db:
            return serialize(self.owned_row(db, tenant, loan_id))

    def checkout(self, tenant, asset_code, borrower_ref):
        with self.connection() as db:
            # Serialize the allowance check and insert with other checkouts and returns.
            db.execute('BEGIN IMMEDIATE')
            active = db.execute('SELECT COUNT(*) FROM loans WHERE tenant_id = ? AND returned_at IS NULL',
                                (tenant.id,)).fetchone()[0]
            if active >= tenant.loan_limit:
                raise ApiError(409, 'active_loan_limit_reached', plan=tenant.plan,
                               limit=tenant.loan_limit, active=active)
            existing = db.execute('''SELECT 1 FROM loans
                                    WHERE tenant_id = ? AND asset_code = ? AND returned_at IS NULL''',
                                  (tenant.id, asset_code)).fetchone()
            if existing:
                raise ApiError(409, 'asset_already_checked_out')
            loan_id = uuid.uuid4().hex
            db.execute('''INSERT INTO loans (id, tenant_id, asset_code, borrower_ref, checked_out_at)
                          VALUES (?, ?, ?, ?, ?)''',
                       (loan_id, tenant.id, asset_code, borrower_ref, utc_timestamp()))
            return serialize(self.owned_row(db, tenant, loan_id))

    def return_loan(self, tenant, loan_id):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            loan = self.owned_row(db, tenant, loan_id)
            if loan['returned_at'] is None:
                db.execute('UPDATE loans SET returned_at = ? WHERE tenant_id = ? AND id = ?',
                           (utc_timestamp(), tenant.id, loan_id))
                loan = self.owned_row(db, tenant, loan_id)
            return serialize(loan)


class Handler(BaseHTTPRequestHandler):
    server_version = 'EquipmentLoanDesk/1.0'
    sys_version = ''

    def authenticated_tenant(self):
        headers = self.headers.get_all('Authorization') or []
        if len(headers) == 1:
            scheme, _, given = headers[0].partition(' ')
            if scheme.lower() == 'bearer':
                for tenant in TENANTS:
                    if compare_digest(given.encode(), tenant.demo_token.encode()):
                        return tenant
        raise ApiError(401, 'invalid_token')

    def checkout_body(self):
        sizes = self.headers.get_all('Content-Length') or []
        if len(sizes) != 1 or not re.fullmatch(r'[0-9]{1,8}', sizes[0]):
            raise ApiError(400, 'invalid_content_length')
        size = int(sizes[0])
        if not 0 < size <= 2048:
            raise ApiError(413, 'invalid_body_size')
        if self.headers.get_content_type() != 'application/json':
            raise ApiError(415, 'expected_json')
        try:
            data = json.loads(self.rfile.read(size))
        except (ValueError, RecursionError):
            raise ApiError(400, 'malformed_json') from None
        if not isinstance(data, dict) or set(data) != {'asset_code', 'borrower_ref'}:
            raise ApiError(400, 'invalid_fields', expected=['asset_code', 'borrower_ref'])
        for key, value in data.items():
            if not isinstance(value, str) or not REFERENCE.fullmatch(value):
                raise ApiError(400, 'invalid_reference', field=key)
        return data

    def dispatch(self, method):
        path = urlsplit(self.path).path
        if method == 'GET' and path == '/health':
            return 200, {'status': 'ok'}
        tenant = self.authenticated_tenant()
        store = self.server.loans
        if path == '/v1/loans':
            if method == 'GET':
                return 200, store.list(tenant)
            return 201, store.checkout(tenant, **self.checkout_body())
        match = LOAN_PATH.fullmatch(path)
        if match:
            loan_id, is_return = match.groups()
            if method == 'GET' and not is_return:
                return 200, store.get(tenant, loan_id)
            if method == 'POST' and is_return:
                return 200, store.return_loan(tenant, loan_id)
        raise ApiError(404, 'route_not_found')

    def handle_request(self, method):
        try:
            status, body = self.dispatch(method)
        except ApiError as error:
            status, body = error.status, error.body
        except sqlite3.Error as error:
            self.log_error('Database operation failed: %s', error)
            status, body = 503, {'error': 'storage_unavailable'}
        except ValueError:
            status, body = 400, {'error': 'invalid_request'}
        output = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(output)))
        self.send_header('Cache-Control', 'no-store')
        if status == 401:
            self.send_header('WWW-Authenticate', 'Bearer')
        self.end_headers()
        self.wfile.write(output)

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')


if __name__ == '__main__':
    with ThreadingHTTPServer(('0.0.0.0', 8080), Handler) as server:
        server.loans = Loans(os.environ.get('DB_PATH', './loans.sqlite'))
        print('Equipment Loan Desk is listening on port 8080', flush=True)
        server.serve_forever()
