#!/usr/bin/env python3
"""
Avantpark Auto Check-in — med første-gangs SMS-bekræftelse
===========================================================
Nye nummerplader: SMS-kvittering første gang (verifikation)
Kendte nummerplader: Ingen kvittering herefter

Secrets i GitHub:
  NUMMERPLADER  →  AB12345:+4512345678,CD67890:+4587654321
                   (plade:telefonnummer adskilt med komma)

Filen verified_plates.json gemmes i dit repo og opdateres automatisk.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL            = "https://vqr.avantpark.dk/QRCode/EnterPlate?Hash=jZqtyJgHJ"
VERIFIED_FILE  = Path("verified_plates.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Indlæs og gem verificerede plader ─────────────────────────

def indlæs_verificerede() -> set[str]:
    if VERIFIED_FILE.exists():
        return set(json.loads(VERIFIED_FILE.read_text()))
    return set()


def gem_verificerede(plader: set[str]):
    VERIFIED_FILE.write_text(json.dumps(sorted(plader), indent=2, ensure_ascii=False))
    log.info(f"  💾 verified_plates.json opdateret: {sorted(plader)}")


# ── Parse nummerplader fra secret ─────────────────────────────

def hent_plader() -> list[dict]:
    """
    Parser 'AB12345:+4512345678,CD67890:+4587654321'
    til [{"plade": "AB12345", "tlf": "+4512345678"}, ...]
    """
    raw = os.environ.get("NUMMERPLADER", "").strip()
    if not raw:
        log.error("❌ NUMMERPLADER secret mangler.")
        log.error("   Format: AB12345:+4512345678,CD67890:+4587654321")
        sys.exit(1)

    plader = []
    for del_ in raw.split(","):
        del_ = del_.strip()
        if ":" in del_:
            plade, tlf = del_.split(":", 1)
            plader.append({"plade": plade.strip().upper(), "tlf": tlf.strip()})
        else:
            log.warning(f"  ⚠️  Ignorerer '{del_}' — mangler telefonnummer (format: PLADE:+4512345678)")

    if not plader:
        log.error("❌ Ingen gyldige nummerplader fundet.")
        sys.exit(1)

    return plader


# ── Selve check-in logikken ────────────────────────────────────

def check_in(plade: str, tlf: str, første_gang: bool) -> bool:
    kvittering = "SMS" if første_gang else "ingen"
    log.info(f"  ▷ {plade}  {'🆕 første gang → SMS til ' + tlf if første_gang else '✔ known → ingen kvittering'}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="da-DK",
        )
        page = context.new_page()

        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=30_000)

            # Udfyld nummerplade
            plate_input = page.locator(
                "input[type='text'], input[name*='plate' i], "
                "input[name*='nummerplade' i], input[id*='plate' i]"
            ).first
            plate_input.wait_for(state="visible", timeout=15_000)
            plate_input.click()
            plate_input.fill(plade)

            if første_gang:
                # Vælg SMS-kvittering
                try:
                    sms_radio = page.get_by_text("SMS-kvittering", exact=True)
                    sms_radio.click(timeout=5_000)
                except Exception:
                    # Prøv radio-knap direkte
                    page.locator("input[type='radio'][value*='sms' i], input[type='radio']:nth-of-type(3)").click(timeout=5_000)

                # Udfyld telefonnummer (feltet dukker op efter klik)
                tlf_input = page.locator(
                    "input[type='tel'], input[name*='phone' i], "
                    "input[name*='mobile' i], input[name*='telefon' i], "
                    "input[placeholder*='telefon' i], input[placeholder*='mobil' i]"
                ).first
                tlf_input.wait_for(state="visible", timeout=8_000)
                tlf_input.fill(tlf)
                log.info(f"  SMS-nr udfyldt: {tlf}")

            else:
                # Ingen kvittering
                try:
                    page.locator("input[type='radio'][value='0'], input[type='radio']:first-of-type").first.click(timeout=5_000)
                except Exception:
                    page.get_by_text("Ingen kvittering ønsket", exact=True).click(timeout=5_000)

            # Vent på Cloudflare Turnstile
            log.info("  Venter på Cloudflare…")
            time.sleep(8)

            # Indsend
            submit = page.locator("button[type='submit'], input[type='submit']").first
            submit.wait_for(state="visible", timeout=10_000)
            submit.click()

            # Bekræft success
            try:
                page.wait_for_url("**/Confirm**", timeout=15_000)
                log.info(f"  ✅ {plade} — GENNEMFØRT")
                return True
            except PlaywrightTimeoutError:
                body = page.inner_text("body")
                if any(w in body.lower() for w in ["bekræft", "registrer", "confirm", "success", "tak"]):
                    log.info(f"  ✅ {plade} — GENNEMFØRT")
                    return True
                log.warning(f"  ⚠️  {plade} — Usikker på resultatet")
                page.screenshot(path=f"fejl_{plade}.png")
                return False

        except Exception as e:
            log.error(f"  ❌ {plade} — Fejl: {e}")
            try:
                page.screenshot(path=f"fejl_{plade}.png")
            except Exception:
                pass
            return False
        finally:
            browser.close()


# ── Main ───────────────────────────────────────────────────────

def main():
    log.info("═" * 50)
    log.info("  Avantpark Auto Check-in")
    log.info("═" * 50)

    plader       = hent_plader()
    verificerede = indlæs_verificerede()
    nye_plader   = set()
    fejl         = 0

    for i, item in enumerate(plader):
        plade      = item["plade"]
        tlf        = item["tlf"]
        første_gang = plade not in verificerede

        ok = check_in(plade, tlf, første_gang)

        if ok and første_gang:
            verificerede.add(plade)
            nye_plader.add(plade)
        elif not ok:
            fejl += 1

        if i < len(plader) - 1:
            time.sleep(30)

    # Gem opdateret liste (workflow committer filen bagefter)
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
