#!/bin/bash
# update_site.sh v3 (17/10/2026) - gira sull'HOST mayhem (cron 13:15) al posto della v1.
# Home nuova (petrolio, listino perforato, tema scuro): due blocchi di offerte, DEALS (3 riquadri in alto)
# e DEALS2 (sezione offerte). Li genera tools/home_offers.py del repo del sito, sui post veri di CT102.
# Se il generatore fallisce o i marcatori mancano, esce senza toccare il sito (set -e).
# Rollback: cp /root/update_site.sh.bak_pre_v3_* /root/update_site.sh  (+ git revert del commit della home)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CT_DATA=102
CT_SITE=104
SITE_DIR=/home/claude/projects/nomadcrazydeals-site
INDEX_REMOTE="$SITE_DIR/public/index.html"
TMP=/tmp/ncd_site_build
mkdir -p "$TMP"

echo "=== 0. il checkout del sito deve essere su main ==="
BR=$(pct exec $CT_SITE -- su - claude -c "cd $SITE_DIR && git rev-parse --abbrev-ref HEAD")
if [ "$BR" != "main" ]; then echo "checkout su '$BR', non main: esco senza toccare nulla"; exit 1; fi

echo "=== 1. genero le offerte dai post veri (CT$CT_DATA) ==="
pct pull $CT_SITE "$SITE_DIR/tools/home_offers.py" "$TMP/home_offers.py"
pct exec $CT_DATA -- /opt/paapi/venv/bin/python3 - /opt/paapi/data/posts_history.json < "$TMP/home_offers.py" > "$TMP/offers.html"
grep -q 'class="p-card' "$TMP/offers.html"
grep -q '<!--SPLIT-->' "$TMP/offers.html"
echo "--- offerte generate ---"; grep -o 'class="name">[^<]*\|<h3>[^<]*' "$TMP/offers.html" || true

echo "=== 2. pull index da CT$CT_SITE ==="
pct pull $CT_SITE "$INDEX_REMOTE" "$TMP/index.html"

echo "=== 3. sostituisco tra i marcatori ==="
OFFERS="$TMP/offers.html" python3 - << 'PYEOF'
import os, re
idx = "/tmp/ncd_site_build/index.html"
hero, rest = open(os.environ["OFFERS"], encoding="utf-8").read().split("<!--SPLIT-->")
s = open(idx, encoding="utf-8").read()
for m in ("DEALS", "DEALS2"):
    if s.count(f"<!--{m}_START-->") != 1 or s.count(f"<!--{m}_END-->") != 1:
        raise SystemExit(f"marcatori {m} assenti o duplicati: non tocco l'index")
s2 = re.sub(r"<!--DEALS_START-->.*?<!--DEALS_END-->", lambda m: "<!--DEALS_START-->\n" + hero.strip("\n") + "\n<!--DEALS_END-->", s, flags=re.S)
s2 = re.sub(r"<!--DEALS2_START-->.*?<!--DEALS2_END-->", lambda m: "<!--DEALS2_START-->\n" + rest.strip("\n") + "\n<!--DEALS2_END-->", s2, flags=re.S)
if s2 == s:
    print("Offerte invariate: niente da aggiornare."); raise SystemExit(0)
open(idx, "w", encoding="utf-8").write(s2)
print("index aggiornato, righe:", s2.count(chr(10)))
PYEOF

echo "=== 4. push index su CT$CT_SITE ==="
pct push $CT_SITE "$TMP/index.html" "$INDEX_REMOTE"

echo "=== 5. commit + push come utente claude ==="
pct exec $CT_SITE -- su - claude -c "cd $SITE_DIR && git add public/index.html && git commit -m 'auto: offerte aggiornate' && git push origin main 2>&1 | tail -5 || echo 'NIENTE DA COMMITTARE o errore push'"

echo "=== FATTO. Cloudflare ribuilda in ~1-2 min ==="
