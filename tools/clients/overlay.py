"""Overlay VELES client base onto the installers list; build xlsx + call-calendar PDF.
Usage: python3 -I overlay.py INSTALLERS.xlsx CLIENTS.xlsx OUTDIR
"""
import datetime as dt
import json
import re
import sys

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

INST, CLI, OUT = sys.argv[1:4]
START = dt.date(2026, 10, 27)
PER_DAY = 10
SLOTS = ['09:30', '09:50', '10:10', '10:30', '10:50', '11:10', '11:30', '11:50', '14:00', '14:20']

RED, ORANGE, YELLOW, BLUE, NEW = 'red', 'orange', 'yellow', 'blue', 'new'
STATUS = {
    RED: ('🔴 НЕ ДЗВОНИТИ — працюємо', 'FFC7CE', '9C0006'),
    ORANGE: ('🟠 Клієнт ВЕЛЕС — можна дзвонити', 'FFE0B2', '8A4B00'),
    YELLOW: ('🟡 Перевірити в базі перед дзвінком', 'FFF2CC', '7F6000'),
    BLUE: ('🔵 Ваш клієнт — дзвоните самі', 'DDEBF7', '1F4E78'),
    NEW: ('🟢 Новий — дзвонити', 'E2EFDA', '375623'),
}
# explicit decisions from the VELES comments (by EDRPOU)
DECIDE = {
    '37851081': (RED, 'клієнт Дениса, брали у 2023'),
    '43221923': (RED, 'Черкаси — територія ФОП Баранник, туди не йдемо'),
    '41444303': (RED, 'працює через «Кабель Ком»'),
    '40833701': (RED, 'клієнт колеги та Дениса'),
    '39835082': (RED, 'клієнт Ксенії'),
    '41218526': (RED, 'клієнт колеги (дир. Олексій, постачання Андрій), беруть світильники'),
    '36767497': (RED, 'клієнт Дениса з 2020'),
    '42591801': (RED, 'клієнт Марини з 2019'),
    '21377944': (RED, 'запити йдуть як від ШРБУ-48 (Ксенія)'),
    '37787692': (RED, 'клієнт колеги («мої»)'),
    '40355726': (RED, 'клієнт Марини та Дениса'),
    '3163908356': (RED, 'клієнт Колі з 2021'),
    '43298268': (RED, 'клієнт Ксенії'),
    '22815333': (RED, 'клієнт колеги («мої»)'),
    '19315887': (RED, 'клієнт Ксенії'),
    '3242413169': (RED, 'клієнт Колі з 2021'),
    '38897076': (ORANGE, 'у колеги, дозволив дзвонити; але переважно беруть напряму на заводі'),
    '30975988': (ORANGE, 'у колеги, дозволив дзвонити'),
    '36785343': (ORANGE, 'у колеги (Микола, Черкаси), дозволив дзвонити'),
    '34724556': (ORANGE, 'є в базі, ні за ким не закріплений, ні разу не брали'),
    '40169080': (YELLOW, 'за кодом немає, але є за назвою — уточнити, чий клієнт'),
    '33649667': (BLUE, 'закріплений за вами'),
}


def key(s):
    return re.sub(r'[^0-9A-ZА-ЯІЇЄҐ]', '', str(s or '').upper())


def phone(v):
    if v is None:
        return ''
    if isinstance(v, float):
        v = str(int(v))
    d = re.sub(r'\D', '', str(v))
    if len(d) == 12 and d.startswith('380'):
        return f'+380 {d[3:5]} {d[5:8]} {d[8:10]} {d[10:]}'
    return str(v)


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip(' ,')


ws_c = openpyxl.load_workbook(CLI, data_only=True)['Лист1']
clients = {}
for r in ws_c.iter_rows(min_row=2, values_only=True):
    if r[0]:
        clients[key(r[0])] = {'name': r[0], 'edrpou': str(r[1] or ''), 'comment': clean(r[2]), 'plant': clean(r[3])}

