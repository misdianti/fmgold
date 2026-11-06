#!/usr/bin/env python3
"""Ambil harga dasar emas batangan 1-50 gram dari logammulia.com/harga-emas
dan simpan ke data/prices.json (dengan riwayat harian).

Pakai:  python3 scrape.py            (buka browser, ambil halaman)
        python3 scrape.py file.html  (uji dengan HTML yang sudah disimpan)
Env:    HEADLESS=1 untuk menjalankan browser tanpa jendela (di Mac sebaiknya tidak diset)
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

URL = "https://logammulia.com/harga-emas"
WEIGHTS = [1, 2, 3, 5, 10, 25, 50]  # gramasi batangan dalam rentang 1-50 gram
OUT = Path(__file__).parent / "data" / "prices.json"
WIB = dt.timezone(dt.timedelta(hours=7))
MAX_HISTORY = 400
MAX_DAILY_JUMP = 0.15  # tolak data jika harga 1 gram lompat >15% (indikasi salah baca)
ROW_SELECTOR = "div.border-bottom-grey-2"
HEADER_SELECTOR = "div.header-bg"


def fetch_html() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright belum terpasang: pip3 install playwright && python3 -m playwright install chromium")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.environ.get("HEADLESS") == "1")
        page = browser.new_page(locale="id-ID")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(ROW_SELECTOR, timeout=45000)
        except Exception:
            title = page.title()
            body = page.inner_text("body")[:300].replace("\n", " ")
            browser.close()
            raise SystemExit(f"Baris harga tidak muncul dalam 45 detik. TITLE={title!r} BODY={body!r}")
        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()
    return html


def to_int(text: str):
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


ROW_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:gr|gram)\b\s*Rp\s*([\d.,]+)", re.I)


def parse(html: str) -> dict:
    """Baca baris 'Berat | Harga Dasar | Harga + Pajak', kelompokkan per tabel
    (dipisah baris header), lalu ambil kelompok pertama yang memuat semua gramasi."""
    soup = BeautifulSoup(html, "html.parser")
    groups, current = [], {}
    for el in soup.select(f"{HEADER_SELECTOR}, {ROW_SELECTOR}"):
        if "header-bg" in (el.get("class") or []):
            if current:
                groups.append(current)
            current = {}
            continue
        text = el.get_text(" ", strip=True)
        m = ROW_RE.match(text)
        if not m:
            continue
        weight = m.group(1).replace(",", ".")
        if not re.fullmatch(r"\d+", weight):
            continue  # lewati 0.5 gr dan sejenisnya
        w = int(weight)
        price = to_int(m.group(2))  # kolom pertama setelah berat = Harga Dasar
        if w in WEIGHTS and price and price > 100_000 and w not in current:
            current[w] = price
    if current:
        groups.append(current)
    for g in groups:
        if all(w in g for w in WEIGHTS):
            return {str(w): g[w] for w in WEIGHTS}
    raise SystemExit("Tabel harga dasar 1-50 gram tidak ditemukan; struktur halaman mungkin berubah")


def main():
    html = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore") if len(sys.argv) > 1 else fetch_html()
    prices = parse(html)
    # sanity: harga per gram tiap batang harus berdekatan dengan harga 1 gram
    for w in WEIGHTS:
        ratio = prices[str(w)] / w / prices["1"]
        if not 0.9 <= ratio <= 1.05:
            raise SystemExit(f"Harga {w} gram tidak masuk akal ({prices[str(w)]}), data tidak disimpan")
    today = dt.datetime.now(WIB).date().isoformat()
    data = json.loads(OUT.read_text()) if OUT.exists() else {"history": []}
    history = [h for h in data.get("history", []) if h["date"] != today]
    if history:
        prev = history[-1]["prices"]["1"]
        if abs(prices["1"] - prev) / prev > MAX_DAILY_JUMP:
            raise SystemExit(f"Lompatan harga mencurigakan ({prev} -> {prices['1']}), data tidak disimpan")
    history.append({"date": today, "prices": prices})
    out = {
        "source": URL,
        "updated": dt.datetime.now(WIB).isoformat(timespec="minutes"),
        "history": history[-MAX_HISTORY:],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("OK", today, prices)


if __name__ == "__main__":
    main()
