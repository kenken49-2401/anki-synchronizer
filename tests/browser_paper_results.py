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
              studies: [], tasks: [], scienceTagVersion: 2,
              scores: [
                {{id:'past',name:'テスト大学 2025年度',kind:'過去問',date:'2026-11-01',subject:'数学',
                  score:8,max:40,scoreComplete:true,questions:[
                    {{name:'1',max:20,score:0,minutes:18,tags:[]}},
                    {{name:'2',max:20,score:8,tags:[]}}
                  ]}},
                {{id:'mock',name:'テスト大学 2025年度',kind:'模試',date:'2026-11-02',subject:'数学',
                  score:20,max:20,scoreComplete:true,questions:[{{name:'1',max:20,score:20,minutes:99,tags:[]}}]}}
              ],
              pastPapers: [
                {{id:'p',exam:'テスト大学',subject:'数学',year:2025,statuses:{{}},tagsByQuestion:{{'1':['整数']}}}},
                {{id:'p2000',exam:'テスト大学',subject:'数学',year:2000,statuses:{{'1':'review'}}}},
                {{id:'p1999',exam:'テスト大学',subject:'数学',year:1999,statuses:{{'1':'done'}}}},
                {{id:'science',exam:'テスト大学',subject:'理科',year:1999,statuses:{{}},
                  tagsByQuestion:{{'物理1':['単振動'],'物理2':['回路'],'化学1':['溶液']}}}}
              ]
            }}));
            localStorage.setItem('atlas.theme.v1', '{theme}');
          }}
        """)
        page.goto("http://atlas.test/study-atlas.html#paper")
        dialog = page.locator("#paperResultDialog")
        cell = page.locator("#paperTable tbody .paper-cell").first
        state = cell.locator("select").first
        assert not dialog.is_visible()
        assert cell.locator(".paper-linked-result").inner_text() == "過去問結果 18分 / 0点"
        picker = page.locator("#paperFilterTags")
        picker.locator("summary").click()
        picker.get_by_label("整数", exact=True).check()
        unmatched = page.locator("#paperTable tbody .paper-cell").nth(1)
        assert "paper-filtered" in unmatched.get_attribute("class")
        assert "paper-filtered" not in cell.get_attribute("class")
        color = unmatched.evaluate("node => getComputedStyle(node).backgroundColor")
        assert color == ("rgb(18, 23, 25)" if theme == "dark" else "rgb(248, 250, 248)")
        page.locator("#paperFilterClear").click()
        assert "paper-filtered" not in unmatched.get_attribute("class")
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
        assert page.locator("#paperTable th[scope=row]").all_text_contents() == ["2025", "2000", "1999"]
        assert "2000年度以降 · 全12問 · 解いた 2問 · 要復習 1問" in page.locator("#paperSummary").inner_text()
        assert "3/12問" in page.locator("#paperStats").inner_text()
        page.locator("#paperSubject").select_option("理科")
        group = page.locator("#paperFilterGroup")
        group.select_option("物理:力学")
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered) select").first.get_attribute("aria-label") == "1999年度 物理1 の状態"
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered)").count() == 1
        picker.locator("summary").click()
        picker.get_by_label("回路", exact=True).check()
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered)").count() == 0
        page.locator("#paperFilterClear").click()
        group.select_option("化学:理論")
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered) select").first.get_attribute("aria-label") == "1999年度 化学1 の状態"
        page.locator("#paperSubject").select_option("数学")
        assert not group.is_visible()
        assert group.input_value() == ""
        assert not page_errors, page_errors
        page.close()
