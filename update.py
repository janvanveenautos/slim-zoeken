"""Werkt de voorraad van Slim zoeken bij vanaf janvanveenautos.nl.

Draait als GitHub Action. Leest /aanbod, haalt van nieuwe auto's de advertentie
en een foto op, en schrijft de nieuwe gegevens in index.html en fotos.json.
"""
import base64, io, json, re, sys, time, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from PIL import Image

SITE = "https://janvanveenautos.nl"
UA = "Mozilla/5.0 (compatible; JvV-SlimZoeken/1.0; +https://slimzoeken-janvanveenautos.nl)"
MAX_NEW = 60  # maximaal aantal nieuwe auto's per keer
TIME_BUDGET = 11 * 60  # seconden; daarna stopt het aanvullen van extra gegevens tot de volgende keer

FLAGS = [
    ("trekhaak", r"trekhaak"), ("acc", r"cruise control adaptief|adaptive cruise"), ("cruise", r"cruise control"),
    ("navi", r"navigatie"), ("camera", r"achteruitrijcamera|rondomzicht|\bcamera\b"), ("cam360", r"rondomzicht|360 camera"),
    ("pdcv", r"parkeersensor voor"), ("pdca", r"parkeersensor achter|parkeersensor voor en achter|parkeersensoren"),
    ("parkassist", r"parkeer-assistent"), ("stoelverw", r"voorstoelen verwarmd|verwarmde voorstoelen|stoelverwarming"),
    ("stuurverw", r"stuurwiel verwarmd"), ("achterbankverw", r"achterbank verwarmd"),
    ("leder", r"lederen bekleding|luxe lederen|^bekleding leder$"),
    ("halfleder", r"lederen/stoffen|lederen/alcantara|leder-stof|leder-alcantara|half leder"), ("alcantara", r"alcantara"),
    ("panorama", r"panorama"), ("carplay", r"apple carplay|android auto|appconnect|app-connect"),
    ("vcockpit", r"virtual cockpit|volledig digitaal instrumentenpaneel"), ("climate", r"climate|airco automatisch"),
    ("led", r"led koplampen|matrix|\bLED\b(?! (achter|dag|mist))"), ("matrix", r"matrix"), ("keyless", r"keyless"),
    ("eklep", r"elektrisch bedienbare achterklep"), ("dodehoek", r"dodehoek"), ("lane", r"rijstrook"), ("hud", r"head-up"),
    ("sfeer", r"sfeerverlichting"), ("dab", r"(?-i:DAB)"), ("draadloos", r"draadloze telefoonlader"),
    ("estoel", r"elektrisch verstelbare (voor|bestuurders|passagiers)?stoel|elektrisch verstelb\. passagiers|elektrisch verstelbare stoel"),
    ("massage", r"massage"), ("luchtvering", r"luchtvering"), ("zeven", r"derde rij|7p\.|7-zits"), ("warmtepomp", r"warmtepomp"),
    ("dakrails", r"dakrails"), ("sportstoel", r"sportstoelen"), ("verkeersbord", r"verkeersbord"), ("getint", r"getint glas|privacy"),
    ("sline", r"s line|s-line|r-line|\bFR\b|sportline"), ("vierwd", r"quattro|4motion|4x4|4drive"),
    ("premiumaudio", r"audio installatie premium|B&O|bang|canton|beats"),
]
FLAG_RE = [re.compile(p, re.I) for _, p in FLAGS]
KEYS = ['Aantal versnellingen', 'Bouwjaar', 'Kenteken', 'Kleur', 'Interieur', 'Bekleding', 'Vermogen', 'Carrosserie', 'Gewicht',
        'Max. trekgewicht', 'Laadvermogen', 'APK', 'Onderhoudsboekje aanwezig?', 'Bijtelling', 'Energielabel', 'Gemiddeld verbruik',
        'Aantal deuren', 'Aantal zitplaatsen', 'Actieradius', 'Batterijcapaciteit', 'Cilinderinhoud']
KEY_RE = re.compile("(" + "|".join(re.escape(k) for k in KEYS) + ")")


def code(i):
    return chr(97 + i) if i < 26 else chr(65 + i - 26)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def get(url, binary=False):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as e:  # noqa
            if attempt == 2:
                raise
            time.sleep(3)


