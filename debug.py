from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    pg = b.new_page(locale="id-ID")
    pg.goto("https://logammulia.com/harga-emas", timeout=60000)
    try:
        pg.wait_for_selector("table", timeout=40000)
    except Exception as e:
        print("Tabel tidak muncul:", e)
    print("TITLE:", pg.title())
    open("rendered.html", "w").write(pg.content())
    print("JUMLAH TABEL:", pg.locator("table").count())
    b.close()