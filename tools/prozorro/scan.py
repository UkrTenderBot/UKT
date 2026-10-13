"""Завантажує документи закупівель і шукає марки/ключові слова профілю.

Usage: python3 -I scan.py CANDS.json RESULTS.jsonl WORKDIR [--profile cable|isp]
Кожен рядок RESULTS: hits (марка → файл → фрагменти), volumes (марка → метри, п. 1), supply (поставка товару).
"""
import json, os, re, sys, time, zipfile, io, subprocess, shutil, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from profiles import get_profile, LAT  # noqa: E402

_args = sys.argv[1:]
_profile = 'cable'
if '--profile' in _args:
    _i = _args.index('--profile'); _profile = _args[_i + 1]; del _args[_i:_i + 2]
PROFILE = get_profile(_profile)
CANDS, OUT, WORK = _args[0], _args[1], _args[2]
os.makedirs(WORK, exist_ok=True)

PATTERNS = PROFILE['patterns']
UNIT_M = {'метр': 1, 'м': 1, 'метри': 1, 'метрів': 1, 'погонний метр': 1, 'м.п.': 1, 'мп': 1, 'кілометр': 1000, 'км': 1000}
_NUM = r'(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,](\d+))?'
RX_QTY_AFTER = re.compile(_NUM + r'\s*(км|м\.?\s?п\.?|м|метр\w*)(?![а-яіїєґa-z])', re.I)
RX_QTY_UNIT_FIRST = re.compile(r'(?<![а-яіїєґa-z])(км|м\.?\s?п\.?|м|метр\w*)\s*[|;:\t]?\s*' + _NUM + r'(?!\s*[хx×*])', re.I)


def _num(a, b):
    return float(re.sub(r'[ \u00a0]', '', a) + ('.' + b if b else ''))


RX_SECT = re.compile(r'(\d)\s?[хx×*]\s?(\d{2,3})(?:\s?/\s?(\d{1,3}))?')


def section_of(text):
    m = RX_SECT.search(text or '')
    return f'{m.group(1)}х{m.group(2)}' + (f'/{m.group(3)}' if m.group(3) else '') if m else ''


def _mult(unit):
    u = unit.lower().replace(' ', '')
    return 1000 if u.startswith('км') or u.startswith('кіломет') else 1


def qty_from_snippet(snip, mark_rx):
    """Метри після згадки марки у фрагменті (перший правдоподібний обсяг), або None."""
    n = snip.translate(LAT).upper()
    m = mark_rx.search(re.sub(r'\s+', ' ', n))
    tail = snip[m.end():] if m else snip
    tail = re.sub(r'\d\s?[хx×*]\s?\d+(?:[.,]\d+)?(?:\s?/\s?\d+)?\s*(мм|кв\.?\s?мм)?', ' ', tail, flags=re.I)  # перерізи
    tail = re.sub(r'\d+(?:[.,]\d+)?\s*кв(?![а-яі])', ' ', tail, flags=re.I)  # напруга
    for rx, order in ((RX_QTY_AFTER, 'nu'), (RX_QTY_UNIT_FIRST, 'un')):
        mm = rx.search(tail)
        if mm:
            if order == 'nu':
                val, unit = _num(mm.group(1), mm.group(2)), mm.group(3)
            else:
                unit, val = mm.group(1), _num(mm.group(2), mm.group(3))
            meters = val * _mult(unit)
            if 1 <= meters <= 500000:
                return meters
    return None


EXT_OK = ('.doc', '.docx', '.pdf', '.xls', '.xlsx', '.rtf', '.odt', '.ods', '.txt', '.zip', '.csv')


def get(url, raw=False, tries=4):
    for a in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=90)
            b = r.read()
            return b if raw else json.loads(b)
        except Exception:
            time.sleep(2 * (a + 1))
    return None


def norm(s):
    s = s.translate(LAT).upper()
    return re.sub(r'[\s\-­ ]+', '', s)


