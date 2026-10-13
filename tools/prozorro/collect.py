import json, urllib.request, sys, time
from concurrent.futures import ThreadPoolExecutor
OUT = sys.argv[1]
def post(body):
    for a in range(4):
        try:
            r = urllib.request.Request("https://prozorro.gov.ua/api/search/tenders", data=json.dumps(body).encode(), headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
            return json.load(urllib.request.urlopen(r, timeout=60))
        except Exception as e: time.sleep(2*(a+1))
    return {'data':[], 'total':0}
ST = sys.argv[2].split(",") if len(sys.argv) > 2 else ["active.tendering","active.enquiries"]
cpvs = ["31320000-5","31321000-2","31321100-3","31321200-4","31321210-7","31321220-0","31321300-5","31300000-9","31310000-2","31340000-1","31344000-9","44320000-9","44321000-6","31330000-8","31350000-4","31681400-2","31680000-6"]
texts = ["кабель","кабелі","кабелю","кабельна продукція","кабельних","ААБл","ААШв","АСБл","АПвЕгаПу","АПвЕгП","АПвЕП","СБл","ЦАСБ","АВБбШв","муфти кабельні","кабельні муфти"]
qs = [{"cpv":[c]} for c in cpvs] + [{"text":t} for t in texts]
found = {}
for q in qs:
    page = 1
    while True:
        d = post({**q, "status":ST, "page":page})
        for x in d['data']:
            found.setdefault(x['tenderID'], x)
        if page*20 >= min(d.get('total',0), 1000) or not d['data']: break
        page += 1
    print(q, d.get('total'), len(found), flush=True)
json.dump(found, open(OUT,'w'), ensure_ascii=False)
