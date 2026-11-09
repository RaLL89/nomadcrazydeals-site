#!/bin/bash
# update_site.sh v4 (09/11/2026) - gira sull'HOST mayhem (cron 9:15, 13:15, 17:15, 21:15) al posto della v3.
# Home v4: in alto le 3 offerte bomba (DEALS), sotto la griglia filtrabile fino a 24 offerte (DEALS2).
# Le genera tools/home_offers.py del repo del sito, sui post veri di CT102 (eseguito da stdin).
# Novita' rispetto alla v3:
#  - "niente di nuovo": confronta i blocchi generati con quelli gia' nella home togliendo le parti che cambiano solo
#    con l'orologio (<time>...</time>: "Aggiornato oggi alle", "oggi 14:32"). Se le offerte sono le stesse esce con 0
#    PRIMA di toccare il checkout (niente commit, niente push).
#  - un git push fallito fa uscire lo script con errore e una riga chiara nel log (la v3 lo inghiottiva);
#    "niente da committare" resta un'uscita pulita. Un commit rimasto non pubblicato viene ripubblicato al giro dopo.
# Come la v3: se il generatore fallisce o i marcatori mancano/sono doppi, esce senza toccare il sito (set -e).
# Rollback: cp /root/update_site.sh.bak_pre_s_* /root/update_site.sh  (+ crontab /root/crontab.bak_pre_s_*)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CT_DATA=102
CT_SITE=104
SITE_DIR=/home/claude/projects/nomadcrazydeals-site
INDEX_REMOTE="$SITE_DIR/public/index.html"
TMP=/tmp/ncd_site_build
mkdir -p "$TMP"
echo "##### $(date '+%F %T') update_site v4 #####"

site() { pct exec $CT_SITE -- su - claude -c "cd $SITE_DIR && $1"; }

echo "=== 0. il checkout del sito deve essere su main ==="
BR=$(site "git rev-parse --abbrev-ref HEAD")
if [ "$BR" != "main" ]; then echo "checkout su '$BR', non main: esco senza toccare nulla"; exit 1; fi
AHEAD=$(site "git rev-list --count origin/main..main" || echo 0)
if [ "$AHEAD" != "0" ]; then
  echo "ci sono $AHEAD commit non pubblicati (push fallito in un giro precedente?): riprovo il push"
  if ! site "git push origin main > /tmp/ncd_push.log 2>&1; rc=\$?; tail -5 /tmp/ncd_push.log; exit \$rc"; then
    echo "ERRORE: git push fallito, il sito online NON e' aggiornato"; exit 1
  fi
fi

echo "=== 1. genero le offerte dai post veri (CT$CT_DATA) ==="
pct pull $CT_SITE "$SITE_DIR/tools/home_offers.py" "$TMP/home_offers.py"
pct exec $CT_DATA -- /opt/paapi/venv/bin/python3 - /opt/paapi/data/posts_history.json < "$TMP/home_offers.py" > "$TMP/offers.html"
grep -q 'class="p-card' "$TMP/offers.html"
grep -q '<!--SPLIT-->' "$TMP/offers.html"
echo "--- offerte generate: $(grep -c 'class="p-card' "$TMP/offers.html") in alto, $(grep -c '<article class="deal"' "$TMP/offers.html" || true) nella griglia ---"
grep -o 'class="name">[^<]*' "$TMP/offers.html" || true

echo "=== 2. pull index da CT$CT_SITE ==="
pct pull $CT_SITE "$INDEX_REMOTE" "$TMP/index.html"

echo "=== 3. sostituisco tra i marcatori (se le offerte sono cambiate) ==="
set +e
OFFERS="$TMP/offers.html" python3 - << 'PYEOF'
import os, re
idx = "/tmp/ncd_site_build/index.html"
hero, rest = open(os.environ["OFFERS"], encoding="utf-8").read().split("<!--SPLIT-->")
s = open(idx, encoding="utf-8").read()
for m in ("DEALS", "DEALS2"):
    if s.count(f"<!--{m}_START-->") != 1 or s.count(f"<!--{m}_END-->") != 1:
        raise SystemExit(f"marcatori {m} assenti o duplicati: non tocco l'index")
TIME = re.compile(r"<time\b[^>]*>.*?</time>", re.S)
def block(text, m):
    return re.search(rf"<!--{m}_START-->(.*?)<!--{m}_END-->", text, re.S).group(1).strip("\n")
def norm(t):
    return TIME.sub("<time/>", t).strip()
if norm(block(s, "DEALS")) == norm(hero.strip("\n")) and norm(block(s, "DEALS2")) == norm(rest.strip("\n")):
    print("Offerte invariate (cambia solo l'orario): niente da aggiornare."); raise SystemExit(3)
s2 = re.sub(r"<!--DEALS_START-->.*?<!--DEALS_END-->", lambda m: "<!--DEALS_START-->\n" + hero.strip("\n") + "\n<!--DEALS_END-->", s, flags=re.S)
s2 = re.sub(r"<!--DEALS2_START-->.*?<!--DEALS2_END-->", lambda m: "<!--DEALS2_START-->\n" + rest.strip("\n") + "\n<!--DEALS2_END-->", s2, flags=re.S)
open(idx, "w", encoding="utf-8").write(s2)
print("index aggiornato, righe:", s2.count(chr(10)), "byte:", len(s2.encode()))
PYEOF
RC=$?
set -e
if [ $RC -eq 3 ]; then echo "=== FATTO: niente di nuovo, checkout non toccato ==="; exit 0; fi
if [ $RC -ne 0 ]; then echo "ERRORE nella sostituzione (rc=$RC): il sito resta com'era"; exit $RC; fi

echo "=== 4. push index su CT$CT_SITE ==="
pct push $CT_SITE "$TMP/index.html" "$INDEX_REMOTE"

echo "=== 5. commit + push come utente claude ==="
site "git add public/index.html && if git diff --cached --quiet; then echo 'NIENTE DA COMMITTARE'; exit 10; fi; git commit -q -m 'auto: offerte aggiornate' && git log -1 --format='commit %h %s'" && RC=0 || RC=$?
if [ $RC -eq 10 ]; then echo "=== FATTO: niente da committare ==="; exit 0; fi
if [ $RC -ne 0 ]; then echo "ERRORE: git commit fallito (rc=$RC)"; exit 1; fi
if ! site "git push origin main > /tmp/ncd_push.log 2>&1; rc=\$?; tail -5 /tmp/ncd_push.log; exit \$rc"; then
  echo "ERRORE: git push fallito, il sito online NON e' aggiornato (il commit resta in locale e si riprova al prossimo giro)"; exit 1
fi

echo "=== FATTO. Cloudflare ribuilda in ~1-2 min ==="
