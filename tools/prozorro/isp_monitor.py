"""Моніторинг ІСП: лише закупівлі ДК 021:2015 35740000-3 «Симулятори бойових дій».

Usage:
  python3 -I isp_monitor.py OUT.json [--statuses s1,s2] [--since РРРР-ММ-ДД] [--ids UA-...,UA-...]

Без --ids шукає на prozorro.gov.ua закупівлі з CPV 35740000-3 у вказаних статусах
(за замовчуванням: усі — від прийому пропозицій до завершених) і залишає лише ті, де хоча б одна
позиція має код 357400xx. --since відсікає закупівлі, оголошені раніше за дату.

OUT.json:
  tenders — по одній на закупівлю: ID, предмет, замовник (ЄДРПОУ, регіон, контакт), позиції (35740000-3),
            очікувана вартість і ПДВ, кінець уточнень і подання, статус, кількість учасників,
            awards (переможці/кандидати з контактами), rejected (відхилені), contracts (договори),
            bidders, own_bids (участь ІСП / ІВТ / ФОП Любченко), discount (знижка переможця від очікуваної).
  prices  — по рядку на (закупівля, позиція 35740000-3, учасник): ціна за одиницю з пропозиції,
            кількість, сума пропозиції, початкова сума (до аукціону), переможець так/ні, наша компанія так/ні.
Код виходу 2 — Prozorro не відповідав.
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

P = get_profile('isp')
ALL_STATUSES = ['active.enquiries', 'active.tendering', 'active.pre-qualification',
                'active.pre-qualification.stand-still', 'active.auction', 'active.qualification',
                'active.awarded', 'complete', 'unsuccessful', 'cancelled']
FAILED = {'n': 0}


def http(url, body=None):
    for a in range(4):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                         headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            time.sleep(2 * (a + 1))
    FAILED['n'] += 1
    return None


def search(statuses, since=''):
    """Видача відсортована від нових до старих; гортаємо до --since (ID містить дату UA-РРРР-ММ-ДД),
    а без --since — до 2000 записів."""
    ids = {}
    for cpv in P['cpvs']:
        page = 1
        while True:
            d = http('https://prozorro.gov.ua/api/search/tenders', {'cpv': [cpv], 'status': statuses, 'page': page})
            if not d or not d.get('data'):
                break
            older = False
            for x in d['data']:
                ids[x['tenderID']] = 1
                if since and x['tenderID'][3:13] < since:
                    older = True
            limit = d.get('total', 0) if since else min(d.get('total', 0), 2000)
            if older or page * 20 >= limit:
                break
            page += 1
    return list(ids)


def relevant(item):
    return ((item.get('classification') or {}).get('id') or '').startswith(P['cpv_prefix'])


def own_name(edrpou):
    return P['own'].get(edrpou)


def load(tid, since):
    s = http(f'https://prozorro.gov.ua/api/tenders/{tid}/summary')
    if not s or 'id' not in s:
        return None
    t = (http(f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{s['id']}") or {}).get('data')
    if not t:
        return None
    items = [i for i in t.get('items', []) if relevant(i)]
    if not items:
        return None
    date = (t.get('tenderPeriod') or {}).get('startDate') or t.get('date') or ''
    if since and date[:10] < since:
        return None
    pe = t['procuringEntity']
    cp = pe.get('contactPoint') or {}
    value = (t.get('value') or {})
    out = {
        'tenderID': tid, 'url': f'https://prozorro.gov.ua/tender/{tid}', 'title': t.get('title'),
        'method': t.get('procurementMethodType'), 'status': t.get('status'),
        'status_ua': STATUS_UA.get(t.get('status'), t.get('status')), 'date': date[:10],
        'customer': pe.get('name'), 'customer_edrpou': (pe.get('identifier') or {}).get('id'),
        'region': (pe.get('address') or {}).get('region'), 'locality': (pe.get('address') or {}).get('locality'),
        'customer_contact': cp.get('name'), 'customer_phone': cp.get('telephone'), 'customer_email': cp.get('email'),
        'value': value.get('amount'), 'vat_included': value.get('valueAddedTaxIncluded'),
        'enquiry_end': (t.get('enquiryPeriod') or {}).get('endDate'),
        'tender_end': (t.get('tenderPeriod') or {}).get('endDate'),
        'items': [{'id': i.get('id'), 'description': i.get('description'), 'quantity': i.get('quantity'),
                   'unit': (i.get('unit') or {}).get('name'), 'cpv': i['classification']['id']} for i in items],
        'bids_count': len(t.get('bids', [])), 'awards': [], 'rejected': [], 'contracts': [], 'bidders': [],
    }
    bids = {b.get('id'): b for b in t.get('bids', [])}
    for b in t.get('bids', []):
        for tr in b.get('tenderers', []):
            e = (tr.get('identifier') or {}).get('id')
            out['bidders'].append({'name': tr.get('name'), 'edrpou': e, 'status': b.get('status'), 'own': own_name(e)})
    out['own_bids'] = [b for b in out['bidders'] if b['own']]
    winners = set()
    for a in t.get('awards', []):
        for sp in a.get('suppliers', []):
            e = (sp.get('identifier') or {}).get('id')
            scp = sp.get('contactPoint') or {}
            row = {'award_status': a.get('status'), 'name': sp.get('name'), 'edrpou': e, 'own': own_name(e),
                   'amount': (a.get('value') or {}).get('amount'), 'date': (a.get('date') or '')[:10],
                   'contact_name': scp.get('name'), 'phone': scp.get('telephone'), 'email': scp.get('email'),
                   'lotID': a.get('lotID')}
            if a.get('status') in ('active', 'pending'):
                out['awards'].append(row)
                if a.get('status') == 'active':
                    winners.add((a.get('bid_id'), a.get('lotID')))
            elif a.get('status') in ('unsuccessful', 'cancelled'):
                out['rejected'].append(row)
    for c in t.get('contracts', []):
        sp = (c.get('suppliers') or [{}])[0]
        out['contracts'].append({'status': c.get('status'), 'amount': (c.get('value') or {}).get('amount'),
                                 'dateSigned': (c.get('dateSigned') or '')[:10], 'supplier': sp.get('name'),
                                 'supplier_edrpou': (sp.get('identifier') or {}).get('id')})
    win = next((a for a in out['awards'] if a['award_status'] == 'active'), None)
    out['discount'] = round(1 - win['amount'] / out['value'], 4) if (win and win['amount'] and out['value']) else None
    # ціни учасників по позиціях 35740000-3
    prices = []
    lot_items = {}
    for i in t.get('items', []):
        lot_items.setdefault(i.get('relatedLot'), []).append(i)
    for b in t.get('bids', []):
        tr = (b.get('tenderers') or [{}])[0]
        e = (tr.get('identifier') or {}).get('id')
        bid_items = {bi.get('id'): bi for bi in b.get('items', [])}
        lvs = {lv.get('relatedLot'): lv for lv in b.get('lotValues', [])}
        if not lvs and b.get('value'):
            lvs[None] = {'value': b['value'], 'initialValue': b.get('initialValue') or b['value'], 'status': b.get('status')}
        for it in items:
            lot = it.get('relatedLot')
            lv = lvs.get(lot) or (lvs.get(None) if len(lvs) == 1 else None)
            if lv is None:
                continue
            uv = ((bid_items.get(it['id']) or {}).get('unit') or {}).get('value') or {}
            val, init = lv.get('value') or {}, lv.get('initialValue') or {}
            unit_price, basis = uv.get('amount'), 'ціна за одиницю з пропозиції'
            in_lot = lot_items.get(lot, [])
            rel_in_lot = [i for i in in_lot if relevant(i)]
            if not unit_price and len(rel_in_lot) == 1 and it.get('quantity') and val.get('amount'):
                unit_price = val['amount'] / it['quantity']
                basis = 'сума / кількість' if len(in_lot) == 1 else 'сума / кількість (сума включає інші позиції лоту)'
            vat = val.get('valueAddedTaxIncluded')
            if vat is None:
                vat = uv.get('valueAddedTaxIncluded')
            prices.append({
                'date': date[:10], 'tenderID': tid, 'customer': pe.get('name'), 'item': it.get('description'),
                'quantity': it.get('quantity'), 'unit': (it.get('unit') or {}).get('name'),
                'bidder': tr.get('name'), 'edrpou': e, 'unit_price': round(unit_price, 2) if unit_price else None,
                'vat_included': vat, 'basis': basis if unit_price else 'немає ціни за одиницю',
                'bid_amount': val.get('amount'), 'initial_amount': init.get('amount'),
                'winner': (b.get('id'), lot) in winners, 'bid_status': lv.get('status') or b.get('status'),
                'own': bool(own_name(e)), 'contact': (tr.get('contactPoint') or {}).get('name'),
                'phone': (tr.get('contactPoint') or {}).get('telephone'),
                'email': (tr.get('contactPoint') or {}).get('email'),
            })
    out['_prices'] = prices
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--statuses', default=','.join(ALL_STATUSES))
    ap.add_argument('--since', default='')
    ap.add_argument('--ids', default='')
    a = ap.parse_args()
    ids = [x for x in a.ids.split(',') if x] or search([s for s in a.statuses.split(',') if s], a.since)
    print('tenders to check', len(ids), flush=True)
    with ThreadPoolExecutor(8) as ex:
        res = [r for r in ex.map(lambda x: load(x, a.since), ids) if r]
    prices = [p for r in res for p in r.pop('_prices')]
    res.sort(key=lambda r: r['date'], reverse=True)
    json.dump({'tenders': res, 'prices': prices}, open(a.out, 'w'), ensure_ascii=False, indent=1)
    print(f'tenders {len(res)}; price rows {len(prices)}; failed requests {FAILED["n"]}', flush=True)
    if not ids or (ids and not res and FAILED['n']):
        sys.exit(2)
