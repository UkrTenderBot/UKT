"""Потенціал продажу і пріоритет A/B/C (п. 1).

Usage:
  python3 -I potential.py PRICES.json SCAN_RESULTS.jsonl [--ids UA-...,UA-...] > potential.json

PRICES.json — рядки вкладки «Ціни учасників» (A:T, як у таблиці або data/prices_2026_rows.json):
  E (4) марка, M (12) ціна за м без ПДВ, Q (16) «так» = переможець.
SCAN_RESULTS.jsonl — вихід scan.py (поля volumes, value, supply).

Ціна за метр = середня ціна переможців для тієї ж марки й перерізу (G), інакше для марки загалом;
якщо переможців немає — середня всіх пропозицій.
Потенціал = Σ (метри × ціна). Якщо обсягів немає: для поставки — очікувана вартість закупівлі,
для робіт — потенціал не рахується, пріоритет за очікуваною вартістю (≥ 5 млн — A, ≥ 1 млн — B).
Пороги за потенціалом: ≥ 500 000 грн — A, ≥ 100 000 грн — B, інакше C.
"""
import argparse
import json
import sys

A_POT, B_POT = 500_000, 100_000
A_VAL, B_VAL = 5_000_000, 1_000_000


def avg_prices(rows):
    win, all_ = {}, {}
    for r in rows:
        if len(r) < 17:
            continue
        mark, sect, price, is_win = r[4], (r[6] or ''), r[12], str(r[16]).strip().lower() == 'так'
        if not mark or not isinstance(price, (int, float)) or price <= 0:
            continue
        for key in ([mark, f'{mark}|{sect}'] if sect else [mark]):
            all_.setdefault(key, []).append(price)
            if is_win:
                win.setdefault(key, []).append(price)
    out = {}
    for m in all_:
        src = win.get(m) or all_[m]
        out[m] = {'price': round(sum(src) / len(src), 2), 'basis': 'переможці' if m in win else 'усі пропозиції',
                  'n': len(src)}
    return out


def rate(res, prices):
    lines, total, missing = [], 0.0, []
    for mark, v in (res.get('volumes') or {}).items():
        for part in v.get('parts') or [{'section': '', 'm': v['m']}]:
            key = f"{mark}|{part['section']}" if part['section'] else mark
            p = prices.get(key) or prices.get(mark)
            label = f"{mark} {part['section']}".strip()
            if not p:
                missing.append(label)
                continue
            s = part['m'] * p['price']
            total += s
            lines.append(f"{label}: {part['m']:,.0f} м × {p['price']:,.2f} = {s:,.0f} грн "
                         f"({v['src']}; ціна {'за перерізом' if key in prices else 'середня по марці'})".replace(',', ' '))
    value = res.get('value') or 0
    if total:
        prio = 'A' if total >= A_POT else 'B' if total >= B_POT else 'C'
        basis = 'обсяг × середня ціна'
    elif res.get('supply') and value:
        total, basis = float(value), 'очікувана вартість поставки'
        prio = 'A' if total >= A_POT else 'B' if total >= B_POT else 'C'
    else:
        prio = 'A' if value >= A_VAL else 'B' if value >= B_VAL else 'C'
        basis = 'лише очікувана вартість робіт (обсяг кабелю не знайдено)'
        total = None
    return {'tenderID': res['tenderID'], 'potential': round(total) if total else None, 'priority': prio,
            'basis': basis, 'lines': lines, 'no_price_for': missing}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('prices')
    ap.add_argument('scan')
    ap.add_argument('--ids', default='')
    a = ap.parse_args()
    prices = avg_prices(json.load(open(a.prices)))
    ids = {x for x in a.ids.split(',') if x}
    out = []
    for line in open(a.scan):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if ids and r.get('tenderID') not in ids:
            continue
        if not r.get('hits'):
            continue
        out.append(rate(r, prices))
    json.dump({'prices_per_m': prices, 'tenders': out}, sys.stdout, ensure_ascii=False, indent=1)
