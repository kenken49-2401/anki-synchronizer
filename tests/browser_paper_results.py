"""Past-paper result entry regression. Run with Python and Playwright."""
from pathlib import Path
import shutil

from playwright.sync_api import sync_playwright

HTML = Path(__file__).resolve().parents[1] / "web" / "study-atlas.html"
KEY = "study-atlas-prototype-v1"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path=shutil.which("chromium"), args=["--no-sandbox"]
    )
    for theme, width in [("light", 1440), ("dark", 390)]:
        page = browser.new_page(viewport={"width": width, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        # Serve local assets without a live GitHub account or a network listener.
        def serve(route):
            name = route.request.url.rsplit("/", 1)[-1].split("?")[0]
            asset = HTML.parent / name
            if asset.is_file():
                route.fulfill(path=asset)
            else:
                route.abort()

        page.route("http://atlas.test/**", serve)
        page.add_init_script(f"""
          if (!localStorage.getItem('{KEY}')) {{
            localStorage.setItem('{KEY}', JSON.stringify({{
              studies: [], scores: [], tasks: [], scienceTagVersion: 2,
              pastPapers: [{{id:'p',exam:'テスト大学',subject:'数学',year:2025,statuses:{{}}}}]
            }}));
            localStorage.setItem('atlas.theme.v1', '{theme}');
          }}
        """)
        page.goto("http://atlas.test/study-atlas.html#paper")
        dialog = page.locator("#paperResultDialog")
        cell = page.locator("#paperTable tbody .paper-cell").first
        state = cell.locator("select").first
        assert not dialog.is_visible()
        state.select_option("done")
        assert dialog.is_visible()
        assert state.input_value() == "new"
        dialog.get_by_role("button", name="キャンセル").click()
        assert state.input_value() == "new"
        state.select_option("done")
        dialog.get_by_label("所要時間").fill("35")
        dialog.get_by_label("点数").fill("0")
        dialog.get_by_role("button", name="保存", exact=True).click()
        assert not dialog.is_visible()
        assert state.input_value() == "done"
        assert "実測 35分 / 0点" in cell.inner_text()
        page.reload()
        assert not dialog.is_visible()
        cell.get_by_role("button", name="実測 35分 / 0点").click()
        assert dialog.get_by_label("点数").input_value() == "0"
        dialog.get_by_label("点数").fill("12.5")
        dialog.get_by_role("button", name="保存", exact=True).click()
        assert "12.5点" in cell.inner_text()
        second = page.locator("#paperTable tbody .paper-cell").nth(1)
        second.locator("select").first.select_option("done")
        dialog.get_by_role("button", name="保存", exact=True).click()
        assert second.locator("select").first.input_value() == "done"
        assert second.get_by_text("時間・点数を入力").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert not page_errors, page_errors
        page.close()