def flags_for(opts, txt):
    out = ""
    for i, rx in enumerate(FLAG_RE):
        if any(rx.search(o) for o in opts) or rx.search(txt):
            out += code(i)
    return out


def read_cards():
    soup = BeautifulSoup(get(SITE + "/aanbod"), "html.parser")
    cards = []
    for p in soup.select(".each-product"):
        a = p.select_one('a[href*="/occasions-kopen/"]')
        if not a:
            continue
        m = re.search(r"/(\d+)-", a.get("href", ""))
        if not m:
            continue
        cards.append({
            "id": m.group(1),
            "mm": clean(p.select_one("h4").get_text() if p.select_one("h4") else ""),
            "uitv": clean(p.select_one("h6").get_text() if p.select_one("h6") else ""),
            "prijs": clean(p.select_one("td").get_text() if p.select_one("td") else ""),
            "range": clean(p.select_one(".product-range").get_text() if p.select_one(".product-range") else ""),
        })
    return cards


def read_detail(card):
    soup = BeautifulSoup(get(f"{SITE}/occasions-kopen/{card['id']}"), "html.parser")
    home = soup.select_one("#home")
    opts = [clean(li.get_text()) for li in home.select("li")] if home else []
    m1 = soup.select_one("#menu1")
    kt = ""
    if m1:
        for s in m1.select("style,script"):
            s.decompose()
        kt = clean(m1.get_text(" ")).replace("EU symbol NL", "")
    parts = KEY_RE.split(kt)
    k = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    top = {}
    for tr in soup.select("table tr"):
        cells = [clean(c.get_text()) for c in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) == 2 and cells[0] and cells[0] not in top:
            top[cells[0]] = cells[1]
    opts.append("bekleding " + k.get("Bekleding", ""))
    digits = lambda s: int(re.sub(r"\D", "", s or "") or 0)
    return {
        "fuel": (top.get("Brandstof") or "B")[0],
        "pk": digits(top.get("Vermogen") or k.get("Vermogen")),
        "kleur": k.get("Kleur", ""),
        "body": k.get("Carrosserie", ""),
        "trek": digits(k.get("Max. trekgewicht")),
        "verbruik": (k.get("Gemiddeld verbruik") or "").replace(" L/100KM", ""),
        "flags": flags_for(opts, card["mm"] + " " + card["uitv"]),
        "x": extra_from(k, opts[:-1]),
    }


def extra_from(k, opts):
    """Extra gegevens voor Slim zoeken: deuren, zitplaatsen, actieradius, label, APK, interieur en de optielijst."""
    def num(key):
        try:
            return int(re.sub(r"\D", "", (k.get(key) or "").split(",")[0]) or 0)
        except Exception:
            return 0
    def txt(key, n):
        return clean(k.get(key, ""))[:n]
    x = {"d": num("Aantal deuren"), "z": num("Aantal zitplaatsen"), "ar": num("Actieradius"),
         "el": txt("Energielabel", 4), "apk": txt("APK", 12), "i": txt("Interieur", 24), "b": txt("Bekleding", 24),
         "cc": num("Cilinderinhoud")}
    seen, lst = set(), []
    for o in opts:
        o = clean(o)[:70]
        if o and o.lower() not in seen:
            seen.add(o.lower())
            lst.append(o)
    x["opts"] = lst[:150]
    return {a: b for a, b in x.items() if b}


def row(card, ex):
    pm = re.search(r"€\s?([\d.]+)", card["prijs"])
    mnd = re.search(r"€\s?([\d.]+)\s*/\s*mnd", card["prijs"])
    rg = card["range"].split(" - ")
    km = int(re.sub(r"\D", "", rg[2])) if len(rg) > 2 and re.search(r"\d", rg[2]) else 0
    return [card["id"], card["mm"], card["uitv"], int(pm.group(1).replace(".", "")) if pm else None,
            "M" if "Marge" in card["prijs"] else "B", (rg[0] if rg else "")[3:], ((rg[1] if len(rg) > 1 else " ") or " ")[0],
            round(km / 100) / 10, ex["fuel"], ex["pk"], ex["kleur"], ex["body"], ex["trek"], ex["verbruik"], ex["flags"],
            mnd.group(1) if mnd else ""]


