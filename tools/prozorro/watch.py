"""Контроль закупівель, де власні компанії є учасниками (п. 11).

Usage: python3 -I watch.py OUT.json --ids UA-...,UA-... [--profile cable|isp] [--since 2026-10-13T08:00]

Для кожної закупівлі повертає:
  urgent      — чинні (строк ще не минув) вимоги щодо усунення невідповідностей (milestone «24h»,
                п. 43 Особливостей, постанова КМУ № 1178) для власної компанії, з dueDate; найвищий пріоритет;
  own         — власні пропозиції та їх статус, рішення щодо власних award (визнано переможцем / відхилено);
  deadlines   — кінець періоду уточнень і подання пропозицій (зміна строку — у changes);
  changes     — що змінилося після --since: нові/змінені документи (зміни до ТД), відповіді на питання,
                нові скарги/вимоги, нові рішення (awards), зміна статусу договору;
  status_ua   — стан закупівлі українською.
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
from winners import STATUS_UA  # noqa: E402

from datetime import datetime, timezone
NOW = datetime.now(timezone.utc)


try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo('Europe/Kyiv')
except Exception:
    KYIV = timezone.utc


def parse(iso):
    try:
        d = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=KYIV)
    except Exception:
        return None


def future(iso):
    d = parse(iso or '')
    return bool(d) and d > NOW

AWARD_UA = {'pending': 'Розглядається', 'active': 'Визнано переможцем', 'unsuccessful': 'Відхилено',
            'cancelled': 'Скасовано'}


def get(url):
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def milestones_24h(obj):
    return [m for m in obj.get('milestones', []) or [] if m.get('code') == '24h']


def check(tid, P, since):
    summ = get(f'https://prozorro.gov.ua/api/tenders/{tid}/summary')
    if not summ or 'id' not in summ:
        return {'tenderID': tid, 'error': 'not found'}
    t = (get(f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{summ['id']}") or {}).get('data')
    if not t:
        return {'tenderID': tid, 'error': 'tender not loaded'}
    own_ids = P['own']
    bids = {b.get('id'): b for b in t.get('bids', [])}

    def is_own_bid(bid_id):
        b = bids.get(bid_id) or {}
        return any((tr.get('identifier') or {}).get('id') in own_ids for tr in b.get('tenderers', []))

    def own_supplier(a):
        return any((s.get('identifier') or {}).get('id') in own_ids for s in a.get('suppliers', []))

    out = {
        'tenderID': tid, 'url': f'https://prozorro.gov.ua/tender/{tid}', 'title': t.get('title'),
        'customer': t['procuringEntity']['name'], 'status': t.get('status'),
        'status_ua': STATUS_UA.get(t.get('status'), t.get('status')),
        'deadlines': {'enquiry_end': (t.get('enquiryPeriod') or {}).get('endDate'),
                      'tender_end': (t.get('tenderPeriod') or {}).get('endDate')},
        'urgent': [], 'own': [], 'changes': [],
    }
    for b in t.get('bids', []):
        for tr in b.get('tenderers', []):
            e = (tr.get('identifier') or {}).get('id')
            if e in own_ids:
                out['own'].append({'company': own_ids[e], 'edrpou': e, 'bid_status': b.get('status')})
    # 24-годинні вимоги: awards (кваліфікація) і qualifications (прекваліфікація)
    for kind, objs in (('award', t.get('awards', [])), ('qualification', t.get('qualifications', []))):
        for o in objs:
            mine = own_supplier(o) if kind == 'award' else is_own_bid(o.get('bidID'))
            if not mine:
                continue
            for m in milestones_24h(o):
                if future(m.get('dueDate') or ''):
                    out['urgent'].append({'type': 'Вимога щодо усунення невідповідностей (24 год)',
                                          'stage': 'кваліфікація' if kind == 'award' else 'прекваліфікація',
                                          'dueDate': m.get('dueDate'), 'date': m.get('date'),
                                          'milestone_status': m.get('status'),
                                          'description': m.get('description')})
            if kind == 'award':
                out['own'].append({'company': next((own_ids[(s.get('identifier') or {}).get('id')]
                                                    for s in o.get('suppliers', [])
                                                    if (s.get('identifier') or {}).get('id') in own_ids), ''),
                                   'award_status': AWARD_UA.get(o.get('status'), o.get('status')),
                                   'award_date': o.get('date'), 'lotID': o.get('lotID')})
    if since:
        since_dt = parse(since)

        def newer(d):
            dd = parse(d or '')
            return bool(dd and since_dt) and dd > since_dt
        for d in t.get('documents', []):
            if newer(d.get('dateModified') or d.get('datePublished')) and d.get('documentOf', 'tender') == 'tender':
                out['changes'].append({'what': 'Документ закупівлі (можливі зміни до ТД)', 'title': d.get('title'),
                                       'date': d.get('dateModified') or d.get('datePublished')})
        for q in t.get('questions', []):
            if newer(q.get('dateAnswered')):
                out['changes'].append({'what': 'Відповідь на питання', 'title': q.get('title'),
                                       'answer': (q.get('answer') or '')[:300], 'date': q.get('dateAnswered')})
            elif newer(q.get('date')):
                out['changes'].append({'what': 'Нове питання', 'title': q.get('title'), 'date': q.get('date')})
        for c in t.get('complaints', []):
            if newer(c.get('dateSubmitted') or c.get('date')):
                out['changes'].append({'what': 'Скарга/вимога', 'title': c.get('title'), 'status': c.get('status'),
                                       'date': c.get('dateSubmitted') or c.get('date')})
        for a in t.get('awards', []):
            if newer(a.get('date')):
                names = ', '.join(s.get('name') or '' for s in a.get('suppliers', []))
                out['changes'].append({'what': 'Рішення щодо пропозиції', 'title': names,
                                       'status': AWARD_UA.get(a.get('status'), a.get('status')), 'date': a.get('date'),
                                       'own': own_supplier(a)})
        for c in t.get('contracts', []):
            if newer(c.get('dateSigned') or c.get('date')):
                out['changes'].append({'what': 'Договір', 'status': c.get('status'),
                                       'date': c.get('dateSigned') or c.get('date')})
        if newer(t.get('date')) and t.get('status') in ('cancelled', 'unsuccessful'):
            out['changes'].append({'what': 'Закупівля ' + out['status_ua'].lower(), 'date': t.get('date')})
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--ids', required=True)
    ap.add_argument('--profile', default='cable')
    ap.add_argument('--since', default='')
    a = ap.parse_args()
    P = get_profile(a.profile)
    ids = [x.strip() for x in a.ids.split(',') if x.strip()]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda x: check(x, P, a.since), ids))
    res.sort(key=lambda r: (not r.get('urgent'), not r.get('changes')))
    json.dump(res, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f"checked {len(res)}; urgent {sum(bool(r.get('urgent')) for r in res)}; "
          f"with changes {sum(bool(r.get('changes')) for r in res)}; errors {sum('error' in r for r in res)}")
    if res and all('error' in r for r in res):
        sys.exit(2)
