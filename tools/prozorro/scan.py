import json, os, re, sys, time, zipfile, io, subprocess, shutil, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

CANDS, OUT, WORK = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(WORK, exist_ok=True)

LAT = str.maketrans('ABCEHKMOPTXaceopxyiI', 'АВСЕНКМОРТХасеорхуіІ')
PATTERNS = {
    'АСБл': re.compile(r'(?<![А-ЯІЇЄҐ])(?:Ц)?АСБ(?:2)?Л'),
    'ААБл': re.compile(r'(?<![А-ЯІЇЄҐ])(?:Ц)?ААБ(?:2|Н)?Л'),
    'ААШв': re.compile(r'(?<![А-ЯІЇЄҐ])(?:Ц)?ААШВ'),
    'АПвЕгаПу': re.compile(r'(?<![А-ЯІЇЄҐ])АПВЕГАП'),
}
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
    return res


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
