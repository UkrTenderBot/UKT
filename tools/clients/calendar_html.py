"""Build call-calendar HTML from overlay.json. Usage: python3 -I calendar_html.py overlay.json OUT.html"""
import datetime as dt
import html
import itertools
import json
import sys

d = json.load(open(sys.argv[1]))
calls, rows = d['calls'], d['rows']
DAYS = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П’ятниця", 'Субота', 'Неділя']
COL = {'orange': '#FFE0B2', 'yellow': '#FFF2CC', 'blue': '#DDEBF7', 'new': '#FFFFFF'}
TAG = {'orange': 'клієнт ВЕЛЕС — можна', 'yellow': 'перевірити', 'blue': 'ваш клієнт', 'new': 'новий'}
e = html.escape


def fd(s):
    return dt.date.fromisoformat(s).strftime('%d.%m.%Y') if s and s != 'None' else '—'


css = """
@page { size: A4 landscape; margin: 10mm 9mm 11mm 9mm; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 7.6pt; color: #1b1b1b; }
h1 { font-size: 15pt; margin: 0 0 2mm; color: #1F4E78; }
h2 { font-size: 11pt; margin: 0 0 2mm; color: #fff; background: #1F4E78; padding: 1.6mm 3mm; border-radius: 1.5mm; }
.day { page-break-before: always; }
.sub { color: #555; margin-bottom: 3mm; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th { background: #DCE6F1; text-align: left; padding: 1.2mm; font-size: 7.2pt; border: 0.2mm solid #A6B8CC; }
td { padding: 1.2mm; vertical-align: top; border: 0.2mm solid #C9D3DE; word-wrap: break-word; }
tr { page-break-inside: avoid; }
.t { font-weight: bold; font-size: 9pt; text-align: center; }
.n { font-weight: bold; }
.tag { display: inline-block; font-size: 6.4pt; padding: 0.2mm 1.2mm; border-radius: 1mm; background: #eee; margin-top: 0.6mm; }
.box { border: 0.3mm solid #1F4E78; border-radius: 1.5mm; padding: 2.5mm 3.5mm; margin: 3mm 0; }
.red td { background: #FFC7CE; color: #9C0006; }
.res { color: #999; }
.grid { display: flex; gap: 4mm; }
.grid > div { flex: 1; }
"""

out = [f'<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>Календар дзвінків монтажникам</title><style>{css}</style></head><body>']
first, last = fd(calls[0]['call_date']), fd(calls[-1]['call_date'])
cnt = {s: sum(1 for r in rows if r['status'] == s) for s in ('red', 'orange', 'yellow', 'blue', 'new')}
out.append(f'<h1>Календар дзвінків монтажникам — кабель «Південкабель»</h1>'
           f'<div class="sub">{first} – {last} · {len(calls)} дзвінків, до 10 на робочий день · першими — свіжі перемоги, де кабель ще не закуплений · '
           f'з бази виключено {cnt["red"]} клієнтів, з якими вже працюємо (червоні нижче)</div>')
out.append('<div class="grid"><div class="box"><b>Як почати розмову (30 сек.)</b><br>'
           '«Добрий день, [ім’я]. Мене звати … , компанія ВЕК — постачаємо кабель заводу «Південкабель». '
           'Бачу, ви виграли [об’єкт] — кабель уже закупили? Ми реєструємо ваш об’єкт на заводі, '
           'тому даємо проектну ціну під ваш кошторис, а не прайсову. Порахуємо за 1 день — на яку пошту надіслати?»<br><br>'
           '<b>Мета дзвінка:</b> специфікація / кошторис на пошту → КП за шаблоном ВЕК (вносимо тільки ціни).<br>'
           '<b>Не надсилаємо прайс</b> — лише розрахунок під конкретний об’єкт.</div>'
           '<div class="box"><b>Позначки</b><br>'
           '<span class="tag" style="background:#E2EFDA">новий</span> — у базі ВЕЛЕС немає, дзвонимо.<br>'
           '<span class="tag" style="background:#FFE0B2">клієнт ВЕЛЕС — можна</span> — є в базі, колега дозволив; врахувати коментар.<br>'
           '<span class="tag" style="background:#FFF2CC">перевірити</span> — є збіг за назвою, спершу уточнити в колег.<br>'
           '<span class="tag" style="background:#DDEBF7">ваш клієнт</span> — закріплений за вами.<br>'
           '<span class="tag" style="background:#FFC7CE;color:#9C0006">не дзвонити</span> — працює інший менеджер (у календар не включено).<br><br>'
           f'Разом: новий {cnt["new"]} · можна {cnt["orange"]} · перевірити {cnt["yellow"]} · ваш {cnt["blue"]} · <b style="color:#9C0006">не дзвонити {cnt["red"]}</b></div></div>')
# red list
out.append('<div class="box" style="border-color:#9C0006"><b style="color:#9C0006">НЕ ДЗВОНИТИ — працюємо (клієнти інших менеджерів / інша схема)</b>'
           '<table style="margin-top:2mm"><tr><th style="width:30%">Компанія</th><th style="width:9%">ЄДРПОУ</th><th style="width:15%">Регіон</th><th>Чому</th></tr>')
for r in rows:
    if r['status'] == 'red':
        out.append(f'<tr class="red"><td class="n">{e(r["name"])}</td><td>{e(r["edrpou"])}</td><td>{e(r["regions"])}</td><td>{e(r["note"])}</td></tr>')
out.append('</table></div>')

for day, items in itertools.groupby(calls, key=lambda c: c['call_date']):
    items = list(items)
    dd = dt.date.fromisoformat(day)
    out.append(f'<div class="day"><h2>{DAYS[dd.weekday()]}, {dd:%d.%m.%Y} — {len(items)} дзвінків</h2><table>'
               '<tr><th style="width:4.5%">Час</th><th style="width:19%">Компанія</th><th style="width:15%">Контакт</th>'
               '<th style="width:16%">Привід</th><th style="width:33%">Коротка пропозиція</th><th style="width:12.5%">Результат</th></tr>')
    for c in items:
        bg = COL[c['status']]
        loc = ', '.join(x for x in (c['city'], c['regions']) if x)
        reason = f'Перемога {fd(c["last"])}<br>{e(c["marks"] or "марки не вказані")}'
        if c['tender']:
            reason += f'<br><span style="color:#555">{e(c["tender"])}</span>'
        out.append(
            f'<tr style="background:{bg}"><td class="t">{c["call_time"]}</td>'
            f'<td><span class="n">{e(c["name"])}</span><br><span style="color:#555">{e(loc)}</span><br>'
            f'<span class="tag" style="background:{"#E2EFDA" if c["status"] == "new" else bg};border:0.2mm solid #bbb">{TAG[c["status"]]}</span></td>'
            f'<td>{e(c["contact"] or "—")}<br><b>{e(c["phone"] or "—")}</b><br><span style="font-size:6.6pt">{e(c["email"])}</span></td>'
            f'<td>{reason}</td><td>{e(c["offer"])}</td>'
            f'<td class="res">☐ дозвонився<br>☐ КП/кошторис<br>☐ передзвонити ____</td></tr>')
    out.append('</table></div>')
out.append('</body></html>')
open(sys.argv[2], 'w').write('\n'.join(out))