ws_i = openpyxl.load_workbook(INST, data_only=True)['Монтажники (дзвонити)']
rows = []
for r in ws_i.iter_rows(min_row=2, values_only=True):
    if not r[0]:
        continue
    c = clients.get(key(r[0]))
    edr = c['edrpou'] if c else ''
    com = c['comment'] if c else ''
    if edr in DECIDE:
        st, note = DECIDE[edr]
    elif c is None:
        st, note = NEW, 'немає в базі ВЕЛЕС'
    else:
        st, note = NEW, 'немає в базі ВЕЛЕС'
    if c and c['plant']:
        note += f'; клієнт заводу: {c["plant"]}'
    rows.append({
        'name': r[0], 'city': clean(r[1]), 'regions': clean(r[2]), 'contact': clean(r[3]), 'phone': phone(r[4]),
        'email': clean(r[5]), 'last': r[6].date() if isinstance(r[6], dt.datetime) else None, 'marks': clean(r[7]),
        'customers': clean(r[8]), 'todo': clean(r[9]), 'tender': clean(r[10]), 'flag': clean(r[11]),
        'edrpou': edr, 'veles_raw': com or ('—' if c else 'не знайдено в базі ВЕЛЕС'), 'status': st, 'note': note,
    })


# ---------- call order & offers ----------
def short_obj(todo):
    m = re.search(r'виграв «([^»]+)»', todo)
    return m.group(1).rstrip('.… ') if m else ''


def offer(r):
    marks = r['marks'].replace('АПвЕгаПу/АПвЕгП', 'АПвЕгаПу/АПвЕгП') or 'силовий'
    obj = short_obj(r['todo'])
    if obj:
        o = obj if len(obj) <= 70 else obj[:68].rsplit(' ', 1)[0] + '…'
        txt = (f'Вітаємо з перемогою («{o}»). Кабель {marks} заводу «Південкабель» під цей об’єкт: '
               f'реєструємо об’єкт на заводі, ціна під ваш кошторис за 1 день, паспорти якості, доставка.')
    else:
        cust = re.sub(r'\s*\(\d+\)', '', r['customers'].split(';')[0]).strip()
        cust = cust if len(cust) <= 45 else cust[:43].rsplit(' ', 1)[0] + '…'
        txt = (f'Кабель {marks} заводу «Південкабель» під ваші об’єкти ({cust}): '
               f'реєстрація об’єкта на заводі, ціна під кошторис, паспорти якості, доставка.')
    if 'Активно подається' in r['todo']:
        txt += ' Порахуємо ціну під тендери, на які подаєтесь — до подачі.'
    if r['status'] == ORANGE:
        txt += ' ⚠ ' + r['note'] + '.'
    if r['status'] == YELLOW:
        txt = '⚠ Спершу уточнити в колег за назвою. ' + txt
    return txt


callable_ = [r for r in rows if r['status'] != RED]
callable_.sort(key=lambda r: (0 if '🆕' in r['todo'] else 1, -(r['last'] or dt.date(2000, 1, 1)).toordinal()))
day = START
i = 0
while i < len(callable_):
    if day.weekday() >= 5:
        day += dt.timedelta(days=1)
        continue
    for s in SLOTS[:PER_DAY]:
        if i >= len(callable_):
            break
        callable_[i]['call_date'], callable_[i]['call_time'] = day, s
        callable_[i]['offer'] = offer(callable_[i])
        i += 1
    day += dt.timedelta(days=1)

# ---------- xlsx ----------
wb = openpyxl.Workbook()
ws = wb.active
ws.title = 'Монтажники + клієнти'
head = ['№', 'Статус', 'Монтажник', 'ЄДРПОУ', 'Коментар бази ВЕЛЕС (як є)', 'Висновок', 'Дата дзвінка', 'Час',
        'Коротка пропозиція', 'Місто', 'Регіони робіт', 'Контактна особа', 'Телефон', 'E-mail', 'Остання перемога',
        'Марки в ТЗ', 'Основні замовники', 'Що робити', 'Закупівля (UA-номер)', 'Позначка']
widths = [5, 30, 36, 12, 42, 40, 12, 7, 60, 18, 16, 24, 18, 28, 12, 22, 40, 60, 24, 10]
thin = Side(style='thin', color='BFBFBF')
ws.append(head)
for c, w in enumerate(widths, 1):
    ws.column_dimensions[get_column_letter(c)].width = w
    cell = ws.cell(1, c)
    cell.font = Font(bold=True, color='FFFFFF')
    cell.fill = PatternFill('solid', fgColor='1F4E78')
    cell.alignment = Alignment(wrap_text=True, vertical='center', horizontal='center')
