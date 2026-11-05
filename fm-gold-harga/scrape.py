#!/usr/bin/env python3
"""Ambil harga dasar emas batangan 1-50 gram dari logammulia.com/harga-emas
dan simpan ke data/prices.json (dengan riwayat harian)."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://logammulia.com/harga-emas"
WEIGHTS = [1, 2, 3, 5, 10, 25, 50]  # gramasi batangan yang dijual dalam rentang 1-50 gram
OUT = Path(__file__).parent / "data" / "prices.json"
WIB = dt.timezone(dt.timedelta(hours=7))
MAX_HISTORY = 400
MAX_DAILY_JUMP = 0.15  # tolak data jika harga 1 gram lompat >15% (indikasi salah parse)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}


def fetch_html() -> str:
    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
        if r.ok and "<table" in r.text:
            return r.text
        print(f"requests gagal, status {r.status_code}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"requests error: {e}", file=sys.stderr)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Diblokir dan playwright tidak terpasang")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="id-ID", user_agent=HEADERS["User-Agent"])
        page.goto(URL, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()
    return html


def to_int(text: str):
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        base_col, prices = 1, {}
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            m = re.match(r"^(\d{1,2})\s*(gr|gram)\b", cells[0], re.I)
            if not m:
                for i, c in enumerate(cells):  # baris header: cari kolom "Harga Dasar"
                    if "dasar" in c.lower():
                        base_col = i
                        break
                continue
            w = int(m.group(1))
            if w in WEIGHTS and w not in prices and len(cells) > base_col:
                p = to_int(cells[base_col])
                if p and p > 100_000:
                    prices[w] = p
        if all(w in prices for w in WEIGHTS):  # tabel pertama yang lengkap = Emas Batangan
            return {str(w): prices[w] for w in WEIGHTS}
    raise SystemExit("Tabel harga dasar 1-50 gram tidak ditemukan; struktur halaman mungkin berubah")


def main():
    html = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else fetch_html()
    prices = parse(html)
    today = dt.datetime.now(WIB).date().isoformat()
    data = json.loads(OUT.read_text()) if OUT.exists() else {"history": []}
    history = [h for h in data.get("history", []) if h["date"] != today]
    if history:
        prev = history[-1]["prices"]["1"]
        if abs(prices["1"] - prev) / prev > MAX_DAILY_JUMP:
            raise SystemExit(f"Lompatan harga mencurigakan ({prev} -> {prices['1']}), data tidak disimpan")
    history.append({"date": today, "prices": prices})
    history = history[-MAX_HISTORY:]
    out = {
        "source": URL,
        "updated": dt.datetime.now(WIB).isoformat(timespec="minutes"),
        "history": history,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("OK", today, prices)


if __name__ == "__main__":
    main()
