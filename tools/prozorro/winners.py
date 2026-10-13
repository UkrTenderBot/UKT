"""Check tracked Prozorro tenders for awards (winners) and their contact persons.

Usage: python3 -I winners.py UA-...-a [UA-...-a ...] > winners.json
Output: JSON list, one entry per tender, with status and award details.
"""
import json
import sys
import time
import urllib.request

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
    for a in t.get('awards', []):
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
                         'dateSigned': (c.get('dateSigned') or '')[:10]} for c in t.get('contracts', [])]
    return out


if __name__ == '__main__':
    print(json.dumps([check(t) for t in sys.argv[1:]], ensure_ascii=False, indent=1))
