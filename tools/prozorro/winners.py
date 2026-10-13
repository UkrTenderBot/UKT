"""Check tracked Prozorro tenders for awards (winners) and their contact persons.

Usage: python3 -I winners.py UA-...-a [UA-...-a ...] [--profile cable|isp] > winners.json
Output: JSON list, one entry per tender:
  awards    — переможці та кандидати (active / pending) з контактами;
  rejected  — відхилені пропозиції (award unsuccessful/cancelled): переможець змінився — новий лід (п. 4);
  contracts — договори зі статусом, датою підписання і постачальником (п. 2, сигнал «зараз купує»);
  bidders   — усі учасники (видно після розкриття): own_bids — участь власних компаній (п. 11).
"""
import json
import sys
import time
import urllib.request
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from profiles import get_profile  # noqa: E402

STATUS_UA = {
    'active.enquiries': 'Період уточнень',
    'active.tendering': 'Прийом пропозицій',
    'active.pre-qualification': 'Прекваліфікація',
    'active.pre-qualification.stand-still': 'Прекваліфікація',
    'active.auction': 'Аукціон',
    'active.qualification': 'Кваліфікація',
    'active.awarded': 'Визначено переможця',
    'complete': 'Завершена',
    'unsuccessful': 'Не відбулась',
    'cancelled': 'Скасована',
}


def get(url):
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def check(tid):
    summ = get(f'https://prozorro.gov.ua/api/tenders/{tid}/summary')
    if not summ or 'id' not in summ:
        return {'tenderID': tid, 'error': 'not found'}
    t = get(f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{summ['id']}")
    if not t:
        return {'tenderID': tid, 'error': 'tender not loaded'}
    t = t['data']
    out = {
        'tenderID': tid,
        'status': t.get('status'),
        'status_ua': STATUS_UA.get(t.get('status'), t.get('status')),
        'title': t.get('title'),
        'customer': t['procuringEntity']['name'],
        'awards': [],
    }
    out['rejected'] = []
    for a in t.get('awards', []):
        if a.get('status') in ('unsuccessful', 'cancelled'):
            for s in a.get('suppliers', []):
                out['rejected'].append({'award_status': a['status'], 'lotID': a.get('lotID'),
                                        'name': s.get('name') or s['identifier'].get('legalName'),
                                        'edrpou': s['identifier'].get('id'), 'date': (a.get('date') or '')[:10]})
            continue
        if a.get('status') not in ('active', 'pending'):
            continue
        for s in a.get('suppliers', []):
            cp = s.get('contactPoint') or {}
            out['awards'].append({
                'award_status': a['status'],  # active = winner, pending = under evaluation
                'lotID': a.get('lotID'),
                'name': s.get('name') or s['identifier'].get('legalName'),
                'edrpou': s['identifier'].get('id'),
                'amount': (a.get('value') or {}).get('amount'),
                'date': (a.get('date') or '')[:10],
                'contact_name': cp.get('name'),
                'phone': cp.get('telephone'),
                'email': cp.get('email'),
                'address': ', '.join(x for x in [(s.get('address') or {}).get('locality'), (s.get('address') or {}).get('streetAddress')] if x),
            })
    out['contracts'] = [{'status': c.get('status'), 'amount': (c.get('value') or {}).get('amount'),
                         'dateSigned': (c.get('dateSigned') or '')[:10],
                         'supplier_edrpou': ((c.get('suppliers') or [{}])[0].get('identifier') or {}).get('id'),
                         'supplier': (c.get('suppliers') or [{}])[0].get('name')} for c in t.get('contracts', [])]
    out['bidders'] = []
    for b in t.get('bids', []):
        for tr in b.get('tenderers', []):
            out['bidders'].append({'name': tr.get('name'), 'edrpou': (tr.get('identifier') or {}).get('id'),
                                   'status': b.get('status')})
    out['own_bids'] = [b for b in out['bidders'] if b['edrpou'] in PROFILE['own']]
    for a in out['awards']:
        a['competitor'] = a['edrpou'] in PROFILE.get('competitors', []) or any(
            w in (a['name'] or '').upper() for w in PROFILE.get('competitor_names', []))
        a['own'] = a['edrpou'] in PROFILE['own']
    return out


if __name__ == '__main__':
    args = sys.argv[1:]
    prof = 'cable'
    if '--profile' in args:
        i = args.index('--profile'); prof = args[i + 1]; del args[i:i + 2]
    PROFILE = get_profile(prof)
    res = [check(t) for t in args]
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if res and all('error' in r for r in res):
        sys.exit(2)
