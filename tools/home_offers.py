#!/usr/bin/env python3
"""Offerte della home (layout 17/10/2026): gira su CT102 e legge posts_history.json.
Stampa due blocchi separati da <!--SPLIT-->: le 3 schede in alto e le schede della sezione offerte.
Filtri come update_site.sh v1: post degli ultimi 3 giorni (anche quelli di gruppo), non terminati, sconto >= 12%,
niente blocklist/titoli rotti; in alto solo punteggio >= 105. Ordinati per punteggio. Titoli = product_headline (interi).
Esce con errore se le regole del canale non si importano: in quel caso il sito resta com'era."""
import datetime, html, json, re, sys
sys.path.insert(0, "/opt/paapi")
from pipeline import _brand_adj, BLOCKLIST_PENALTY, score_product, macro_category, product_headline

HIST = sys.argv[1] if len(sys.argv) > 1 else "/opt/paapi/data/posts_history.json"
BLOCK = ["smartwatch", "orologio smart", "power bank", "magnetic", "scarpe"]
BROKEN_RE = re.compile(r"AmazonIt|[A-Za-z]/[A-Z0-9]{3,}")
MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
MESI_LUNGHI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
E = html.escape


def num(s):
    if not s:
        return None
    s = str(s).replace("\xa0", " ").replace("€", "").strip().replace(".", "").replace(",", ".")
    m = re.search(r"[\d.]+", s)
    return float(m.group(0)) if m else None


def euro(n):
    return ("%.2f" % n).replace(".", ",") + " €"


def select(hist, today):
    rows, seen = [], set()
    for e in reversed(hist):   # piu' recenti prima, a parita' di punteggio
        if not isinstance(e, dict) or e.get("terminated"):
            continue
        title = e.get("title") or ""
        if any(b in title.lower() for b in BLOCK) or _brand_adj(title) == -BLOCKLIST_PENALTY or BROKEN_RE.search(title):
            continue
        try:
            ts = datetime.datetime.fromisoformat((e.get("ts") or e.get("posted_at_utc") or "").replace("Z", "+00:00"))   # i post di gruppo hanno solo posted_at_utc
        except ValueError:
            continue
        if (today - ts.date()).days > 3:
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
        rows.append({"e": e, "s": s, "nn": nn, "on": on, "img": img, "ts": ts, "head": product_headline(e), "short": product_headline(e, limit=56),
                     "url": e.get("url") or "https://t.me/NomadCrazyDeals", "score": score_product(e)})
    rows.sort(key=lambda r: -r["score"])
    return rows


def split(rows):
    """In alto: le 3 migliori con punteggio >= 105 (regola della home dal 15/06: niente largo consumo nei riquadri).
    Sezione offerte (17/10): le altre, fino a 5, gia' passate dai filtri del canale."""
    hero = [r for r in rows if r["score"] >= 105][:3]
    rest = [r for r in rows if r not in hero][:5]
    return hero, rest


def hero_card(r, cls):
    return (f'      <a href="{E(r["url"])}" target="_blank" rel="sponsored nofollow noopener" class="p-card {cls}">\n'
            f'        <div class="img"><img src="{E(r["img"])}" alt="{E(r["head"])}"><span class="badge">−{r["s"]}%</span></div>\n'
            f'        <div class="body"><div class="name">{E(r["short"])}</div><div class="price"><span class="now">{euro(r["nn"])}</span>'
            f'<span class="was">{euro(r["on"])}</span><span class="save">risparmi {round(r["on"] - r["nn"])} €</span></div></div>\n'
            f'      </a>')


def item(r, size):
    cat = (r["e"].get("category") or "").strip()
    day = f'{r["ts"].astimezone().day} {MESI[r["ts"].astimezone().month - 1]}'
    label = f"{E(cat)} · {day}" if cat else day
    return (f'      <div class="item {size}">\n'
            f'        <div class="thumb"><img src="{E(r["img"])}" alt="{E(r["head"])}" loading="lazy"><span class="off-badge">−{r["s"]}%</span></div>\n'
            f'        <div class="content">\n'
            f'          <div class="cat">{label}</div>\n'
            f'          <h3>{E(r["head"])}</h3>\n'
            f'          <div class="price-row"><span class="now">{euro(r["nn"])}</span><span class="was">{euro(r["on"])}</span>'
            f'<span class="save">−{round(r["on"] - r["nn"])} €</span></div>\n'
            f'          <div class="cta-row"><a href="{E(r["url"])}" target="_blank" rel="sponsored nofollow noopener" class="btn-sm">Vedi su Amazon</a></div>\n'
            f'        </div>\n'
            f'      </div>')


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    hero, rest = split(select(json.load(open(HIST)), now.date()))
    if not hero:
        raise SystemExit("nessuna offerta selezionabile: il sito resta com'era")
    print("\n".join(hero_card(r, c) for r, c in zip(hero, ("pc1", "pc2", "pc3"))))
    print("<!--SPLIT-->")
    loc = now.astimezone()
    print(f'      <p class="updated">Aggiornate il {loc.day} {MESI_LUNGHI[loc.month - 1]} {loc.year}</p>')
    if rest:
        sizes = ["featured", "normal", "small", "small", "small"]
        print("\n".join(item(r, z) for r, z in zip(rest, sizes)))
    else:
        print('      <p class="empty">Le altre offerte di questi giorni sono sul canale Telegram.</p>')


if __name__ == "__main__":
    main()
