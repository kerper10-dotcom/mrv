#!/usr/bin/env python3
"""
Njuskalo Monitor - Mrvica Bot
==============================
Prati zemljista (Zadar + okolica) i Toyota Yaris Hibrid + Corolla, Mazda, stanove i kuće.
Salje Telegram obavijesti za nove oglase na dva chata.

Pokreće se preko GitHub Actions (public repo - unlimited minutes).
"""

import os
import re
import sqlite3
import time
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

# =============================================================================
#  KONFIGURACIJA — @njuskalo_mrvica_bot
# =============================================================================

URLS = {
    "ZEMLJISTA ZADAR": (
        "https://www.njuskalo.hr/prodaja-zemljista/zadar"
        "?landTypeId=235"
    ),
    "ZEMLJISTA OKOLICA": (
        "https://www.njuskalo.hr/prodaja-zemljista"
        "?price%5Bmax%5D=100000&landTypeId=235"
        "&geo%5BlocationIds%5D=8692%2C8696%2C8809%2C8797"
    ),
    "ZEMLJISTA GALOVAC": (
        "https://www.njuskalo.hr/prodaja-zemljista/galovac"
        "?price%5Bmax%5D=150000&landTypeId=235"
    ),
    "YARIS HIBRID": (
        "https://www.njuskalo.hr/rabljeni-auti/toyota-yaris"
        "?yearManufactured%5Bmin%5D=2020&fuelTypeId=604"
    ),
    "COROLLA": (
        "https://www.njuskalo.hr/auti/toyota-corolla"
        "?price%5Bmax%5D=25000&yearManufactured%5Bmin%5D=2019"
    ),
    "MAZDA CX-30": (
        "https://www.njuskalo.hr/rabljeni-auti/mazda-cx-30"
        "?transmissionTypeId%5B611%5D=611&transmissionTypeId%5B612%5D=612&transmissionTypeId%5B613%5D=613"
    ),
    "STANOVI ZADAR KVARTOVI": (
        "https://www.njuskalo.hr/prodaja-stanova"
        "?price%5Bmax%5D=260000"
        "&geo%5BlocationIds%5D=8758%2C13722%2C13593%2C8797%2C8762%2C8770%2C8771%2C8772%2C8776%2C8777%2C8778%2C8781%2C8782%2C8783%2C8785%2C8787%2C8790%2C8791"
        "&livingArea%5Bmin%5D=55"
    ),
    "KUCE ZADAR OKOLICA": (
        "https://www.njuskalo.hr/prodaja-kuca"
        "?geo%5BlocationIds%5D=1695%2C1725%2C1726%2C8692%2C8696%2C8697%2C8743%2C8809%2C8810%2C8811"
        "&price%5Bmin%5D=5000&price%5Bmax%5D=330000"
    ),
}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
_extra = os.environ.get("TELEGRAM_EXTRA_CHATS", "1327890117")
TELEGRAM_EXTRA_CHATS = [c.strip() for c in _extra.split(",") if c.strip()]

PAGES_PER_URL = 2
DELAY_BETWEEN_URLS = 2.0
HEADLESS = True
BROWSER_TIMEOUT = 30000
DB_FILE = str(Path(__file__).parent / "njuskalo_mrvica.db")
TELEGRAM_MAX_CHARS = 4000
SKIP_BEFORE_DATE = "28.05.2026"

# =============================================================================
#  SQLite BAZA
# =============================================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_ads ("
        "  id INTEGER PRIMARY KEY,"
        "  category TEXT NOT NULL,"
        "  first_seen TEXT NOT NULL DEFAULT (datetime('now','localtime')),"
        "  title TEXT,"
        "  url TEXT,"
        "  pub_date TEXT DEFAULT ''"
        ")"
    )
    try:
        conn.execute("ALTER TABLE seen_ads ADD COLUMN pub_date TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_ads_id ON seen_ads(id)")
    conn.commit()
    conn.close()

def db_is_empty() -> bool:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.execute("SELECT COUNT(*) FROM seen_ads")
    count = cur.fetchone()[0]
    conn.close()
    return count == 0