def find(text):
    """Return {mark: [snippets]}; normalized copy keeps single spaces as word boundaries."""
    hits = {}
    if not text:
        return hits
    keep, idx = [], []
    t2 = text.translate(LAT).upper()
    for i, ch in enumerate(t2):
        if ch == chr(0xAD):
            continue
        if ch.isspace():
            if keep and keep[-1] == ' ':
                continue
            ch = ' '
        keep.append(ch); idx.append(i)
    n = ''.join(keep)
    for mark, rx in PATTERNS.items():
        for m in rx.finditer(n):
            s = idx[m.start()]
            snip = re.sub(r'\s+', ' ', text[max(0, s - 40): s + 90]).strip()
            lst = hits.setdefault(mark, [])
            if len(lst) < 6 and snip not in lst:
                lst.append(snip)
    return hits


def text_of(path, tmpdir):
    p = path.lower()
    try:
        if p.endswith(('.docx', '.xlsx', '.odt', '.ods')):
            z = zipfile.ZipFile(path)
            parts = []
            for nm in z.namelist():
                if nm.endswith('.xml') and ('word/' in nm or 'sharedStrings' in nm or 'worksheets' in nm or nm == 'content.xml'):
                    x = z.read(nm).decode('utf-8', 'ignore')
                    x = re.sub(r'</w:p>|</row>|</text:p>', '\n', x)
                    parts.append(re.sub(r'<[^>]+>', '', x))
            return '\n'.join(parts)
        if p.endswith('.pdf'):
            r = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, timeout=120)
            return r.stdout.decode('utf-8', 'ignore')
        if p.endswith(('.txt', '.csv')):
            b = open(path, 'rb').read()
            for enc in ('utf-8', 'cp1251'):
                try:
                    return b.decode(enc)
                except Exception:
                    pass
        if p.endswith('.rtf'):
            x = open(path, 'rb').read().decode('latin-1')
            x = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode('cp1251', 'ignore'), x)
            x = re.sub(r'\\u(-?\d+)\??', lambda m: chr(int(m.group(1)) % 65536), x)
            return re.sub(r'\\[a-z]+-?\d* ?|[{}]', ' ', x)
        if p.endswith(('.doc', '.xls')):
            b = open(path, 'rb').read()
            parts = [b.decode('utf-16le', 'ignore'), b[1:].decode('utf-16le', 'ignore'), b.decode('cp1251', 'ignore')]
            keep = []
            for t in parts:
                keep.extend(re.findall(r'[\w\s.,;:()%№«»"\'/+×\-]{4,}', t))
            return '\n'.join(keep)
    except Exception as e:
        return ''
    return ''


