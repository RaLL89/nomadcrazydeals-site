#!/usr/bin/env python3
"""Offerte della home (v4, 09/11/2026): gira su CT102 e legge posts_history.json.
Stampa due blocchi separati da <!--SPLIT-->: le 3 "offerte bomba" in alto e la griglia filtrabile della sezione offerte.

Filtri (invariati dal 26/10): non terminati, blocklist titoli/brand, titoli rotti, entrambi i prezzi e sconto >= 12%,
niente largo consumo/beauty sotto 5 € con sconto < 55%, immagine https, un solo record per ASIN, una sola scheda per brand.
In alto: le 3 migliori per punteggio (>= 105) dei post degli ultimi 3 giorni, come prima.
Griglia (v4): fino a 24 offerte dei post delle ultime 48 ore (72 se nelle 48 ore ce ne sono meno di 12), scelte con
punteggio + freschezza e un tetto morbido per categoria (la tecnologia vince sempre sul punteggio e riempirebbe tutto),
poi mostrate dalla piu' recente. Ogni scheda porta data-cat/off/price/ts/q per i filtri lato browser.
Le parti che cambiano solo con l'orologio stanno dentro <time>...</time>: update_site.sh v4 le toglie prima di
decidere se le offerte sono cambiate.
Esce con errore se le regole del canale non si importano o se non c'e' nessuna offerta per l'alto: il sito resta com'era.
Gira da stdin (python3 - <history>): non puo' importare file accanto a se'."""
import datetime, html, json, math, re, sys
sys.path.insert(0, "/opt/paapi")
from pipeline import _brand_adj, BLOCKLIST_PENALTY, score_product, macro_category, product_headline, _macro_v2

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover - CT102 ha Python 3.11
    TZ = None

HIST = sys.argv[1] if len(sys.argv) > 1 else "/opt/paapi/data/posts_history.json"
# 26/10 (audit): stessa lista di build_props.py (video) + "scarpe" (solo sito, scelta del 17/10).
BLOCK = ["smartwatch", "orologio smart", "power bank", "magnetic", "robot aspirapolvere", "aspirapolvere senza", "scarpe"]
BROKEN_RE = re.compile(r"AmazonIt|[A-Za-z]/[A-Z0-9]{3,}")
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
E = html.escape

HERO_DAYS = 3          # come prima: post degli ultimi 3 giorni di calendario
GRID_MAX = 24
GRID_MIN = 12          # sotto questa soglia la finestra passa da 48 a 72 ore
WINDOWS_H = (48, 72)
FRESH_BONUS = 40       # punti in piu' per un post appena uscito, scendono a 0 alla fine della finestra
CAT_SHARE = 0.30       # tetto morbido: al primo giro max 30% della griglia per categoria (24 -> 8)
CAT_FLOOR = 2          # prima di tutto le 2 migliori di ogni categoria presente nella finestra

CAT_LABEL = {"tech": "Tech", "casa": "Casa & Cucina", "gaming": "Gaming", "moda": "Moda", "beauty": "Beauty", "altro": "Altro"}
CAT_META = {"casa": 'Casa<span class="cat-x"> &amp; Cucina</span>'}   # sotto 380px resta "Casa", cosi' l'ora si legge
SUBTAG_CAT = {"tech": "tech", "cucina_casa": "casa", "casa": "casa", "moda": "moda", "bellezza_salute": "beauty",
              "food": "altro", "sport": "altro", "giochi": "altro"}
MACRO_CAT = {"tech": "tech", "casa": "casa", "moda": "moda", "beauty": "beauty"}
SUBTAG_RE = re.compile(r"ascsubtag=hook_[A-Z]_\d{8}_([a-z_]+?)_(?:nd|fam|ninja)\b")
GAMING_RE = re.compile(r"gaming|\bconsole\b|xbox|playstation|\bps5\b|\bps4\b|nintendo|videogioc|\bgamepad\b"
                       r"|\bswitch\b|\bcontroller\b|monitor gaming|cuffie gaming|mouse gaming|tastiera gaming")
