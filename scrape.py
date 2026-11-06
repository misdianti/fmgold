#!/usr/bin/env python3
"""Ambil harga emas 1-50 gram dari dua sumber dan simpan dengan riwayat harian:
  1. Antam, harga dasar     : logammulia.com/harga-emas  -> data/prices.json
  2. Galeri 24, harga jual  : galeri24.co.id/harga-emas  -> data/galeri24.json

Pakai:  python3 scrape.py                       (buka browser, ambil kedua halaman)
        python3 scrape.py antam.html [g24.txt]  (uji dengan file yang sudah disimpan)
Env:    HEADLESS=1 tanpa jendela, BROWSER_CHANNEL=chrome untuk memakai Google Chrome terpasang
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ANTAM_URL = "https://logammulia.com/harga-emas"
G24_URL = "https://galeri24.co.id/harga-emas"
DATA = Path(__file__).parent / "data"
WEIGHTS = [1, 2, 3, 5, 10, 25, 50]
G24_REQUIRED = [1, 2, 5, 10, 25, 50]  # Galeri 24 tidak menjual batangan 3 gram
WIB = dt.timezone(dt.timedelta(hours=7))
MAX_HISTORY = 400
MAX_DAILY_JUMP = 0.15
ROW_SELECTOR = "div.border-bottom-grey-2"
HEADER_SELECTOR = "div.header-bg"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
     "september", "oktober", "november", "desember"])}


class ScrapeError(Exception):
    pass


def to_int(text):
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def check_prices(prices, required):
    base = prices["1"]
    for w in required:
        ratio = prices[str(w)] / w / base
        if not 0.9 <= ratio <= 1.05:
            raise ScrapeError(f"Harga {w} gram tidak masuk akal ({prices[str(w)]})")


# ---------- Antam (logammulia.com) ----------
ROW_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:gr|gram)\b\s*Rp\s*([\d.,]+)", re.I)


def parse_antam(html):
    soup = BeautifulSoup(html, "html.parser")
    groups, current = [], {}
    for el in soup.select(f"{HEADER_SELECTOR}, {ROW_SELECTOR}"):
        if "header-bg" in (el.get("class") or []):
            if current:
                groups.append(current)
            current = {}
            continue
        m = ROW_RE.match(el.get_text(" ", strip=True))
        if not m:
            continue
        weight = m.group(1).replace(",", ".")
        if not re.fullmatch(r"\d+", weight):
            continue
        w, price = int(weight), to_int(m.group(2))
        if w in WEIGHTS and price and price > 100_000 and w not in current:
            current[w] = price
    if current:
        groups.append(current)
    for g in groups:
        if all(w in g for w in WEIGHTS):
            prices = {str(w): g[w] for w in WEIGHTS}
            check_prices(prices, WEIGHTS)
            return prices, None
    raise ScrapeError("Tabel harga dasar Antam 1-50 gram tidak ditemukan")


# ---------- Galeri 24 (galeri24.co.id), tabel "Harga GALERI 24" ----------
G24_HEADING = re.compile(r"Harga GALERI 24\b")
G24_ROW = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s+Rp\s*([\d.]+)\s+Rp\s*([\d.]+)")
G24_DATE = re.compile(r"Diperbarui\s+\w+,\s*(\d{1,2})\s+(\w+)\s+(\d{4})")


def parse_galeri24(text):
    m = G24_HEADING.search(text)
    if not m:
        raise ScrapeError("Bagian 'Harga GALERI 24' tidak ditemukan")
    end = text.find("Diperbarui", m.end())
    segment = text[m.end(): end if end != -1 else len(text)]
    prices = {}
    for weight, jual, _buyback in G24_ROW.findall(segment):  # buyback diabaikan
        if not re.fullmatch(r"\d+", weight):
            continue
        w, price = int(weight), to_int(jual)
        if w in WEIGHTS and price and price > 100_000 and w not in prices:
            prices[w] = price
    if not all(w in prices for w in G24_REQUIRED):
        raise ScrapeError("Harga jual Galeri 24 tidak lengkap untuk 1, 2, 5, 10, 25, 50 gram")
    out = {str(w): prices[w] for w in WEIGHTS if w in prices}
    check_prices(out, [w for w in WEIGHTS if w in prices])
    source_date = None
    dates = G24_DATE.findall(text[: m.start()])
    if dates:
        d, mon, y = dates[-1]
        if mon.lower() in MONTHS:
            source_date = dt.date(int(y), MONTHS[mon.lower()], int(d)).isoformat()
    return out, source_date


# ---------- Ambil halaman ----------
def fetch_all():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright belum terpasang: pip3 install playwright && python3 -m playwright install chromium")
    pages, errors = {}, {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel=os.environ.get("BROWSER_CHANNEL") or None,
            headless=os.environ.get("HEADLESS") == "1",
        )
        page = browser.new_page(locale="id-ID")
        try:
            page.goto(ANTAM_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(ROW_SELECTOR, timeout=45000)
            page.wait_for_timeout(1500)
            pages["antam"] = page.content()
        except Exception:
            errors["antam"] = f"Halaman Antam tidak termuat. TITLE={page.title()!r}"
        try:
            page.goto(G24_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_function(
                "document.body && document.body.innerText.includes('Harga GALERI 24')", timeout=45000)
            page.wait_for_timeout(1000)
            pages["galeri24"] = page.inner_text("body")
        except Exception:
            errors["galeri24"] = f"Halaman Galeri 24 tidak termuat. TITLE={page.title()!r}"
        browser.close()
    return pages, errors


# ---------- Simpan ----------
def save(path, source_url, prices, source_date=None):
    today = dt.datetime.now(WIB).date().isoformat()
    data = json.loads(path.read_text()) if path.exists() else {"history": []}
    history = [h for h in data.get("history", []) if h["date"] != today]
    if history:
        prev = history[-1]["prices"]["1"]
        if abs(prices["1"] - prev) / prev > MAX_DAILY_JUMP:
            raise ScrapeError(f"Lompatan harga mencurigakan ({prev} -> {prices['1']})")
    entry = {"date": today, "prices": prices}
    if source_date:
        entry["source_date"] = source_date
    history.append(entry)
    out = {"source": source_url,
           "updated": dt.datetime.now(WIB).isoformat(timespec="minutes"),
           "history": history[-MAX_HISTORY:]}
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    if len(sys.argv) > 1:
        pages, errors = {}, {}
        pages["antam"] = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
        if len(sys.argv) > 2:
            pages["galeri24"] = Path(sys.argv[2]).read_text(encoding="utf-8", errors="ignore")
    else:
        pages, errors = fetch_all()
    jobs = [("antam", parse_antam, DATA / "prices.json", ANTAM_URL),
            ("galeri24", parse_galeri24, DATA / "galeri24.json", G24_URL)]
    saved = 0
    for name, parser, path, url in jobs:
        if name not in pages:
            if name in errors:
                print(f"::warning::{name}: {errors[name]}")
            continue
        try:
            prices, source_date = parser(pages[name])
            save(path, url, prices, source_date)
            print("OK", name, prices, source_date or "")
            saved += 1
        except ScrapeError as e:
            print(f"::warning::{name}: {e}")
    if saved == 0:
        raise SystemExit("Tidak ada sumber yang berhasil diambil")


if __name__ == "__main__":
    main()
