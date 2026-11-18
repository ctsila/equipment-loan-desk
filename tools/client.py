"""HTTP requests for the local coursework demo."""

from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json


TOKENS = {'A': 'demo-northside-token', 'B': 'demo-westbank-token'}
LOANS = '/v1/loans'


def request(url, method, path, tenant=None, body=None):
    headers = {'Accept': 'application/json'}
    if tenant:
        headers['Authorization'] = f'Bearer {TOKENS[tenant]}'
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode('utf-8')
    req = Request(url.rstrip('/')+path, data=data, headers=headers, method=method)
    try:
        response = urlopen(req, timeout=8)
    except HTTPError as error:
        response = error
    with response:
        return {'status': response.status, 'json': json.load(response)}
