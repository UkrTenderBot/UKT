"""Збирає кандидатів із пошуку prozorro.gov.ua за кодами CPV і словами профілю.

Usage: python3 -I collect.py OUT.json [статуси через кому] [--profile cable|isp]
Статуси за замовчуванням: active.tendering,active.enquiries
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from profiles import get_profile  # noqa: E402

args = [a for a in sys.argv[1:]]
profile = 'cable'
if '--profile' in args:
    i = args.index('--profile')
    profile = args[i + 1]
    del args[i:i + 2]
P = get_profile(profile)
OUT = args[0]
ST = args[1].split(",") if len(args) > 1 else ["active.tendering", "active.enquiries"]


def post(body):
    for a in range(4):
        try:
            r = urllib.request.Request("https://prozorro.gov.ua/api/search/tenders", data=json.dumps(body).encode(),
                                       headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
            return json.load(urllib.request.urlopen(r, timeout=60))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


qs = [{"cpv": [c]} for c in P['cpvs']] + [{"text": t} for t in P['texts']]
found, errors = {}, 0
for q in qs:
    page = 1
    while True:
        d = post({**q, "status": ST, "page": page})
        if d is None:
            errors += 1
            d = {'data': [], 'total': 0}
        for x in d['data']:
            x['_supply'] = any(c in P['supply_cpvs'] for c in ([q['cpv'][0]] if 'cpv' in q else []))
            prev = found.get(x['tenderID'])
            if prev and prev.get('_supply'):
                x['_supply'] = True
            found[x['tenderID']] = x
        if page * 20 >= min(d.get('total', 0), 1000) or not d['data']:
            break
        page += 1
    print(q, d.get('total'), len(found), flush=True)
json.dump(found, open(OUT, 'w'), ensure_ascii=False)
print(f'profile={profile} candidates={len(found)} failed_requests={errors}', flush=True)
# Код 2 — пошук Prozorro не відповідав (для контролю справності, п. 9)
if errors and errors >= len(qs) // 2:
    sys.exit(2)
