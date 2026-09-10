from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


class PublishError(RuntimeError):
    pass


class DouDianSimilarPublisher:
    """DouDian similar-product RPA.

    It deliberately changes only three fields inherited from the source product:
    title, first main image and SKU/spec name. CAPTCHA/login verification is never bypassed.
    """

    def __init__(self, page: Page, selector_file: Path, screenshot_dir: Path, step_cb: Callable[[str, int], None] | None = None):
        self.page = page
        self.selector_file = selector_file
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.selectors = json.loads(selector_file.read_text(encoding="utf-8"))
        self.step_cb = step_cb or (lambda _s, _p: None)

    def step(self, text: str, progress: int):
        self.step_cb(text, progress)

    def _cfg(self, key: str) -> dict:
        return self.selectors.get(key, {})

    def _candidate_locator(self, candidate: dict):
        kind = candidate.get("kind", "text")
        value = candidate.get("value", "")
        exact = bool(candidate.get("exact", False))
        if kind == "text":
            return self.page.get_by_text(value, exact=exact)
        if kind == "placeholder":
            return self.page.get_by_placeholder(value, exact=exact)
        if kind == "label":
            return self.page.get_by_label(value, exact=exact)
        if kind == "role":
            return self.page.get_by_role(candidate.get("role", "button"), name=value, exact=exact)
        if kind == "css":
            return self.page.locator(value)
        raise PublishError(f"不支持的 selector 类型: {kind}")

    def locator(self, key: str, timeout=1200):
        cfg = self._cfg(key)
        candidates = list(cfg.get("candidates") or [])
        for k in ("css", "placeholder", "text"):
            if cfg.get(k):
                candidates.append({"kind": k, "value": cfg[k]})
        for cand in candidates:
            try:
                loc = self._candidate_locator(cand).first
                loc.wait_for(state="visible", timeout=timeout)
                return loc
            except Exception:
                continue
        raise PublishError(f"未找到页面元素：{key}。请在 config/selectors.json 校准该节点。")

    def click(self, key: str, timeout=8000):
        loc = self.locator(key, timeout=min(timeout, 1800))
        loc.click(timeout=timeout)
        return loc

    def fill(self, key: str, value: str, timeout=8000):
        loc = self.locator(key, timeout=min(timeout, 1800))
        loc.fill(value, timeout=timeout)
        return loc

    def wait_page_ready(self, ms=700):
        self.page.wait_for_timeout(ms)

    def screenshot_error(self, task_code: str):
        safe = "".join(ch for ch in task_code if ch.isalnum() or ch in "_-" ) or "task"
        path = self.screenshot_dir / f"{safe}_error.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    # ---------- Recorded workflow ----------
    def open_product_list(self):
        self.step("进入商品管理", 8)
        self.wait_page_ready(500)

        # V2.0.1:
        # Keep the user's current merchant page instead of forcing a jump to the public root.
        # If the user has already opened 商品管理/商品列表, start directly from the search box.
        try:
            self.locator("source_search_input", timeout=2800)
            self.step("已在商品列表", 12)
            return
        except PublishError:
            pass

        # If not already on the list page, try the current merchant-side navigation.
        try:
            self.click("nav_product", timeout=10000)
            self.wait_page_ready(500)
        except PublishError as exc:
            raise PublishError(
                "当前页面未检测到商品列表搜索框，也未找到商品导航。"
                "请先在软件打开的抖店浏览器中人工进入 商品→商品管理/商品列表，保持该页面后重试。"
            ) from exc

        # Some accounts land directly on the list after clicking 商品.
        try:
            self.locator("source_search_input", timeout=2200)
            return
        except PublishError:
            pass

        # Other accounts require a second-level 商品管理/商品列表 click.
        try:
            self.click("product_list", timeout=8000)
        except PublishError:
            pass
        self.wait_page_ready(800)

        try:
            self.locator("source_search_input", timeout=3500)
        except PublishError as exc:
            raise PublishError(
                "已进入商品相关页面，但仍未检测到商品列表搜索框 source_search_input。"
                "请保持商品列表页并提供失败截图，以便校准搜索框。"
            ) from exc

    def search_source_product(self, keyword: str):
        self.step("搜索源商品", 18)
        box = self.locator("source_search_input", timeout=2200)
        box.fill("")
        box.fill(keyword)
        try:
            self.click("source_search_button", timeout=5000)
        except PublishError:
            box.press("Enter")
        self.wait_page_ready(1100)

        row = self.page.locator("tr").filter(has_text=keyword).first
        try:
            row.wait_for(state="visible", timeout=3500)
            return row
        except Exception:
            return None

    def open_similar_product(self, keyword: str):
        self.step("打开发布相似品", 28)
        row = self.search_source_product(keyword)

        if row is not None:
            for txt in self._cfg("similar_publish_row_texts").get("values", ["发布相似品", "相似品"]):
                try:
                    btn = row.get_by_text(txt, exact=False).first
                    btn.wait_for(state="visible", timeout=1000)
                    btn.click()
                    self.wait_page_ready(600)
                    return
                except Exception:
                    pass
            for txt in self._cfg("row_more_texts").get("values", ["更多", "操作"]):
                try:
                    btn = row.get_by_text(txt, exact=False).first
                    btn.wait_for(state="visible", timeout=1000)
                    btn.click()
                    self.wait_page_ready(300)
                    self.click("similar_publish_entry", timeout=5000)
                    self.wait_page_ready(700)
                    return
                except Exception:
                    pass

        try:
            self.click("similar_publish_entry", timeout=5000)
        except PublishError:
            self.click("row_more_button", timeout=5000)
            self.click("similar_publish_entry", timeout=5000)
        self.wait_page_ready(800)

    def wait_edit_page(self):
        self.step("等待相似品编辑页", 36)
        self.locator("title_input", timeout=12000)
        self.wait_page_ready(500)

    def replace_title(self, new_title: str):
        self.step("修改商品标题", 46)
        self.fill("title_input", new_title, timeout=10000)

    def replace_first_main_image(self, image_path: str):
        self.step("替换第一张主图", 60)
        image = Path(image_path)
        if not image.exists() or not image.is_file():
            raise PublishError(f"新首图不存在：{image}")
        if image.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise PublishError(f"不支持的首图格式：{image.suffix}")

        cfg = self._cfg("first_main_image_input")
        css = cfg.get("css")
        if css:
            inputs = self.page.locator(css)
            try:
                if inputs.count() > 0:
                    inputs.nth(int(cfg.get("index", 0))).set_input_files(str(image))
                    self.wait_page_ready(900)
                    return
            except Exception:
                pass

        try:
            with self.page.expect_file_chooser(timeout=7000) as chooser_info:
                self.click("first_main_image_replace", timeout=6500)
            chooser_info.value.set_files(str(image))
            self.wait_page_ready(900)
            return
        except Exception as exc:
            raise PublishError("首图替换控件未定位成功，请校准 first_main_image_input / first_main_image_replace") from exc

    def replace_sku_name(self, sku_name: str):
        self.step("修改 SKU 名称", 74)
        loc = self.locator("sku_name_input", timeout=4500)
        loc.fill("")
        loc.fill(sku_name)
        self.wait_page_ready(350)

    def preflight_guard(self, expected_title: str, expected_sku: str):
        self.step("发布前校验", 84)
        title = self.locator("title_input", timeout=2500).input_value().strip()
        if title != expected_title.strip():
            raise PublishError("发布前校验失败：商品标题与任务数据不一致")
        sku = self.locator("sku_name_input", timeout=2500).input_value().strip()
        if sku != expected_sku.strip():
            raise PublishError("发布前校验失败：SKU 名称与任务数据不一致")

    def submit(self, safe_mode: bool):
        if safe_mode:
            self.step("已到发布前安全停点", 92)
            return "待确认", "已完成标题、首图、SKU 修改，已停在最终发布前。"

        self.step("提交发布", 92)
        self.click("publish_button", timeout=12000)
        self.wait_page_ready(800)
        success_texts = self._cfg("publish_success_texts").get("values", ["商品提交成功", "提交成功", "发布成功"])
        for text in success_texts:
            try:
                self.page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=15000)
                self.step("发布成功", 100)
                return "成功", text
            except Exception:
                continue
        raise PublishError("已点击发布，但未检测到“商品提交成功”等成功反馈，请人工检查页面。")

    def run(self, task: dict, template: dict, safe_mode=True):
        code = str(task.get("task_code", "task"))
        try:
            self.open_product_list()
            self.open_similar_product(str(template["source_keyword"]))
            self.wait_edit_page()
            self.replace_title(str(task["new_title"]))
            self.replace_first_main_image(str(task["cover_image"]))
            self.replace_sku_name(str(task["sku_name"]))
            self.preflight_guard(str(task["new_title"]), str(task["sku_name"]))
            return self.submit(safe_mode)
        except PlaywrightTimeoutError as exc:
            shot = self.screenshot_error(code)
            raise PublishError(f"页面等待超时，已截图：{shot}") from exc
        except Exception:
            try:
                self.screenshot_error(code)
            except Exception:
                pass
            raise


DouDianPublisher = DouDianSimilarPublisher
