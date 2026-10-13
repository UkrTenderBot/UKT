"""Participants' prices per meter for cable tenders (АСБл, ААБл, ААШв, АПвЕгаПу, АПвЕгП).

Usage:
  python3 -I prices.py OUT.json [--since 2025-01-01] [--ids UA-...,UA-...]
Without --ids it searches prozorro.gov.ua for finished/awarded tenders mentioning the marks.
Output: JSON list of rows, one per (tender, cable item, participant).
"""
import argparse
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

LAT = str.maketrans('ABCEHKMOPTXaceopxyiI', 'АВСЕНКМОРТХасеорхуіІ')
GROUPS = [
    ('АПвЕгаПу', re.compile(r'АПВЕГАП')),
    ('АПвЕгП', re.compile(r'АПВЕГП')),
    ('АСБл', re.compile(r'(?<![А-ЯІЇЄҐ])Ц?АСБ(?:2)?Л')),
    ('ААБл', re.compile(r'(?<![А-ЯІЇЄҐ])Ц?ААБ(?:2|Н)?Л')),
    ('ААШв', re.compile(r'(?<![А-ЯІЇЄҐ])Ц?ААШВ')),
    ('ЦАБл', re.compile(r'(?<![А-ЯІЇЄҐ])ЦАБ(?:2|Н)?Л')),
]
QUERIES = ['АСБл', 'ААБл', 'ААШв', 'АПвЕгаПу', 'АПвЕгП', 'АСБ2л', 'ЦАСБ', 'ААБ2л', 'ЦААШв', 'ЦААБл', 'АСБл-10', 'ААБл-10', 'ААШв-10', 'ЦАБл', 'ЦАБ2л']
STATUSES = ['complete', 'active.awarded', 'active.qualification', 'unsuccessful']
UNIT_M = {'метр': 1, 'м': 1, 'метри': 1, 'погонний метр': 1, 'кілометр': 1000, 'км': 1000}


def http(url, body=None):
    for a in range(4):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                         headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def group_of(desc):
    n = re.sub(r'[\s ]+', ' ', (desc or '').translate(LAT).upper())
    for g, rx in GROUPS:
        if rx.search(n):
            return g
    return None


def parse_desc(desc):
    d = (desc or '').translate(LAT).replace('X', 'х').replace('x', 'х').replace('Х', 'х')
    volt = re.search(r'-\s?(\d{1,3}(?:[.,]\d)?)\b', d)
    sect = re.search(r'(\d)\s?[хx*]\s?(\d{2,4})(?:\s?/\s?(\d{1,3}))?', d)
    return (volt.group(1) + ' кВ') if volt else '', (f'{sect.group(1)}х{sect.group(2)}' + (f'/{sect.group(3)}' if sect.group(3) else '')) if sect else ''


def search_ids():
    ids = {}
    for q in QUERIES:
        page = 1
        while True:
            d = http('https://prozorro.gov.ua/api/search/tenders', {'text': q, 'status': STATUSES, 'page': page}) or {'data': []}
            for x in d['data']:
                ids[x['tenderID']] = 1
            if not d['data'] or page * 20 >= min(d.get('total', 0), 1000):
                break
            page += 1
    return list(ids)


