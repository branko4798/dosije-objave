"""Objavljuje dospele objave iz schedule.json na Instagram i Facebook (Meta Graph API).

Pokreće ga GitHub Actions više puta oko 19h. Objava je dospela kad je njen datum+sat (Beograd)
prošao; posle uspeha upisuje se u posted.json da se ne objavi dvaput. Najviše jedna objava po
pokretanju. DRY_RUN=1 samo proverava token i pravi Instagram kontejnere, ništa ne objavljuje.
"""
import datetime, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

API = "https://graph.facebook.com/v26.0"
PAGE_ID = "1272241642650271"
IG_ID = "17841423785881213"
BASE = "https://branko4798.github.io/dosije-objave/"
TOKEN = os.environ["META_TOKEN"]
DRY = os.environ.get("DRY_RUN") == "1"
ONLY = os.environ.get("ONLY_ID", "")          # ručno: objavi baš ovu objavu
TZ = ZoneInfo("Europe/Belgrade")


def call(method, path, **params):
    params["access_token"] = TOKEN
    data = urllib.parse.urlencode(params).encode()
    url = f"{API}/{path}"
    req = urllib.request.Request(url + ("?" + data.decode() if method == "GET" else ""),
                                 data=None if method == "GET" else data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode()[:500]}")


def wait_ready(cid):
    for _ in range(30):
        s = call("GET", cid, fields="status_code").get("status_code")
        if s == "FINISHED":
            return
        if s in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG kontejner {cid}: {s}")
        time.sleep(5)
    raise RuntimeError(f"IG kontejner {cid} nije spreman")


def instagram(post):
    urls = [BASE + p for p in post["images"]]
    if len(urls) == 1:
        cid = call("POST", f"{IG_ID}/media", image_url=urls[0], caption=post["caption"])["id"]
    else:
        kids = [call("POST", f"{IG_ID}/media", image_url=u, is_carousel_item="true")["id"] for u in urls]
        for k in kids:
            wait_ready(k)
        cid = call("POST", f"{IG_ID}/media", media_type="CAROUSEL", children=",".join(kids),
                   caption=post["caption"])["id"]
    wait_ready(cid)
    if DRY:
        return f"dry:{cid}"
    return call("POST", f"{IG_ID}/media_publish", creation_id=cid)["id"]


def facebook(post):
    urls = [BASE + p for p in post["images"]]
    if DRY:
        return "dry:" + call("GET", PAGE_ID, fields="name")["name"]
    if len(urls) == 1:
        return call("POST", f"{PAGE_ID}/photos", url=urls[0], message=post["caption"])["id"]
    ids = [call("POST", f"{PAGE_ID}/photos", url=u, published="false")["id"] for u in urls]
    media = json.dumps([{"media_fbid": i} for i in ids])
    return call("POST", f"{PAGE_ID}/feed", message=post["caption"], attached_media=media)["id"]


def main():
    sched = json.load(open("schedule.json", encoding="utf-8"))
    posted = json.load(open("posted.json")) if os.path.exists("posted.json") else {}
    now = datetime.datetime.now(TZ)
    due = [p for p in sched if (p["id"] == ONLY if ONLY else
           datetime.datetime.fromisoformat(f"{p['date']}T{p['time']}").replace(tzinfo=TZ) <= now)
           and not (posted.get(p["id"], {}).get("ig") and posted.get(p["id"], {}).get("fb"))]
    if not due:
        print("Nema dospelih objava.")
        return
    post = due[0]
    rec = posted.setdefault(post["id"], {})
    print(f"Objava: {post['id']} {post['name']} ({len(post['images'])} slika){' [DRY]' if DRY else ''}")
    errors = []
    for key, fn in (("ig", instagram), ("fb", facebook)):
        if rec.get(key):
            continue
        try:
            rec[key] = fn(post)
            print(f"  {key}: {rec[key]}")
        except Exception as e:
            errors.append(f"{key}: {e}")
            print(f"  {key} GREŠKA: {e}")
    if not DRY:
        rec["at"] = now.isoformat(timespec="minutes")
        json.dump(posted, open("posted.json", "w"), indent=1)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