def scan_tender(tid):
    summ = get(f'https://prozorro.gov.ua/api/tenders/{tid}/summary')
    if not summ or 'id' not in summ:
        return {'tenderID': tid, 'error': 'no summary'}
    t = get(f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{summ['id']}")
    if not t:
        return {'tenderID': tid, 'error': 'no tender'}
    t = t['data']
    res = {
        'tenderID': tid, 'id': t['id'], 'title': t.get('title'), 'status': t.get('status'),
        'method': t.get('procurementMethodType'),
        'customer': t['procuringEntity']['name'], 'edrpou': t['procuringEntity']['identifier']['id'],
        'region': t['procuringEntity'].get('address', {}).get('region'),
        'value': t.get('value', {}).get('amount'), 'vat': t.get('value', {}).get('valueAddedTaxIncluded'),
        'enquiryEnd': (t.get('enquiryPeriod') or {}).get('endDate'), 'tenderEnd': (t.get('tenderPeriod') or {}).get('endDate'),
        'items': [(i.get('description'), i.get('quantity'), (i.get('unit') or {}).get('name'), i['classification']['id']) for i in t.get('items', [])],
        'hits': {}, 'docs': [],
    }
    # metadata hits (title, items, description, criteria)
    meta = ' \n'.join([t.get('title') or '', t.get('description') or ''] + [str(i.get('description')) for i in t.get('items', [])])
    for crit in t.get('criteria', []):
        for g in crit.get('requirementGroups', []):
            for r in g.get('requirements', []):
                meta += '\n' + (r.get('title') or '') + ' ' + json.dumps(r.get('expectedValues') or r.get('expectedValue') or '', ensure_ascii=False)
    for k, v in find(meta).items():
        res['hits'].setdefault(k, {}).setdefault('[картка закупівлі]', v)
    # latest version of each document
    docs = {}
    for d in t.get('documents', []):
        docs[d['id']] = d
    tmp = os.path.join(WORK, tid); os.makedirs(tmp, exist_ok=True)
    for d in docs.values():
        title = d.get('title') or ''
        if not title.lower().endswith(EXT_OK):
            continue
        b = get(d['url'], raw=True)
        if not b:
            continue
        fn = os.path.join(tmp, re.sub(r'[^\w.\-]+', '_', title)[-120:])
        open(fn, 'wb').write(b)
        texts = []
        if fn.lower().endswith('.zip'):
            try:
                z = zipfile.ZipFile(io.BytesIO(b)); zd = fn + '_x'; os.makedirs(zd, exist_ok=True)
                for nm in z.namelist():
                    if nm.lower().endswith(EXT_OK[:-2]):
                        out = os.path.join(zd, re.sub(r'[^\w.\-]+', '_', os.path.basename(nm))[-120:])
                        open(out, 'wb').write(z.read(nm)); texts.append((title + ' / ' + os.path.basename(nm), text_of(out, tmp)))
            except Exception:
                pass
        else:
            texts.append((title, text_of(fn, tmp)))
        for name, tx in texts:
            res['docs'].append(name)
            for k, v in find(tx).items():
                res['hits'].setdefault(k, {})[name] = v
    shutil.rmtree(tmp, ignore_errors=True)
    res['volumes'] = volumes_of(t, res['hits'])
    res['supply'] = any(i['classification']['id'] in PROFILE['supply_cpvs'] for i in t.get('items', [])) \
        and not any(i['classification']['id'].startswith('45') for i in t.get('items', []))
    return res


def volumes_of(t, hits):
    """Обсяг у метрах за марками: спершу з позицій закупівлі (кількість × одиниця), інакше з фрагментів документів."""
    vol = {}
    for it in t.get('items', []):
        desc = (it.get('description') or '').translate(LAT).upper()
        desc = re.sub(r'\s+', ' ', desc)
        mult = UNIT_M.get(((it.get('unit') or {}).get('name') or '').lower().strip())
        if not mult or not it.get('quantity'):
            continue
        for mark, rx in PATTERNS.items():
            if rx.search(desc):
                v = vol.setdefault(mark, {'m': 0, 'src': 'позиції закупівлі', 'parts': []})
                v['m'] += it['quantity'] * mult
                v['parts'].append({'section': section_of(it.get('description')), 'm': it['quantity'] * mult})
                break
    for mark, files in hits.items():
        if mark in vol:
            continue
        best, best_parts = 0, []
        for fname, snips in files.items():
            seen, total, parts = set(), 0, []
            for sn in snips:
                q = qty_from_snippet(sn, PATTERNS[mark])
                if q and sn not in seen:
                    seen.add(sn); total += q; parts.append({'section': section_of(sn), 'm': q})
            if total > best:
                best, best_parts = total, parts
        if best:
            vol[mark] = {'m': round(best, 1), 'src': 'документи (оцінка)', 'parts': best_parts}
    return vol


cands = json.load(open(CANDS))
done = {}
if os.path.exists(OUT):
    for line in open(OUT):
        try:
            done[json.loads(line)['tenderID']] = 1
        except Exception:
            pass
todo = [k for k in cands if k not in done]
print('todo', len(todo), flush=True)
with open(OUT, 'a') as fo, ThreadPoolExecutor(6) as ex:
    for i, r in enumerate(ex.map(scan_tender, todo)):
        fo.write(json.dumps(r, ensure_ascii=False) + '\n'); fo.flush()
        if r.get('hits'):
            print('HIT', r['tenderID'], list(r['hits']), (r.get('title') or '')[:60], flush=True)
        if i % 20 == 0:
            print('progress', i, flush=True)
print('done', flush=True)