def rows_for(tid, since):
    s = http(f'https://prozorro.gov.ua/api/tenders/{tid}/summary')
    if not s or 'id' not in s:
        return []
    t = (http(f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{s['id']}") or {}).get('data')
    if not t:
        return []
    date = (t.get('tenderPeriod') or {}).get('endDate') or t.get('date') or ''
    if date[:10] < since:
        return []
    items = {i['id']: i for i in t.get('items', []) if group_of(i.get('description'))}
    if not items:
        return []
    winners = {}
    for a in t.get('awards', []):
        if a.get('status') == 'active':
            winners[(a.get('bid_id'), a.get('lotID'))] = 1
    # items per lot (to divide a lot total when the lot has one item)
    lot_items = {}
    for i in t.get('items', []):
        lot_items.setdefault(i.get('relatedLot'), []).append(i)
    # winner's per-unit prices from signed/pending contracts (when the API exposes them)
    contract_unit = {}
    for c in t.get('contracts', []):
        for ci in c.get('items', []) or []:
            uv = (ci.get('unit') or {}).get('value') or {}
            if uv.get('amount'):
                contract_unit[ci.get('id')] = uv
    pe = t['procuringEntity']
    out = []
    for b in t.get('bids', []):
        tend = (b.get('tenderers') or [{}])[0]
        cp = tend.get('contactPoint') or {}
        bid_items = {bi.get('id'): bi for bi in b.get('items', [])}
        lv_by_lot = {lv.get('relatedLot'): lv for lv in b.get('lotValues', [])}
        if not lv_by_lot and b.get('value'):
            lv_by_lot[None] = {'value': b['value'], 'initialValue': b.get('initialValue') or b['value'], 'status': b.get('status')}
        for iid, it in items.items():
            lot = it.get('relatedLot')
            lv = lv_by_lot.get(lot) or (lv_by_lot.get(None) if len(lv_by_lot) == 1 else None)
            if lv is None and lot in lv_by_lot:
                lv = lv_by_lot[lot]
            if lv is None:
                continue  # bidder did not bid on this lot
            qty = it.get('quantity') or 0
            mult = UNIT_M.get(((it.get('unit') or {}).get('name') or '').lower().strip(), None)
            meters = qty * mult if mult else None
            val = lv.get('value') or {}
            init = lv.get('initialValue') or {}
            unit_val = ((bid_items.get(iid) or {}).get('unit') or {}).get('value') or {}
            per_m = basis = None
            if unit_val.get('amount') and mult:
                per_m, basis = unit_val['amount'] / mult, 'ціна за одиницю з пропозиції'
            elif (b.get('id'), lot) in winners and contract_unit.get(iid) and mult:
                unit_val = contract_unit[iid]
                per_m, basis = unit_val['amount'] / mult, 'ціна за одиницю з договору'
            elif meters and len(lot_items.get(lot, [])) == 1 and val.get('amount'):
                per_m, basis = val['amount'] / meters, 'сума лоту / метри'
            vat = val.get('valueAddedTaxIncluded')
            if vat is None:
                vat = unit_val.get('valueAddedTaxIncluded')
            per_m_novat = per_m / 1.2 if (per_m and vat) else per_m
            volt, sect = parse_desc(it.get('description'))
            out.append({
                'date': date[:10], 'tenderID': tid, 'status': t.get('status'), 'method': t.get('procurementMethodType'),
                'customer': pe['name'], 'region': (pe.get('address') or {}).get('region') or '',
                'item': it.get('description'), 'group': group_of(it.get('description')), 'voltage': volt, 'section': sect,
                'meters': meters, 'bidder': tend.get('name') or (tend.get('identifier') or {}).get('legalName'),
                'edrpou': (tend.get('identifier') or {}).get('id'),
                'per_m': round(per_m, 2) if per_m else None, 'per_m_novat': round(per_m_novat, 2) if per_m_novat else None,
                'vat_included': vat, 'basis': basis or 'лише загальна сума лоту',
                'lot_final': val.get('amount'), 'lot_initial': init.get('amount'),
                'winner': (b.get('id'), lot) in winners, 'bid_status': lv.get('status') or b.get('status'),
                'contact': cp.get('name'), 'phone': cp.get('telephone'), 'email': cp.get('email'),
            })
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--since', default='2025-01-01')
    ap.add_argument('--ids', default='')
    ap.add_argument('--queries', default='', help='comma-separated search texts to use instead of the default list')
    a = ap.parse_args()
    if a.queries:
        QUERIES[:] = [q for q in a.queries.split(',') if q]
    ids = [x for x in a.ids.split(',') if x] or search_ids()
    print('tenders to check', len(ids), flush=True)
    rows = []
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(lambda x: rows_for(x, a.since), ids):
            rows.extend(r)
    json.dump(rows, open(a.out, 'w'), ensure_ascii=False, indent=0)
    print('rows', len(rows), 'tenders with rows', len({r['tenderID'] for r in rows}), flush=True)
