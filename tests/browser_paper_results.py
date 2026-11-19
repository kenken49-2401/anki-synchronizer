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
        page = browser.new_page(viewport={"width": width, "height": 844}, has_touch=width == 390)
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
                    {{name:'1',max:20,score:0,minutes:18,difficulty:'C',expectedMinutes:25,tags:[]}},
                    {{name:'2',max:20,score:8,tags:[]}}
                  ]}},
                {{id:'mock',name:'テスト大学 2025年度',kind:'模試',date:'2026-11-02',subject:'数学',
                  score:20,max:20,scoreComplete:true,questions:[{{name:'1',max:20,score:20,minutes:99,tags:[]}}]}}
              ],
              pastPapers: [
                {{id:'p',exam:'テスト大学',subject:'数学',year:2025,statuses:{{}},tagsByQuestion:{{'1':['整数']}}}},
                {{id:'p2000',exam:'テスト大学',subject:'数学',year:2000,statuses:{{'1':'review'}}}},
                {{id:'p1999',exam:'テスト大学',subject:'数学',year:1999,statuses:{{'1':'done'}},tagsByQuestion:{{'1':['整数']}}}},
                {{id:'science',exam:'テスト大学',subject:'理科',year:1999,statuses:{{}},
                  tagsByQuestion:{{'物理1':['単振動'],'物理2':['回路'],'化学1':['溶液']}}}}
              ]
            }}));
            localStorage.setItem('atlas.theme.v1', '{theme}');
          }}
        """)
        page.goto("http://atlas.test/study-atlas.html#paper")
        assert not page_errors, page_errors
        page.set_default_timeout(3500)
        dialog = page.locator("#paperResultDialog")
        cell = page.locator("#paperTable tbody .paper-cell").first
        edit = cell.locator(".paper-result-edit")
        assert not dialog.is_visible()
        result = cell.locator(".difficulty-badge + .paper-result-value")
        assert result.inner_text() == "0点(18m)"
        assert result.evaluate("e => getComputedStyle(e).color") == "rgb(0, 0, 0)"
        assert "過去問結果" not in cell.inner_text()
        if width == 390:
            assert cell.bounding_box()["width"] < 100
        else:
            viewport = page.locator("#paperTableViewport")
            assert abs(page.locator("#paperTable").bounding_box()["width"] - viewport.evaluate("e => e.clientWidth")) <= 2
            assert cell.bounding_box()["width"] > 100
        picker = page.locator("#paperFilterTags")
        picker.locator("summary").click()
        picker.get_by_label("整数", exact=True).check()
        matches = page.locator("#paperMatchesTable tbody tr")
        assert matches.count() == 2
        assert matches.nth(0).locator("td").all_text_contents() == ["2025", "1", "C", "**°", "0点", "18m"]
        assert matches.nth(1).locator("td").all_text_contents() == ["1999", "1", "—", "—", "—", "—"]
        assert "paper-solved" in matches.nth(1).get_attribute("class")
        color_of = "e => getComputedStyle(e).backgroundColor"
        assert matches.nth(0).evaluate(color_of) == cell.evaluate(color_of)
        unmatched = page.locator("#paperTable tbody .paper-cell").nth(1)
        assert "paper-filtered" in unmatched.get_attribute("class")
        assert "paper-filtered" not in cell.get_attribute("class")
        color = unmatched.evaluate("node => getComputedStyle(node).backgroundColor")
        assert color == ("rgb(18, 23, 25)" if theme == "dark" else "rgb(248, 250, 248)")
        page.locator("#paperFilterClear").click()
        assert "paper-filtered" not in unmatched.get_attribute("class")
        assert not page.locator("#paperMatches").is_visible()
        edit.click()
        assert dialog.is_visible()
        assert cell.get_attribute("data-state") == "review"
        dialog.get_by_label("整数", exact=True).uncheck()
        dialog.get_by_role("button", name="キャンセル").click()
        assert cell.get_by_text("整数", exact=True).is_visible()
        assert cell.get_attribute("data-state") == "review"
        edit.click()
        dialog.get_by_label("所要時間").fill("35")
        dialog.get_by_label("点数").fill("0")
        dialog.get_by_label("整数", exact=True).uncheck()
        dialog.get_by_label("微積分", exact=True).check()
        dialog.get_by_role("button", name="保存", exact=True).click()
        assert not dialog.is_visible()
        assert cell.get_attribute("data-state") == "review"
        assert cell.locator(".paper-result-value").inner_text() == "0点(35m)"
        page.reload()
        assert not dialog.is_visible()
        edit.click()
        assert dialog.get_by_label("点数").input_value() == "0"
        assert dialog.get_by_label("微積分", exact=True).is_checked()
        assert not dialog.get_by_label("整数", exact=True).is_checked()
        assert cell.get_by_role("button").count() == 1
        dialog.get_by_label("点数").fill("15")
        dialog.get_by_role("button", name="保存", exact=True).click()
        assert "15点" in cell.inner_text()
        assert cell.get_attribute("data-state") == "done"
        assert cell.locator("select").count() == 0
        assert edit.bounding_box()["height"] <= 26
        third = page.locator("#paperTable tbody .paper-cell").nth(2)
        third.locator(".paper-result-edit").click()
        dialog.get_by_label("所要時間").fill("24")
        dialog.get_by_role("button", name="保存", exact=True).click()
        assert third.get_attribute("data-state") == "new"
        assert third.locator(".paper-result-value").inner_text() == "(24m)"
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        assert page.locator("#paperTable th[scope=row]").all_text_contents() == ["2025", "2000", "1999"]
        assert "2000年度以降 · 全12問 · 解いた 1問 · 要復習 2問" in page.locator("#paperSummary").inner_text()
        assert "3/12問" in page.locator("#paperStats").inner_text()
        page.locator("#paperSubject").select_option("理科")
        group = page.locator("#paperFilterGroup")
        group.select_option("物理:力学")
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered) .paper-result-edit").first.get_attribute("aria-label").startswith("1999年度 物理1")
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered)").count() == 1
        picker.locator("summary").click()
        picker.get_by_label("回路", exact=True).check()
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered)").count() == 0
        page.locator("#paperFilterClear").click()
        group.select_option("化学:理論")
        assert page.locator("#paperTable .paper-cell:not(.paper-filtered) .paper-result-edit").first.get_attribute("aria-label").startswith("1999年度 化学1")
        page.locator("#paperSubject").select_option("数学")
        assert group.is_visible()
        assert group.input_value() == ""
        for group_name in ("数学Ⅱ", "数学Ⅲ"):
            group.select_option("数学:" + group_name)
            assert page.locator("#paperMatchesTable tbody tr").count() == 1
            assert cell.get_by_text("微積分", exact=True).is_visible()
        page.locator("#paperFilterClear").click()
        assert page.locator("#paperTable .paper-result-edit").all_text_contents() == ["✎"] * 18
        viewport = page.locator("#paperTableViewport")
        table = page.locator("#paperTable")
        original_width = table.bounding_box()["width"]
        page.get_by_role("button", name="表を拡大", exact=True).click()
        assert page.locator("#paperZoomReset").inner_text() == "125%"
        assert table.bounding_box()["width"] > original_width * 1.2
        page.get_by_role("button", name="表を縮小", exact=True).click()
        assert page.locator("#paperZoomReset").inner_text() == "100%"
        if width == 390:
            viewport.scroll_into_view_if_needed()
            box = viewport.bounding_box()
            cx, cy = int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2)
            cdp = page.context.new_cdp_session(page)
            for event, radius in [("touchStart", 25), ("touchMove", 38), ("touchEnd", 0)]:
                touches = [{"x": cx + dx, "y": cy, "id": i} for i, dx in enumerate([-radius, radius])] if radius else []
                cdp.send("Input.dispatchTouchEvent", {"type": event, "touchPoints": touches})
            assert page.locator("#paperZoomReset").inner_text() == "152%"
            assert page.evaluate("visualViewport.scale") == 1
            assert viewport.evaluate("element => element.scrollLeft") > 0
            viewport.evaluate("element => { element.scrollLeft = 0; }")
            cell.locator(".paper-result-edit").tap()
            assert dialog.is_visible()
            assert dialog.get_by_label("微積分", exact=True).is_checked()
            dialog.get_by_label("整数", exact=True).check()
            dialog.get_by_role("button", name="保存", exact=True).tap()
            assert cell.get_by_text("整数", exact=True).is_visible()
            page.locator("#paperZoomReset").click()
            assert page.locator("#paperZoomReset").inner_text() == "100%"
        assert not page_errors, page_errors
        page.close()
