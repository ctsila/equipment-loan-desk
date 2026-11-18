"""Compare the final loan lists with the same endpoint after a container restart."""

from argparse import ArgumentParser
from pathlib import Path
import json

from client import LOANS, request


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=Path('local-evidence/acceptance.json'))
    parser.add_argument('--output', type=Path, default=Path('local-evidence/persistence.json'))
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding='utf-8'))
    results = {}
    for tenant, label in [('A', 'limit.A.final'), ('B', 'limit.B.after')]:
        before = next(x['response'] for x in reference['exchanges'] if x['check'] == label)
        after = request(reference['url'], 'GET', LOANS, tenant)
        results[tenant] = {'request': {'method': 'GET', 'path': LOANS, 'tenant_credential': tenant},
                           'before': before, 'after': after, 'identical': before == after}
    args.output.write_text(json.dumps(results, indent=2)+'\n', encoding='utf-8')
    if not all(result['identical'] for result in results.values()):
        raise SystemExit('Loan records changed after restart. See ' + str(args.output))
    print('PASS: Both tenants’ loan lists, statuses and timestamps matched after restart.')


if __name__ == '__main__':
    main()
