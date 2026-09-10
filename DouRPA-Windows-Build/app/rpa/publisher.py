from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


class PublishError(RuntimeError):
    pass


class DouDianSimilarPublisher:
    """抖店发布相似品 RPA - V2.0.5"""

    def __init__(self, page: Page, selector_file: Path, screenshot_dir: Path,
                 step_cb: Callable[[str, int], None] | None = None):
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

    def _sync_active_page(self):
        try:
            pages = [p for p in self.page.context.pages if not p.is_closed()]
        except Exception:
            pages = []
        if not pages:
            raise PublishError("浏览器中没有可用页面。")

        preferred = [
            p for p in pages
            if ("jinritemai.com" in (p.url or "") or "douyin.com" in (p.url or ""))
        ]
        self.page = preferred[-1] if preferred else pages[-1]
        try:
            self.page.bring_to_front()
        except Exception:
            pass
        return self.page

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

    def locator(self, key: str, timeout=1500):
        cfg = self._cfg(key)
        candidates = list(cfg.get("candidates") or [])
        for k in ("css", "placeholder", "text"):
            if cfg.get(k):
                candidates.append({"kind": k, "value": cfg[k]})

        for cand in candidates:
            try:
                group = self._candidate_locator(cand)
                count = min(group.count(), 20)
            except Exception:
                continue

            for i in range(count):
                try:
                    loc = group.nth(i)
                    if loc.is_visible(timeout=timeout):
                        return loc
                except Exception:
                    continue

        raise PublishError(f"未找到页面元素：{key}。请在 config/selectors.json 校准该节点。")

    def click(self, key: str, timeout=8000):
        loc = self.locator(key, timeout=min(timeout, 2200))
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        loc.click(timeout=timeout)
        return loc

    def wait_page_ready(self, ms=700):
        self.page.wait_for_timeout(ms)

    def screenshot_error(self, task_code: str):
        self._sync_active_page()
        safe = "".join(ch for ch in task_code if ch.isalnum() or ch in "_-") or "task"
        path = self.screenshot_dir / f"{safe}_error.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    def diagnostic_summary(self) -> str:
        try:
            inputs = self.page.locator("input")
            textareas = self.page.locator("textarea")
            contents = self.page.locator("[contenteditable='true']")
            return (
                f"URL={self.page.url}; "
                f"input={inputs.count()}; textarea={textareas.count()}; "
                f"contenteditable={contents.count()}"
            )
        except Exception:
            return f"URL={getattr(self.page, 'url', '')}"

    def _visible_controls_in_ancestor(self, text: str, exact=True):
        """从字段标签向上找表单容器，再找其中的可编辑控件。"""
        labels = self.page.get_by_text(text, exact=exact)
        try:
            count = min(labels.count(), 15)
        except Exception:
            count = 0

        results = []
        for i in range(count):
            label = labels.nth(i)
            try:
                if not label.is_visible(timeout=400):
                    continue
            except Exception:
                continue

            # 从标签父级开始最多向上 5 层，适配抖店动态表单结构
            for depth in range(1, 6):
                xpath = "/.." * depth
                try:
                    ancestor = label.locator("xpath=" + xpath)
                    controls = ancestor.locator(
                        "input:not([type='hidden']):not([disabled]), "
                        "textarea:not([disabled]), "
                        "[contenteditable='true']"
                    )
                    c = min(controls.count(), 20)
                except Exception:
                    continue

                for j in range(c):
                    ctl = controls.nth(j)
                    try:
                        if not ctl.is_visible(timeout=300):
                            continue
                        box = ctl.bounding_box()
                        if not box or box["width"] < 80 or box["height"] < 18:
                            continue
                        key = (
                            round(box["x"]), round(box["y"]),
                            round(box["width"]), round(box["height"])
                        )
                        if all(r[0] != key for r in results):
                            results.append((key, ctl, depth))
                    except Exception:
                        continue

                if results:
                    return results
        return results

    def _title_input(self):
        self._sync_active_page()

        # 1) 先尝试旧配置，保持兼容
        try:
            return self.locator("title_input", timeout=900)
        except Exception:
            pass

        # 2) 根据截图中的字段名“商品标题”做相对定位
        controls = self._visible_controls_in_ancestor("商品标题", exact=True)
        if controls:
            # 商品标题框是该行最宽的可编辑控件，优先选宽度最大的
            controls.sort(key=lambda x: x[0][2], reverse=True)
            return controls[0][1]

        # 3) 兜底：找页面顶部基础信息区域的长文本框
        candidates = self.page.locator(
            "input:not([type='hidden']):not([disabled]), textarea:not([disabled])"
        )
        found = []
        try:
            count = min(candidates.count(), 80)
        except Exception:
            count = 0

        for i in range(count):
            loc = candidates.nth(i)
            try:
                if not loc.is_visible(timeout=250):
                    continue
                box = loc.bounding_box()
                if not box or box["width"] < 350:
                    continue
                val = ""
                try:
                    val = loc.input_value().strip()
                except Exception:
                    pass
                # 标题截图中是较长已有文本，优先有内容的宽输入框
                if len(val) >= 8:
                    found.append((box["y"], -box["width"], loc))
            except Exception:
                continue

        if found:
            found.sort(key=lambda x: (x[0], x[1]))
            return found[0][2]

        raise PublishError(
            "未能定位“商品标题”输入框。"
            + self.diagnostic_summary()
        )

    def _sku_value_input(self):
        self._sync_active_page()

        # 根据截图：商品规格 > 包装规格 > 已有规格值
        controls = self._visible_controls_in_ancestor("包装规格", exact=True)

        scored = []
        for key, ctl, depth in controls:
            try:
                tag = ctl.evaluate("(e)=>e.tagName.toLowerCase()")
            except Exception:
                tag = ""
            try:
                placeholder = ctl.get_attribute("placeholder") or ""
            except Exception:
                placeholder = ""
            try:
                value = ctl.input_value().strip() if tag in ("input", "textarea") else (ctl.inner_text() or "").strip()
            except Exception:
                value = ""

            # 排除截图中“填写并新增规格值”的新增框
            if "新增规格" in placeholder or "新增规格值" in placeholder:
                continue

            score = 0
            if value:
                score += 100
            if len(value) >= 4:
                score += 50
            if key[2] >= 140:
                score += 10
            score -= depth
            scored.append((score, ctl))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]

        # 兼容旧 placeholder 方案
        try:
            return self.locator("sku_name_input", timeout=1200)
        except Exception:
            pass

        raise PublishError(
            "未能定位“包装规格”已有规格值输入框。"
            + self.diagnostic_summary()
        )

    def _has_source_search(self, timeout=2200) -> bool:
        try:
            self.locator("source_search_input", timeout=timeout)
            return True
        except PublishError:
            return False

    def _click_visible_text(self, text: str, exact=True, timeout=5000):
        group = self.page.get_by_text(text, exact=exact)
        try:
            count = min(group.count(), 20)
        except Exception:
            count = 0
        last_exc = None
        for i in range(count):
            loc = group.nth(i)
            try:
                if not loc.is_visible(timeout=500):
                    continue
                loc.scroll_into_view_if_needed(timeout=1000)
                loc.click(timeout=timeout)
                return loc
            except Exception as exc:
                last_exc = exc
        raise PublishError(f"未找到可点击文字：{text}") from last_exc

    def _click_product_management_directly(self):
        try:
            self.click("product_list", timeout=8000)
            return
        except Exception:
            pass
        self._click_visible_text("商品管理", exact=True, timeout=5000)

    def open_product_list(self):
        self.step("绑定当前抖店标签页", 5)
        self._sync_active_page()
        self.wait_page_ready(400)

        if self._has_source_search(1800):
            self.step("已在商品列表", 12)
            return

        self.step("点击商品管理", 8)
        try:
            self._click_product_management_directly()
        except Exception as exc:
            raise PublishError(f"未能点击“商品管理”。当前页面：{self.page.url}") from exc

        self.wait_page_ready(1000)
        self._sync_active_page()
        self.wait_page_ready(600)

        if self._has_source_search(5000):
            self.step("已进入商品列表", 12)
            return

        try:
            self.step("展开商品菜单", 9)
            self.click("nav_product", timeout=6000)
            self.wait_page_ready(400)
            self._click_product_management_directly()
            self.wait_page_ready(900)
            self._sync_active_page()
        except Exception:
            pass

        if self._has_source_search(5000):
            self.step("已进入商品列表", 12)
            return

        raise PublishError(
            "已经执行“商品管理”点击，但目标页面没有识别到商品列表搜索框。"
            f" 当前URL：{self.page.url}"
        )

    def search_source_product(self, keyword: str):
        self._sync_active_page()
        self.step("搜索源商品", 18)

        box = self.locator("source_search_input", timeout=4000)
        box.fill("")
        box.fill(keyword)

        try:
            self.click("source_search_button", timeout=5000)
        except PublishError:
            box.press("Enter")

        self.wait_page_ready(1200)
        self._sync_active_page()

        row = self.page.locator("tr").filter(has_text=keyword).first
        try:
            row.wait_for(state="visible", timeout=3500)
            return row
        except Exception:
            return None

    def _handle_similar_confirm_dialog(self):
        self._sync_active_page()
        self.wait_page_ready(350)

        try:
            title = self.page.get_by_text("请确认要进行的操作", exact=False).first
            title.wait_for(state="visible", timeout=1800)
        except Exception:
            return

        self.step("确认发布相似品", 32)

        texts = self.page.get_by_text("发布相似品", exact=True)
        clicked = False
        try:
            count = min(texts.count(), 20)
        except Exception:
            count = 0

        for i in range(count - 1, -1, -1):
            try:
                loc = texts.nth(i)
                if loc.is_visible(timeout=400):
                    loc.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            raise PublishError("已出现操作确认弹窗，但未能选中“发布相似品”。")

        self.wait_page_ready(250)

        for label in ("确定", "确认"):
            try:
                group = self.page.get_by_role("button", name=label, exact=True)
                cnt = min(group.count(), 12)
                for i in range(cnt - 1, -1, -1):
                    btn = group.nth(i)
                    if btn.is_visible(timeout=400):
                        btn.click(timeout=6000)
                        self.wait_page_ready(1000)
                        self._sync_active_page()
                        return
            except Exception:
                continue

        raise PublishError("已选中“发布相似品”，但未能点击确认弹窗中的“确定”。")

    def open_similar_product(self, keyword: str):
        self.step("打开发布相似品", 28)
        row = self.search_source_product(keyword)

        clicked = False
        if row is not None:
            for txt in self._cfg("similar_publish_row_texts").get("values", ["发布相似品", "相似品"]):
                try:
                    btn = row.get_by_text(txt, exact=False).first
                    btn.wait_for(state="visible", timeout=1200)
                    btn.click()
                    clicked = True
                    break
                except Exception:
                    pass

            if not clicked:
                for txt in self._cfg("row_more_texts").get("values", ["更多", "操作"]):
                    try:
                        btn = row.get_by_text(txt, exact=False).first
                        btn.wait_for(state="visible", timeout=1200)
                        btn.click()
                        self.wait_page_ready(350)
                        self.click("similar_publish_entry", timeout=5000)
                        clicked = True
                        break
                    except Exception:
                        pass

        if not clicked:
            try:
                self.click("similar_publish_entry", timeout=5000)
            except PublishError:
                self.click("row_more_button", timeout=5000)
                self.click("similar_publish_entry", timeout=5000)

        self.wait_page_ready(500)
        self._handle_similar_confirm_dialog()
        self.wait_page_ready(900)
        self._sync_active_page()

    def wait_edit_page(self):
        self._sync_active_page()
        self.step("等待相似品编辑页", 36)
        self._title_input()
        self.wait_page_ready(500)

    def replace_title(self, new_title: str):
        self.step("修改商品标题", 46)
        loc = self._title_input()
        try:
            loc.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        loc.fill(new_title, timeout=10000)
        self.wait_page_ready(300)

    def replace_first_main_image(self, image_path: str):
        self.step("替换第一张主图", 60)
        image = Path(image_path)

        if not image.exists() or not image.is_file():
            raise PublishError(f"新首图不存在：{image}")
        if image.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise PublishError(f"不支持的首图格式：{image.suffix}")

        # 暂保留现有上传方案；若此节点失败，新诊断信息会继续用于精确校准。
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
        except Exception as exc:
            raise PublishError(
                "首图替换控件未定位成功。"
                + self.diagnostic_summary()
            ) from exc

    def replace_sku_name(self, sku_name: str):
        self.step("修改 SKU 名称", 74)
        loc = self._sku_value_input()
        try:
            loc.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        try:
            loc.fill("")
            loc.fill(sku_name)
        except Exception:
            # 部分动态表单可能使用 contenteditable
            try:
                loc.click()
                self.page.keyboard.press("Control+A")
                self.page.keyboard.type(sku_name)
            except Exception as exc:
                raise PublishError(
                    "已找到包装规格控件，但无法修改其值。"
                    + self.diagnostic_summary()
                ) from exc
        self.wait_page_ready(350)

    def _read_editable_value(self, loc):
        try:
            return loc.input_value().strip()
        except Exception:
            try:
                return (loc.inner_text() or "").strip()
            except Exception:
                return ""

    def preflight_guard(self, expected_title: str, expected_sku: str):
        self.step("发布前校验", 84)

        title = self._read_editable_value(self._title_input())
        if title != expected_title.strip():
            raise PublishError(
                f"发布前校验失败：商品标题不一致。页面值={title!r}"
            )

        sku = self._read_editable_value(self._sku_value_input())
        if sku != expected_sku.strip():
            raise PublishError(
                f"发布前校验失败：SKU 名称不一致。页面值={sku!r}"
            )

    def submit(self, safe_mode: bool):
        if safe_mode:
            self.step("已到发布前安全停点", 92)
            return "待确认", "已完成标题、首图、SKU 修改，已停在最终发布前。"

        self.step("提交发布", 92)
        self.click("publish_button", timeout=12000)
        self.wait_page_ready(800)
        self._sync_active_page()

        success_texts = self._cfg("publish_success_texts").get(
            "values", ["商品提交成功", "提交成功", "发布成功"]
        )
        for text in success_texts:
            try:
                self.page.get_by_text(text, exact=False).first.wait_for(
                    state="visible", timeout=15000
                )
                self.step("发布成功", 100)
                return "成功", text
            except Exception:
                continue

        raise PublishError("已点击发布，但未检测到成功反馈，请人工检查页面。")

    def run(self, task: dict, template: dict, safe_mode=True):
        code = str(task.get("task_code", "task"))
        try:
            self._sync_active_page()
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
            raise PublishError(
                f"页面等待超时，已截图：{shot}; {self.diagnostic_summary()}"
            ) from exc
        except Exception:
            try:
                self.screenshot_error(code)
            except Exception:
                pass
            raise


DouDianPublisher = DouDianSimilarPublisher
