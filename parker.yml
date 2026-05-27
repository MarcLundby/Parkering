#!/usr/bin/env python3
"""
Avantpark Auto Check-in — direkte HTTP POST
Omgår Cloudflare Turnstile ved at sende formularen direkte.
Format: "AB12345:+4512345678,CD67890:+4587654321"
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from bs4 import BeautifulSoup

URL           = "https://vqr.avantpark.dk/QRCode/EnterPlate?Hash=jZqtyJgHJ"
VERIFIED_FILE = Path("verified_plates.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": URL,
}


def indlæs_verificerede() -> set[str]:
    if VERIFIED_FILE.exists():
        return set(json.loads(VERIFIED_FILE.read_text()))
    return set()


def gem_verificerede(plader: set[str]):
    VERIFIED_FILE.write_text(json.dumps(sorted(plader), indent=2, ensure_ascii=False))
    log.info(f"  💾 verified_plates.json opdateret: {sorted(plader)}")


def hent_plader() -> list[dict]:
    raw = os.environ.get("NUMMERPLADER", "").strip()
    if not raw:
        log.error("❌ NUMMERPLADER secret mangler.")
        sys.exit(1)
    plader = []
    for del_ in raw.split(","):
        del_ = del_.strip()
        if ":" in del_:
            plade, tlf = del_.split(":", 1)
            plader.append({"plade": plade.strip().upper(), "tlf": tlf.strip()})
        else:
            log.warning(f"  ⚠️  Ignorerer '{del_}' — mangler telefonnummer")
    if not plader:
        log.error("❌ Ingen gyldige nummerplader fundet.")
        sys.exit(1)
    return plader


def check_in(plade: str, tlf: str, første_gang: bool) -> bool:
    log.info(f"  ▷ {plade}  {'🆕 første gang → SMS til ' + tlf if første_gang else '✔ known → ingen kvittering'}")

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Trin 1: Hent siden og udtræk skjulte formfelter ──────
    try:
        r = session.get(URL, timeout=15)
        r.raise_for_status()
        log.info(f"  GET {r.status_code}")
    except Exception as e:
        log.error(f"  ❌ Kunne ikke hente siden: {e}")
        return False

    soup = BeautifulSoup(r.text, "html.parser")

    # Find form action
    form = soup.find("form")
    action = form.get("action", "") if form else ""
    if not action.startswith("http"):
        base = "https://vqr.avantpark.dk"
        action = base + action if action.startswith("/") else URL

    log.info(f"  Form action: {action}")

    # Saml alle skjulte felter (inkl. CSRF tokens)
    data = {}
    if form:
        for inp in form.find_all("input"):
            name  = inp.get("name", "")
            value = inp.get("value", "")
            if name:
                data[name] = value

    log.info(f"  Skjulte felter fundet: {list(data.keys())}")

    # ── Trin 2: Udfyld formularen ─────────────────────────────
    # Nummerplade — find det rigtige feltnavn
    plate_field = next(
        (k for k in data if any(w in k.lower() for w in ["plate", "nummerplade", "regnr", "licens"])),
        None
    )
    if not plate_field and form:
        txt = form.find("input", {"type": "text"})
        plate_field = txt.get("name") if txt else None
    if plate_field:
        data[plate_field] = plade
        log.info(f"  Nummerplade feltnavn: '{plate_field}' = {plade}")
    else:
        log.warning("  ⚠️  Kunne ikke finde nummerpladefelt — gætter 'plate'")
        data["plate"] = plade

    # Kvittering — find radio-feltnavnet
    receipt_field = next(
        (k for k in data if any(w in k.lower() for w in ["receipt", "kvittering", "notification", "sms"])),
        None
    )
    if not receipt_field and form:
        radio = form.find("input", {"type": "radio"})
        receipt_field = radio.get("name") if radio else None

    if receipt_field:
        if første_gang:
            # Find SMS-værdien
            radios = form.find_all("input", {"type": "radio", "name": receipt_field}) if form else []
            sms_val = next((r.get("value","") for r in radios if "sms" in r.get("value","").lower() or "sms" in str(r).lower()), "2")
            data[receipt_field] = sms_val
            # Telefonnummer
            tel_inp = form.find("input", {"type": "tel"}) if form else None
            tel_name = tel_inp.get("name") if tel_inp else "phone"
            data[tel_name] = tlf
            log.info(f"  Kvittering: SMS ({sms_val}), tlf: {tlf}")
        else:
            radios = form.find_all("input", {"type": "radio", "name": receipt_field}) if form else []
            no_val = next((r.get("value","0") for r in radios if r.get("value","") in ["0","none","no"]), "0")
            data[receipt_field] = no_val
            log.info(f"  Kvittering: ingen ({no_val})")
    else:
        log.warning("  ⚠️  Kunne ikke finde kvitteringsfelt")

    log.info(f"  POST data: { {k: ('***' if 'token' in k.lower() or 'csrf' in k.lower() else v) for k,v in data.items()} }")

    # ── Trin 3: Send formularen ───────────────────────────────
    try:
        r2 = session.post(action, data=data, timeout=15, allow_redirects=True)
        log.info(f"  POST {r2.status_code} → {r2.url}")

        body = BeautifulSoup(r2.text, "html.parser").get_text(separator=" ", strip=True)
        log.info(f"  Svar: {body[:300]}")

        if any(w in body.lower() for w in ["bekræft", "registrer", "confirm", "success", "tak", "gennemført", "registered"]):
            log.info(f"  ✅ {plade} — GENNEMFØRT")
            return True
        if "EnterPlate" not in r2.url:
            log.info(f"  ✅ {plade} — GENNEMFØRT (URL skiftede)")
            return True

        log.warning(f"  ⚠️  {plade} — Ingen bekræftelse")
        return False

    except Exception as e:
        log.error(f"  ❌ POST fejlede: {e}")
        return False


def main():
    log.info("═" * 50)
    log.info("  Avantpark Auto Check-in")
    log.info("═" * 50)

    plader       = hent_plader()
    verificerede = indlæs_verificerede()
    nye_plader   = set()
    fejl         = 0

    for i, item in enumerate(plader):
        plade       = item["plade"]
        tlf         = item["tlf"]
        første_gang = plade not in verificerede

        ok = check_in(plade, tlf, første_gang)

        if ok and første_gang:
            verificerede.add(plade)
            nye_plader.add(plade)
        elif not ok:
            fejl += 1

        if i < len(plader) - 1:
            time.sleep(30)

    if nye_plader:
        gem_verificerede(verificerede)
        log.info(f"  🆕 Nye plader verificeret: {', '.join(nye_plader)}")

    log.info("─" * 50)
    log.info(f"  Færdig: {len(plader) - fejl}/{len(plader)} lykkedes")
    log.info("═" * 50)

    if fejl > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