def is_new_ad(ad_id: int) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.execute("SELECT 1 FROM seen_ads WHERE id = ?", (ad_id,))
    result = cur.fetchone() is None
    conn.close()
    return result

def save_ad(ad_id: int, category: str, title: str, url: str, pub_date: str = ""):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT OR IGNORE INTO seen_ads (id, category, title, url, pub_date) VALUES (?, ?, ?, ?, ?)",
        (ad_id, category, title, url, pub_date),
    )
    conn.commit()
    conn.close()

def get_db_stats() -> dict:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.execute("SELECT COUNT(*) FROM seen_ads")
    total = cur.fetchone()[0]
    cur = conn.execute("SELECT category, COUNT(*) FROM seen_ads GROUP BY category ORDER BY 2 DESC")
    by_cat = dict(cur.fetchall())
    conn.close()
    return {"total": total, "by_category": by_cat}

# =============================================================================
#  POMOCNE
# =============================================================================

def parse_date_croatian(date_str: str) -> str:
    if not date_str:
        return ""
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", date_str)
    if m:
        return f"{int(m.group(1)):02d}.{int(m.group(2)):02d}.{m.group(3)}"
    return ""

def is_too_old(pub_date: str) -> bool:
    if SKIP_BEFORE_DATE is None or not pub_date:
        return False
    try:
        d = datetime.strptime(pub_date, "%d.%m.%Y")
        cutoff = datetime.strptime(SKIP_BEFORE_DATE, "%d.%m.%Y")
        return d < cutoff
    except ValueError:
        return False

# =============================================================================
#  SCRAPING
# =============================================================================