# "switch" e "controller" da soli sono anche switch di rete, controller MIDI, centraline: li escludo se il contesto e' quello
NOT_GAMING_RE = re.compile(r"switch di rete|switch ethernet|gigabit|\bporte\b|\bmidi\b|irrigaz|\bdmx\b|\bled\b|interruttor|smart home")


def num(s):
    if not s:
        return None
    s = str(s).replace("\xa0", " ").replace("€", "").strip().replace(".", "").replace(",", ".")
    m = re.search(r"[\d.]+", s)
    return float(m.group(0)) if m else None


def euro(n):
    return ("%.2f" % n).replace(".", ",") + " €"


def local(dt):
    return dt.astimezone(TZ) if TZ else dt.astimezone()


def parse_ts(e):
    try:
        ts = datetime.datetime.fromisoformat((e.get("ts") or e.get("posted_at_utc") or "").replace("Z", "+00:00"))   # i post di gruppo hanno solo posted_at_utc
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)


def cat_key(e):
    """tech | casa | gaming | moda | beauty | altro. Prima la regola gaming (titolo + categoria fine), poi il token
    di categoria dell'ascsubtag del post, poi le regole del canale (macro_category, _macro_v2) sulla categoria fine."""
    title, fine = (e.get("title") or "").lower(), (e.get("category") or "").lower()
    text = f"{fine} {title}"
    if GAMING_RE.search(text) and not NOT_GAMING_RE.search(text):
        return "gaming"
    m = SUBTAG_RE.search(e.get("url") or "")
    if m and m.group(1) in SUBTAG_CAT:
        return SUBTAG_CAT[m.group(1)]
    macro = macro_category(fine)
    if macro == "altro":
        macro = _macro_v2(text)
    return MACRO_CAT.get(macro, "altro")


def select(hist, now):
    """Tutti i post che passano i filtri del sito, dal piu' recente; un solo record per ASIN (il piu' recente)."""
    today = now.date()
    dated = [(parse_ts(e), e) for e in hist if isinstance(e, dict)]
    dated = [(ts, e) for ts, e in dated if ts]
    dated.sort(key=lambda p: p[0], reverse=True)
    rows, seen = [], set()
    for ts, e in dated:
        if e.get("terminated"):
            continue
        title = e.get("title") or ""
        if any(b in title.lower() for b in BLOCK) or _brand_adj(title) == -BLOCKLIST_PENALTY or BROKEN_RE.search(title):
            continue
        if (today - ts.date()).days > HERO_DAYS:
            continue
        nn, on = num(e.get("price_now")), num(e.get("price_old"))
        try:
            s = int(float(e.get("saving_percent") or 0))
        except (TypeError, ValueError):
            s = 0
        if not nn or not on or s < 12:
            continue
        if macro_category(e.get("category") or "") in ("largo_consumo", "beauty") and 0 < nn < 5 and s < 55:
            continue
        img = e.get("image_url") or e.get("image") or ""
        if not img.startswith("https://") or e.get("asin") in seen:
            continue
        seen.add(e.get("asin"))
        head = product_headline(e)
        rows.append({"e": e, "s": s, "nn": nn, "on": on, "img": img, "ts": ts, "head": head, "short": product_headline(e, limit=56),
                     "url": e.get("url") or "https://t.me/NomadCrazyDeals", "score": score_product(e), "cat": cat_key(e),
                     "age_h": max(0.0, (now - ts).total_seconds() / 3600), "timed": deal_timed(e, now)})
    return rows


def deal_timed(e, now):
    """'A tempo' solo se Amazon ha dato una scadenza e non e' ancora passata: ritorna la scadenza (epoch) o 0."""
    end = e.get("deal_end")
    if not end:
        return 0
    try:
        d = datetime.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if not d.tzinfo:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return int(d.timestamp()) if d > now else 0