def thumb(car_id):
    for n in range(4):
        try:
            data = get(f"{SITE}/webservices/feed_images/{car_id}/{car_id}-{n}.jpg", binary=True)
            im = Image.open(io.BytesIO(data)).convert("RGB")
            w = 480
            im = im.resize((w, round(im.height * w / im.width)))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=68)
            return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            continue
    return None


def main():
    html = open("index.html", encoding="utf-8").read()
    m = re.search(r"^(let|const) CARS=(.*);$", html, re.M)
    if not m:
        sys.exit("CARS-regel niet gevonden in index.html")
    old = {c[0]: c for c in json.loads(m.group(2))}
    try:
        fotos = json.load(open("fotos.json", encoding="utf-8"))
    except Exception:
        fotos = {}

    cards = read_cards()
    if len(cards) < 50:
        sys.exit(f"Te weinig auto's gevonden op /aanbod ({len(cards)}); niets gewijzigd.")

    me = re.search(r"^const EXTRA=(.*);$", html, re.M)
    extra = {}
    if me:
        try:
            ej = json.loads(me.group(1))
            od = ej.get("o", [])
            for i, v in ej.get("c", {}).items():
                v = dict(v)
                v["opts"] = [od[j] for j in v.pop("o", []) if j < len(od)]
                extra[i] = v
        except Exception as e:
            print("EXTRA niet gelezen, begin opnieuw:", e)
    start = time.time()
    rows, new, filled = [], 0, 0
    for c in cards:
        o = old.get(c["id"])
        if o and me and c["id"] not in extra and time.time() - start < TIME_BUDGET:
            try:  # aanvullen: extra gegevens van een auto die al in de lijst stond
                ex = read_detail(c)
                extra[c["id"]] = ex.pop("x", {})
                filled += 1
                time.sleep(0.4)
            except Exception as e:
                print("Extra gegevens niet gelezen:", c["id"], e)
                ex = {"fuel": o[8], "pk": o[9], "kleur": o[10], "body": o[11], "trek": o[12], "verbruik": o[13], "flags": o[14]}
        elif o:
            ex = {"fuel": o[8], "pk": o[9], "kleur": o[10], "body": o[11], "trek": o[12], "verbruik": o[13], "flags": o[14]}
        elif new < MAX_NEW:
            try:
                ex = read_detail(c)
                extra[c["id"]] = ex.pop("x", {})
                new += 1
                time.sleep(0.5)
            except Exception as e:
                print("Advertentie niet gelezen:", c["id"], e)
                continue
        else:
            continue
        r = row(c, ex)
        if r[3]:
            rows.append(r)

    ids = {r[0] for r in rows}
    for i in list(fotos):
        if i not in ids:
            del fotos[i]
    for i in ids:
        if i not in fotos:
            t = thumb(i)
            if t:
                fotos[i] = t

    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    html = html[:m.start()] + f"{m.group(1)} CARS={data};" + html[m.end():]
    if me:
        od, idx, ec = [], {}, {}
        for i in sorted(ids):
            v = dict(extra.get(i) or {})
            if not v:
                continue
            nums = []
            for s in v.pop("opts", []):
                if s not in idx:
                    idx[s] = len(od)
                    od.append(s)
                nums.append(idx[s])
            if nums:
                v["o"] = nums
            ec[i] = v
        ejs = json.dumps({"v": 1, "o": od, "c": ec}, ensure_ascii=False, separators=(",", ":"))
        me2 = re.search(r"^const EXTRA=(.*);$", html, re.M)
        html = html[:me2.start()] + "const EXTRA=" + ejs.replace("</", "<\\/") + ";" + html[me2.end():]
        print(f"Extra gegevens: {len(ec)} auto's, {len(od)} verschillende opties, {filled} aangevuld.")
    today = datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%d-%m-%Y")
    html = re.sub(r'const STOCK_DATE="[^"]*";', f'const STOCK_DATE="{today}";', html, count=1)
    open("index.html", "w", encoding="utf-8").write(html)
    json.dump(fotos, open("fotos.json", "w", encoding="utf-8"), separators=(",", ":"))
    nieuw_ids = [r[0] for r in rows if r[0] not in old]
    json.dump(nieuw_ids, open("nieuw.json", "w"))
    gone = len(set(old) - ids)
    print(f"Klaar: {len(rows)} auto's, {new} nieuw, {gone} verdwenen, {len(fotos)} foto's.")


if __name__ == "__main__":
    main()
