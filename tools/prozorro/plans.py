"""Річні плани закупівель Prozorro (п. 8): майбутні закупівлі ще до оголошення тендера.

Usage: python3 -I plans.py OUT.json [--profile cable|isp] [--since 2026-10-01]

Шукає плани за CPV і словами профілю (plan_cpvs, plan_texts) через пошук prozorro.gov.ua,
потім довантажує кожен план з публічного API. Пише список:
  planID, id, buyer, buyer_edrpou, region, budget, currency, year, description, cpv,
  tender_start (орієнтовний початок закупівлі), method, status, dateModified, url.
Код виходу 2 — пошук планів не відповів (див. README: перевірити ендпойнт).
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from profiles import get_profile  # noqa: E402

SEARCH = 'https://prozorro.gov.ua/api/search/plans'
API = 'https://public-api.prozorro.gov.ua/api/2.5/plans/'


def http(url, body=None):
    for a in range(4):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                         headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def search(P):
    found, failed, qs = {}, 0, [{'cpv': [c]} for c in P['plan_cpvs']] + [{'text': t} for t in P['plan_texts']]
    for q in qs:
        page = 1
        while True:
            d = http(SEARCH, {**q, 'page': page})
            if d is None or 'data' not in d:
                failed += 1
                break
            for x in d['data']:
                pid = x.get('id') or x.get('_id')
                if pid:
                    found[pid] = x
            if not d['data'] or page * 20 >= min(d.get('total', 0), 400):
                break
            page += 1
    return found, failed, len(qs)


def detail(pid):
    p = (http(API + pid) or {}).get('data')
    if not p:
        return None
    b = p.get('budget') or {}
    buyer = (p.get('buyers') or [p.get('procuringEntity') or {}])[0]
    return {
        'planID': p.get('planID'), 'id': p.get('id'),
        'buyer': buyer.get('name'), 'buyer_edrpou': (buyer.get('identifier') or {}).get('id'),
        'region': (buyer.get('address') or {}).get('region'),
        'budget': b.get('amount'), 'currency': b.get('currency'), 'year': (b.get('period') or {}).get('startDate', '')[:4],
        'description': b.get('description') or (p.get('items') or [{}])[0].get('description'),
        'cpv': (p.get('classification') or {}).get('id'),
        'tender_start': ((p.get('tender') or {}).get('tenderPeriod') or {}).get('startDate', '')[:10],
        'method': (p.get('tender') or {}).get('procurementMethodType'),
        'status': p.get('status'), 'dateModified': (p.get('dateModified') or '')[:10],
        'tender_ids': [t.get('id') for t in (p.get('tender_id') and [{'id': p['tender_id']}] or [])],
        'url': f"https://prozorro.gov.ua/plan/{p.get('planID')}",
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--profile', default='cable')
    ap.add_argument('--since', default='')
    a = ap.parse_args()
    P = get_profile(a.profile)
    found, failed, total = search(P)
    print(f'plans found {len(found)}; failed queries {failed}/{total}', flush=True)
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(detail, list(found)) if r]
    # лише чинні плани, ще без оголошеної закупівлі, змінені після --since
    rows = [r for r in rows if r['status'] in (None, 'scheduled', 'draft') and not r['tender_ids']
            and (not a.since or (r['dateModified'] or '') >= a.since)]
    rows.sort(key=lambda r: (r['tender_start'] or '9999', -(r['budget'] or 0)))
    json.dump(rows, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print('plans saved', len(rows), flush=True)
    if failed == total:
        sys.exit(2)