def scrape_listings(page, url: str, pages: int) -> list[dict]:
    all_ads = []
    seen_ids = set()

    for p in range(1, pages + 1):
        page_url = url if p == 1 else f"{url}&page={p}"

        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        except Exception as e:
            print(f"    [!] Greska ucitavanja str.{p}: {e}")
            continue

        time.sleep(1.5)

        if "shield" in page.content()[:5000].lower():
            print(f"    [!] CAPTCHA na str.{p}, preskacem URL")
            break

        ads = page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('.EntityList-item--Regular article.entity-body').forEach(article => {
                    const link = article.querySelector('h3.entity-title a.link');
                    if (!link) return;
                    const titleEl = link.querySelector('span');
                    const title = titleEl ? titleEl.textContent.trim() : link.textContent.trim();
                    const href = link.getAttribute('href');
                    const nameId = link.getAttribute('name');
                    const priceEl = article.querySelector('.price--hrk, strong.price');
                    const price = priceEl ? priceEl.textContent.trim() : '';
                    const dateEl = article.querySelector('.date--full, .entity-pub-date time');
                    const pubDate = dateEl ? dateEl.textContent.trim() : '';

                    let adId = nameId ? parseInt(nameId) : null;
                    if (!adId && href) {
                        const m = href.match(/-oglas-(\\d+)/);
                        if (m) adId = parseInt(m[1]);
                    }
                    if (adId) results.push({ id: adId, title, price, url: href, date: pubDate });
                });
                return results;
            }
        """)

        for ad in ads:
            ad_id = ad["id"]
            if ad_id and ad_id not in seen_ids:
                seen_ids.add(ad_id)
                if ad["url"].startswith("/"):
                    ad["url"] = "https://www.njuskalo.hr" + ad["url"]
                all_ads.append(ad)

    return all_ads

# =============================================================================
#  TELEGRAM
# =============================================================================

def telegram_configured() -> bool:
    return (
        TELEGRAM_BOT_TOKEN not in ("YOUR_BOT_TOKEN_HERE", "")
        and TELEGRAM_CHAT_ID not in ("YOUR_CHAT_ID_HERE", "")
    )

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send_telegram(text: str):
    if not telegram_configured():
        print("  [!] Telegram nije konfiguriran")
        return

    import requests

    all_chats = [TELEGRAM_CHAT_ID] + TELEGRAM_EXTRA_CHATS

    for chat_id in all_chats:
        base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        chunks = _split_message(text, TELEGRAM_MAX_CHARS)

        for i, chunk in enumerate(chunks):
            try:
                resp = requests.post(
                    base_url,
                    json={
                        "chat_id": chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    print(f"    [!] Telegram error ({chat_id}): {resp.status_code} {resp.text[:200]}")
                else:
                    label = f" ({i+1}/{len(chunks)})" if len(chunks) > 1 else ""
                    print(f"    [✓] Telegram poslan za {chat_id}{label}")
            except Exception as e:
                print(f"    [!] Telegram greska ({chat_id}): {e}")

def _split_message(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    lines = text.split("\n")
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks

# =============================================================================
#  MAIN
# =============================================================================

def run():
    init_db()
    first_run = db_is_empty()

    print("=" * 60)
    print("  NJuskalo Monitor — Mrvica Bot")
    print(f"  {time.strftime('%d.%m.%Y. %H:%M:%S')}")
    if first_run:
        print("  [i] PRVO POKRETANJE - punim bazu bez slanja obavijesti")
    print("=" * 60)

    total_new = 0
    telegram_body = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-setuid-sandbox",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="hr-HR",
        )

        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        first_url = list(URLS.values())[0]
        try:
            page.goto(first_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
            try:
                btn = page.locator("#didomi-notice-agree-button")
                btn.wait_for(state="visible", timeout=4000)
                btn.click()
                time.sleep(0.5)
            except Exception:
                pass
        except Exception:
            pass

        categories = list(URLS.keys())
        for idx, (category, url) in enumerate(URLS.items()):
            print(f"\n[{category}]")
            print(f"  URL: {url}")

            ads = scrape_listings(page, url, PAGES_PER_URL)
            print(f"  [i] Ukupno na stranicama: {len(ads)} oglasa")

            new_ads = []
            skipped_old = 0
            for ad in ads:
                pub_date = parse_date_croatian(ad.get("date", ""))
                ad["date"] = pub_date

                if is_too_old(pub_date):
                    skipped_old += 1
                    continue

                if is_new_ad(ad["id"]):
                    new_ads.append(ad)
                    save_ad(ad["id"], category, ad["title"], ad["url"], pub_date)

            if skipped_old:
                print(f"  [i] Preskoceno {skipped_old} prestarih oglasa (prije {SKIP_BEFORE_DATE})")

            if new_ads:
                print(f"  [✓] {len(new_ads)} NOVIH!")
                total_new += len(new_ads)

                telegram_body += f"\n<b>━━━ {category} ━━━</b>\n"
                telegram_body += f"<i>{len(new_ads)} novih oglasa</i>\n\n"

                for ad in new_ads:
                    title_safe = escape_html(ad["title"])
                    price_safe = ad["price"].strip() if ad["price"] else "?"
                    url_safe = escape_html(ad["url"])
                    date_safe = ad.get("date", "")
                    telegram_body += f"<b>{title_safe}</b>\n"
                    telegram_body += f"💰 {price_safe}\n"
                    if date_safe:
                        telegram_body += f"📅 {date_safe}\n"
                    telegram_body += f"🔗 {url_safe}\n\n"
            else:
                print(f"  [~] Nema novih")

            if idx < len(categories) - 1:
                time.sleep(DELAY_BETWEEN_URLS)

        browser.close()

    if not first_run and total_new > 0 and telegram_configured():
        header = (
            f"🆕 <b>NJUSKALO — MRVICA</b>\n"
            f"📅 {time.strftime('%d.%m.%Y. %H:%M')}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        send_telegram(header + telegram_body)
    elif first_run and total_new > 0:
        print(f"\n[i] Inicijalno spremljeno {total_new} oglasa u bazu (bez obavijesti)")

    stats = get_db_stats()
    print(f"\n{'=' * 60}")
    print(f"  GOTOVO! Novih: {total_new} | Baza ukupno: {stats['total']}")
    for cat, cnt in sorted(stats.get("by_category", {}).items()):
        print(f"    {cat}: {cnt}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    run()