def brand_root(title):
    """Prima parola del titolo (come dedup_brand in build_props.py): 'LG OLED...' e 'LG QNED...' -> 'lg'."""
    words = re.sub(r"\s+", " ", title or "").strip().split()
    return words[0].lower().strip(",.") if words else ""


def root_of(r):
    return brand_root(r["head"] or r["e"].get("title") or "")


def dedup_brand(rows, taken=()):
    """26/10 (audit): una sola scheda per brand in home, resta la migliore per punteggio (prima erano uscite 2 TV LG insieme).
    v4: vale su tutta la home, quindi i brand gia' in alto non si ripetono nella griglia."""
    seen_b, out = set(taken), []
    for r in sorted(rows, key=lambda r: -r["score"]):
        root = root_of(r)
        if root in seen_b:
            continue
        seen_b.add(root)
        out.append(r)
    return out


def pick_hero(rows):
    """In alto: le 3 migliori con punteggio >= 105 (regola della home dal 15/06), una per brand."""
    return [r for r in dedup_brand(rows) if r["score"] >= 105][:3]


def pick_grid(rows, hero):
    """Griglia: post delle ultime 48 ore (72 se sono meno di 12), esclusi quelli in alto e i loro brand.
    Ordine di scelta = punteggio + bonus freschezza; giro 0: le CAT_FLOOR migliori di ogni categoria; giro 1: max
    CAT_SHARE della griglia per categoria; giro 2: i posti vuoti si riempiono con quello che resta. Mostrate dalla piu' recente."""
    hero_ids = {id(r) for r in hero}
    taken = {root_of(r) for r in hero}
    pool, window = [], WINDOWS_H[0]
    for window in WINDOWS_H:
        pool = dedup_brand([r for r in rows if id(r) not in hero_ids and r["age_h"] <= window], taken)
        if len(pool) >= GRID_MIN:
            break
    for r in pool:
        r["blend"] = r["score"] + FRESH_BONUS * max(0.0, 1 - r["age_h"] / window)
    pool.sort(key=lambda r: -r["blend"])
    n = min(GRID_MAX, len(pool))
    cap = max(3, math.ceil(n * CAT_SHARE))
    chosen, count = [], {}
    for r in pool:   # giro 0: le 2 migliori di ogni categoria presente (gaming e moda sono poche: senza, sparirebbero)
        if count.get(r["cat"], 0) < CAT_FLOOR and len(chosen) < n:
            chosen.append(r)
            count[r["cat"]] = count.get(r["cat"], 0) + 1
    for r in pool:
        if r not in chosen and len(chosen) < n and count.get(r["cat"], 0) < cap:
            chosen.append(r)
            count[r["cat"]] = count.get(r["cat"], 0) + 1
    for r in pool:
        if len(chosen) >= n:
            break
        if r not in chosen:
            chosen.append(r)
    return order_recent(chosen), window


def order_recent(rows):
    """Dalla piu' recente; i post di gruppo hanno lo stesso orario: a pari orario alterno le categorie."""
    out, groups = [], {}
    for r in sorted(rows, key=lambda r: (-r["ts"].timestamp(), -r["score"])):
        groups.setdefault(r["ts"], []).append(r)
    for ts in sorted(groups, reverse=True):
        g, last = groups[ts], None
        while g:
            i = next((k for k, r in enumerate(g) if r["cat"] != last), 0)
            r = g.pop(i)
            out.append(r)
            last = r["cat"]
    return out


def when(ts, now):
    """'oggi 14:32' / 'ieri 18:05' / '7 nov' (ora di Roma). Il browser lo ricalcola all'apertura."""
    t, n = local(ts), local(now)
    hm = t.strftime("%H:%M")
    days = (n.date() - t.date()).days
    if days == 0:
        return f"oggi {hm}"
    if days == 1:
        return f"ieri {hm}"
    return f"{t.day} {MESI[t.month - 1]}"   # piu' vecchie di ieri: solo il giorno, la riga resta corta su 2 colonne


def iso(ts):
    return local(ts).isoformat(timespec="minutes")