order = {RED: 0, ORANGE: 2, YELLOW: 1, BLUE: 3, NEW: 4}
rows_sorted = sorted(rows, key=lambda r: (order[r['status']], r.get('call_date') or dt.date(2100, 1, 1), r.get('call_time', '')))
for n, r in enumerate(rows_sorted, 1):
    label, bg, fg = STATUS[r['status']]
    ws.append([n, label, r['name'], r['edrpou'], r['veles_raw'], r['note'] if r['status'] != NEW else 'дзвонити за календарем',
               r.get('call_date'), r.get('call_time', ''), r.get('offer', '—  не дзвонити' if r['status'] == RED else ''),
               r['city'], r['regions'], r['contact'], r['phone'], r['email'], r['last'], r['marks'], r['customers'],
               r['todo'], r['tender'], r['flag']])
    row = ws.max_row
    for c in range(1, len(head) + 1):
        cell = ws.cell(row, c)
        cell.alignment = Alignment(wrap_text=True, vertical='top')
        cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        if r['status'] == RED:
            cell.fill = PatternFill('solid', fgColor=bg)
            cell.font = Font(color=fg, bold=c in (2, 3))
        elif c in (2, 5, 6):
            cell.fill = PatternFill('solid', fgColor=bg)
            cell.font = Font(color=fg, bold=c == 2)
    ws.cell(row, 7).number_format = 'DD.MM.YYYY'
    ws.cell(row, 15).number_format = 'DD.MM.YYYY'
ws.freeze_panes = 'D2'
ws.auto_filter.ref = f'A1:{get_column_letter(len(head))}{ws.max_row}'
ws.row_dimensions[1].height = 32

# summary
sm = wb.create_sheet('Зведення', 0)
sm['A1'] = 'Накладання бази клієнтів ВЕЛЕС на базу монтажників'
sm['A1'].font = Font(bold=True, size=14)
sm['A2'] = f'Монтажників у списку: {len(rows)}; знайдено в базі ВЕЛЕС: {sum(1 for r in rows if r["edrpou"])}. Сформовано {dt.date.today():%d.%m.%Y}.'
sm.append([])
sm.append(['Статус', 'Кількість', 'Що робимо'])
what = {RED: 'не дзвонимо — працює інший менеджер / інша схема', ORANGE: 'дзвонимо, враховуючи коментар колеги',
        YELLOW: 'спершу уточнити в колег, потім дзвонити', BLUE: 'ваш клієнт — дзвоните як своєму',
        NEW: 'дзвонимо за календарем'}
for st in (RED, ORANGE, YELLOW, BLUE, NEW):
    label, bg, fg = STATUS[st]
    sm.append([label, sum(1 for r in rows if r['status'] == st), what[st]])
    for c in range(1, 4):
        sm.cell(sm.max_row, c).fill = PatternFill('solid', fgColor=bg)
        sm.cell(sm.max_row, c).font = Font(color=fg, bold=c == 1)
for c in range(1, 4):
    sm.cell(4, c).font = Font(bold=True, color='FFFFFF')
    sm.cell(4, c).fill = PatternFill('solid', fgColor='1F4E78')
last_call = max(r['call_date'] for r in callable_)
sm.append([])
sm.append([f'Календар дзвінків: {START:%d.%m.%Y} – {last_call:%d.%m.%Y}, до {PER_DAY} дзвінків на робочий день; першими — свіжі перемоги, де кабель ще не закуплений.'])
sm.column_dimensions['A'].width = 42
sm.column_dimensions['B'].width = 12
sm.column_dimensions['C'].width = 60

# full VELES base for reference
fb = wb.create_sheet('База ВЕЛЕС (319)')
fb.append(['Монтажник', 'ЄДРПОУ', 'Коментар ВЕЛЕС', 'Клієнт заводу', 'Є в списку монтажників'])
inlist = {key(r['name']) for r in rows}
for k, c in clients.items():
    fb.append([c['name'], c['edrpou'], c['comment'], c['plant'], 'так' if k in inlist else ''])
for c, w in zip('ABCDE', (50, 14, 60, 18, 14)):
    fb.column_dimensions[c].width = w
for c in range(1, 6):
    fb.cell(1, c).font = Font(bold=True, color='FFFFFF')
    fb.cell(1, c).fill = PatternFill('solid', fgColor='1F4E78')
fb.freeze_panes = 'A2'
fb.auto_filter.ref = f'A1:E{fb.max_row}'
wb.save(f'{OUT}/Монтажники_накладання_база_ВЕЛЕС.xlsx')

json.dump({'rows': rows, 'calls': callable_}, open(f'{OUT}/overlay.json', 'w'), ensure_ascii=False, default=str, indent=0)
print({st: sum(1 for r in rows if r['status'] == st) for st in STATUS}, 'calls', len(callable_), 'last', last_call)