def flags(r, bomb):
    out = []
    if bomb:
        out.append('<span class="flag flag-bomb">🔥 Bomba</span>')
    if r["timed"]:
        out.append(f'<span class="flag flag-time" data-end="{r["timed"]}">⚡ A tempo</span>')   # il browser lo toglie dopo la scadenza
    return f'<span class="flags">{"".join(out)}</span>' if out else ""


def hero_card(r, cls):
    return (f'      <a href="{E(r["url"])}" target="_blank" rel="sponsored nofollow noopener" class="p-card {cls}">\n'
            f'        <div class="img"><img src="{E(r["img"])}" alt="{E(r["head"])}" width="500" height="500" fetchpriority="high"><span class="badge">−{r["s"]}%</span>{flags(r, True)}</div>\n'
            f'        <div class="body"><div class="name">{E(r["short"])}</div><div class="price"><span class="now">{euro(r["nn"])}</span>'
            f'<span class="was">{euro(r["on"])}</span><span class="save">risparmi {round(r["on"] - r["nn"])} €</span></div></div>\n'
            f'      </a>')


def search_text(r):
    e = r["e"]
    parts = [r["head"], e.get("title") or "", e.get("brand") or "", e.get("category") or "", CAT_LABEL[r["cat"]]]
    words, out = re.sub(r"\s+", " ", " ".join(parts).lower()).split(" "), []
    for w in words:   # parole uniche, per non gonfiare la pagina
        if w and w not in out:
            out.append(w)
    return " ".join(out)


def deal(r, now):
    ts = int(r["ts"].timestamp())
    saved = round(r["on"] - r["nn"])
    return (f'      <article class="deal" data-cat="{r["cat"]}" data-off="{r["s"]}" data-price="{r["nn"]:.2f}" data-ts="{ts}" data-q="{E(search_text(r))}">\n'
            f'        <div class="thumb"><img src="{E(r["img"])}" alt="" width="500" height="500" loading="lazy" decoding="async">'
            f'<span class="off-badge">−{r["s"]}%</span>{flags(r, r["s"] >= 40)}</div>\n'
            f'        <div class="content">\n'
            f'          <p class="meta"><span class="cat">{CAT_META.get(r["cat"], CAT_LABEL[r["cat"]])}</span> · <time datetime="{iso(r["ts"])}" data-ts="{ts}">{when(r["ts"], now)}</time></p>\n'
            f'          <h3>{E(r["head"])}</h3>\n'
            f'          <div class="price-row"><span class="now">{euro(r["nn"])}</span><span class="was">{euro(r["on"])}</span></div>\n'
            f'          <p class="saved">Risparmi {saved} €</p>\n'
            f'          <a href="{E(r["url"])}" target="_blank" rel="sponsored nofollow noopener" class="btn-sm">Vedi su Amazon</a>\n'
            f'        </div>\n'
            f'      </article>')


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = select(json.load(open(HIST)), now)
    hero = pick_hero(rows)
    if not hero:
        raise SystemExit("nessuna offerta selezionabile: il sito resta com'era")
    grid, window = pick_grid(rows, hero)
    print("\n".join(hero_card(r, c) for r, c in zip(hero, ("pc1", "pc2", "pc3"))))
    print("<!--SPLIT-->")
    loc = local(now)
    print(f'      <p class="updated" data-window="{window}">Aggiornato <time datetime="{loc.isoformat(timespec="minutes")}" data-ts="{int(now.timestamp())}" data-fmt="upd">oggi alle {loc.strftime("%H:%M")}</time></p>')
    if grid:
        print('      <div class="deals" id="deals">')
        print("\n".join(deal(r, now) for r in grid))
        print('      </div>')
    else:
        print('      <p class="empty">Le altre offerte di questi giorni sono sul canale Telegram.</p>')
    sys.stderr.write(f"home_offers v4: hero={len(hero)} griglia={len(grid)} finestra={window}h categorie="
                     f"{ {k: sum(r['cat'] == k for r in grid) for k in CAT_LABEL} }\n")


if __name__ == "__main__":
    main()
