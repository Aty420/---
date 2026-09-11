from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


class PublishError(RuntimeError):
    pass


class DouDianSimilarPublisher:
    """抖店发布相似品 RPA - V2.0.8
    核心修复：自动遍历主页面及所有 iframe。
    """

    def __init__(self, page: Page, selector_file: Path, screenshot_dir: Path,
                 step_cb: Callable[[str, int], None] | None = None):
        self.page = page
        self.selector_file = selector_file
        self.screenshot_dir = screenshot_dir
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.selectors = json.loads(selector_file.read_text(encoding="utf-8"))
        self.step_cb = step_cb or (lambda _s, _p: None)
        self._sku_verified = False

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

    def _scopes(self):
        """返回当前页面所有 Frame（包含主 frame），优先子 frame。"""
        self._sync_active_page()
        try:
            frames = list(self.page.frames)
        except Exception:
            frames = []
        # 编辑器常在子 frame 中，优先查子 frame，再查 main frame
        children = [f for f in frames if f != self.page.main_frame]
        ordered = children + ([self.page.main_frame] if self.page.main_frame else [])
        return ordered or [self.page]

    def _candidate_locator(self, scope, candidate: dict):
        kind = candidate.get("kind", "text")
        value = candidate.get("value", "")
        exact = bool(candidate.get("exact", False))
        if kind == "text":
            return scope.get_by_text(value, exact=exact)
        if kind == "placeholder":
            return scope.get_by_placeholder(value, exact=exact)
        if kind == "label":
            return scope.get_by_label(value, exact=exact)
        if kind == "role":
            return scope.get_by_role(candidate.get("role", "button"), name=value, exact=exact)
        if kind == "css":
            return scope.locator(value)
        raise PublishError(f"不支持的 selector 类型: {kind}")

    def locator(self, key: str, timeout=1500):
        cfg = self._cfg(key)
        candidates = list(cfg.get("candidates") or [])
        for k in ("css", "placeholder", "text"):
            if cfg.get(k):
                candidates.append({"kind": k, "value": cfg[k]})

        for scope in self._scopes():
            for cand in candidates:
                try:
                    group = self._candidate_locator(scope, cand)
                    count = min(group.count(), 30)
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
        info = []
        self._sync_active_page()
        try:
            frames = self.page.frames
        except Exception:
            frames = []
        for idx, f in enumerate(frames):
            try:
                input_count = f.locator("input").count()
                textarea_count = f.locator("textarea").count()
                editable_count = f.locator("[contenteditable='true']").count()
                info.append(
                    f"frame{idx}[url={f.url};input={input_count};"
                    f"textarea={textarea_count};contenteditable={editable_count}]"
                )
            except Exception:
                info.append(f"frame{idx}[unreadable]")
        return f"page={self.page.url}; frames={len(frames)}; " + " | ".join(info)

    def _visible_controls_in_ancestor(self, text: str, exact=True):
        results = []
        for scope in self._scopes():
            try:
                labels = scope.get_by_text(text, exact=exact)
                count = min(labels.count(), 20)
            except Exception:
                continue

            for i in range(count):
                label = labels.nth(i)
                try:
                    if not label.is_visible(timeout=350):
                        continue
                except Exception:
                    continue

                for depth in range(1, 7):
                    try:
                        ancestor = label.locator("xpath=" + "/.." * depth)
                        controls = ancestor.locator(
                            "input:not([type='hidden']):not([disabled]), "
                            "textarea:not([disabled]), "
                            "[contenteditable='true']"
                        )
                        c = min(controls.count(), 30)
                    except Exception:
                        continue

                    local = []
                    for j in range(c):
                        ctl = controls.nth(j)
                        try:
                            if not ctl.is_visible(timeout=250):
                                continue
                            box = ctl.bounding_box()
                            if not box or box["width"] < 70 or box["height"] < 16:
                                continue
                            local.append((box, ctl, depth))
                        except Exception:
                            continue
                    if local:
                        results.extend(local)
                        break
        return results

    def _title_input(self):
        # 1) 旧 selector 兼容
        try:
            return self.locator("title_input", timeout=900)
        except Exception:
            pass

        # 2) 字段标签相对定位（遍历 iframe）
        controls = self._visible_controls_in_ancestor("商品标题", exact=True)
        if controls:
            # 标题通常是最宽、且位于页面较上方的控件
            scored = []
            for box, ctl, depth in controls:
                try:
                    val = ctl.input_value().strip()
                except Exception:
                    val = ""
                score = box["width"] * 2 - box["y"] - depth * 10
                if len(val) >= 8:
                    score += 500
                scored.append((score, ctl))
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]

        # 3) 全 frame 宽输入框兜底
        found = []
        for scope in self._scopes():
            try:
                candidates = scope.locator(
                    "input:not([type='hidden']):not([disabled]), textarea:not([disabled])"
                )
                count = min(candidates.count(), 120)
            except Exception:
                continue
            for i in range(count):
                loc = candidates.nth(i)
                try:
                    if not loc.is_visible(timeout=200):
                        continue
                    box = loc.bounding_box()
                    if not box or box["width"] < 300:
                        continue
                    val = ""
                    try:
                        val = loc.input_value().strip()
                    except Exception:
                        pass
                    score = box["width"] - box["y"]
                    if len(val) >= 8:
                        score += 400
                    found.append((score, loc))
                except Exception:
                    continue
        if found:
            found.sort(key=lambda x: x[0], reverse=True)
            return found[0][1]

        raise PublishError("未能定位“商品标题”输入框。 " + self.diagnostic_summary())

    def _open_pack_spec_editor(self):
        """按录屏中的正确路径打开“包装规格”的组合规格编辑浮层。"""
        label = self._visible_text_locator("包装规格", exact=True, timeout_ms=15000)
        try:
            label.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass
        self.page.wait_for_timeout(350)
        box = label.bounding_box()
        if not box:
            raise PublishError("无法获取“包装规格”位置。")

        # 录屏中的正确动作：点击“包装规格”标题正下方的已有规格值胶囊，
        # 而不是价格库存表格中的“价格”输入框。
        x = box["x"] + max(70, min(120, box["width"] + 35))
        y = box["y"] + box["height"] + 36
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(450)

        try:
            return self._visible_text_locator("选择规则", exact=True, timeout_ms=6000)
        except Exception as exc:
            raise PublishError(
                "未打开包装规格组合编辑器。应点击包装规格下方已有规格值，而不是价格输入框。"
            ) from exc

    def _sku_value_input(self):
        """只定位组合规格浮层里最左侧的‘名称’输入框，绝不回退到价格输入框。"""
        rule = self._visible_text_locator("选择规则", exact=True, timeout_ms=6000)
        rule_box = rule.bounding_box()
        if not rule_box:
            raise PublishError("无法获取“选择规则”浮层位置。")

        candidates = []
        for scope in self._scopes():
            try:
                inputs = scope.locator("input:not([type='hidden']):not([disabled])")
                count = min(inputs.count(), 120)
            except Exception:
                continue

            for i in range(count):
                loc = inputs.nth(i)
                try:
                    if not loc.is_visible(timeout=250):
                        continue
                    box = loc.bounding_box()
                    if not box:
                        continue
                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2

                    # 浮层第一行位于“选择规则”下方约 20~110px。
                    # 只允许这个小区域，彻底排除页面下方的“价格/库存”等输入框。
                    if not (rule_box["x"] - 30 <= cx <= rule_box["x"] + 700):
                        continue
                    if not (rule_box["y"] + 20 <= cy <= rule_box["y"] + 120):
                        continue

                    placeholder = (loc.get_attribute("placeholder") or "").strip()
                    if any(word in placeholder for word in (
                        "价格", "库存", "商家编码", "条形码", "新增规格", "新增规格值"
                    )):
                        continue

                    # 录屏中要改的是最左侧第一格：产品/SKU 名称；
                    # 右侧的 100、抽、1、包全部保持原样。
                    candidates.append((box["x"], box["y"], loc))
                except Exception:
                    continue

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1]))
            return candidates[0][2]

        raise PublishError(
            "已打开包装规格编辑器，但未找到最左侧 SKU 名称输入框。" + self.diagnostic_summary()
        )

    def _has_source_search(self, timeout=2200) -> bool:
        try:
            self.locator("source_search_input", timeout=timeout)
            return True
        except PublishError:
            return False

    def _click_visible_text(self, text: str, exact=True, timeout=5000):
        for scope in self._scopes():
            try:
                group = scope.get_by_text(text, exact=exact)
                count = min(group.count(), 30)
            except Exception:
                continue
            for i in range(count):
                loc = group.nth(i)
                try:
                    if not loc.is_visible(timeout=400):
                        continue
                    loc.scroll_into_view_if_needed(timeout=1000)
                    loc.click(timeout=timeout)
                    return loc
                except Exception:
                    continue
        raise PublishError(f"未找到可点击文字：{text}")

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

        # 从所有 frame 中寻找包含源商品 ID/关键词的行
        for scope in self._scopes():
            try:
                row = scope.locator("tr").filter(has_text=keyword).first
                row.wait_for(state="visible", timeout=1800)
                return row
            except Exception:
                continue
        return None

    def _handle_similar_confirm_dialog(self):
        self._sync_active_page()
        self.wait_page_ready(350)

        dialog_scope = None
        for scope in self._scopes():
            try:
                title = scope.get_by_text("请确认要进行的操作", exact=False).first
                title.wait_for(state="visible", timeout=900)
                dialog_scope = scope
                break
            except Exception:
                continue
        if dialog_scope is None:
            return

        self.step("确认发布相似品", 32)
        texts = dialog_scope.get_by_text("发布相似品", exact=True)
        clicked = False
        try:
            count = min(texts.count(), 20)
        except Exception:
            count = 0

        for i in range(count - 1, -1, -1):
            try:
                loc = texts.nth(i)
                if loc.is_visible(timeout=300):
                    loc.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            raise PublishError("已出现确认弹窗，但未能选中“发布相似品”。")

        self.wait_page_ready(250)

        for label in ("确定", "确认"):
            try:
                group = dialog_scope.get_by_role("button", name=label, exact=True)
                cnt = min(group.count(), 12)
                for i in range(cnt - 1, -1, -1):
                    btn = group.nth(i)
                    if btn.is_visible(timeout=300):
                        btn.click(timeout=6000)
                        self.wait_page_ready(1000)
                        self._sync_active_page()
                        return
            except Exception:
                continue
        raise PublishError("已选中“发布相似品”，但未能点击“确定”。")

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

    def _visible_text_locator(self, text: str, exact=True, timeout_ms=30000):
        """等待页面中的可见文字出现，并优先返回编辑区左侧的匹配项。"""
        deadline = time.monotonic() + timeout_ms / 1000
        last = None
        while time.monotonic() < deadline:
            candidates = []
            for scope in self._scopes():
                try:
                    group = scope.get_by_text(text, exact=exact)
                    count = min(group.count(), 30)
                except Exception as exc:
                    last = exc
                    continue
                for i in range(count):
                    loc = group.nth(i)
                    try:
                        if not loc.is_visible(timeout=250):
                            continue
                        box = loc.bounding_box()
                        if not box:
                            continue
                        # 编辑区通常位于页面左/中部；排除右侧消费者预览中的同名文字。
                        vw = (self.page.viewport_size or {}).get("width", 99999)
                        penalty = 5000 if box["x"] > vw * 0.80 else 0
                        candidates.append((penalty + box["x"] + box["y"] * 0.05, loc, box))
                    except Exception as exc:
                        last = exc
                        continue
            if candidates:
                candidates.sort(key=lambda x: x[0])
                return candidates[0][1]
            self.page.wait_for_timeout(500)
        raise PublishError(f"等待页面文字超时：{text}。{self.diagnostic_summary()}") from last

    def _keyboard_edit_near_label(self, label_text: str, value: str, x_offset=240, y_offset=0):
        """用于抖店自定义富文本/组件：基于字段标签位置点击，再用真实键盘输入。"""
        label = self._visible_text_locator(label_text, exact=True, timeout_ms=10000)
        try:
            label.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass
        self.page.wait_for_timeout(250)
        box = label.bounding_box()
        if not box:
            raise PublishError(f"无法获取字段位置：{label_text}")
        x = box["x"] + box["width"] + x_offset
        y = box["y"] + box["height"] / 2 + y_offset
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(150)
        self.page.keyboard.press("Control+A")
        self.page.wait_for_timeout(80)
        self.page.keyboard.insert_text(value)
        self.page.wait_for_timeout(500)

    def _visible_text_exists(self, text: str, timeout_ms=2500) -> bool:
        try:
            self._visible_text_locator(text, exact=False, timeout_ms=timeout_ms)
            return True
        except Exception:
            return False

    def wait_edit_page(self):
        self._sync_active_page()
        self.step("等待相似品编辑页加载", 36)

        # 抖店发布页是 SPA，URL 已切换并不代表表单完成 hydration。
        # 旧版本只等约 1 秒，用户机器上经常出现页面肉眼稍后才加载完成的情况。
        self._visible_text_locator("商品标题", exact=True, timeout_ms=30000)
        self._visible_text_locator("基础信息", exact=True, timeout_ms=10000)
        self.page.wait_for_timeout(1200)
        self.step("编辑页加载完成", 40)

    def replace_title(self, new_title: str):
        self.step("修改商品标题", 46)

        # 优先标准 DOM；若抖店把标题渲染成自定义富文本组件，则退化为标签定位+键盘输入。
        try:
            loc = self._title_input()
            try:
                loc.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                loc.fill(new_title, timeout=8000)
            except Exception:
                loc.click()
                self.page.keyboard.press("Control+A")
                self.page.keyboard.insert_text(new_title)
        except Exception:
            self._keyboard_edit_near_label("商品标题", new_title, x_offset=260, y_offset=0)

        # 自定义组件无法可靠读取 input_value，因此同时用页面可见文本做校验。
        if not self._visible_text_exists(new_title, timeout_ms=3500):
            try:
                loc = self._title_input()
                value = self._read_editable_value(loc)
                if value.strip() != new_title.strip():
                    raise PublishError(
                        f"标题输入后未检测到新标题。页面值={value!r}; {self.diagnostic_summary()}"
                    )
            except PublishError:
                raise
            except Exception:
                raise PublishError(
                    "标题输入动作已执行，但无法确认页面已更新。" + self.diagnostic_summary()
                )
        self.wait_page_ready(500)

    def replace_first_main_image(self, image_path: str):
        self.step("替换第一张主图", 60)
        image = Path(image_path)
        if not image.exists() or not image.is_file():
            raise PublishError(f"新首图不存在：{image}")
        if image.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise PublishError(f"不支持的首图格式：{image.suffix}")

        # 遍历所有 iframe 中的 file input
        cfg = self._cfg("first_main_image_input")
        css = cfg.get("css") or "input[type='file'][accept*='image']"
        for scope in self._scopes():
            try:
                inputs = scope.locator(css)
                if inputs.count() > 0:
                    inputs.nth(int(cfg.get("index", 0))).set_input_files(str(image))
                    self.wait_page_ready(900)
                    return
            except Exception:
                continue

        # 退化方案：点击替换/更换并接管 file chooser
        try:
            with self.page.expect_file_chooser(timeout=7000) as chooser_info:
                self.click("first_main_image_replace", timeout=6500)
            chooser_info.value.set_files(str(image))
            self.wait_page_ready(900)
            return
        except Exception as exc:
            raise PublishError(
                "首图替换控件未定位成功。 " + self.diagnostic_summary()
            ) from exc

    def replace_sku_name(self, sku_name: str):
        self._sku_verified = False
        self.step("进入价格库存", 70)
        try:
            self._click_visible_text("价格库存", exact=True, timeout=6000)
        except Exception:
            pass
        self.page.wait_for_timeout(900)

        self.step("打开包装规格编辑器", 73)
        self._open_pack_spec_editor()

        self.step("修改包装规格名称", 76)
        loc = self._sku_value_input()
        try:
            loc.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        try:
            loc.fill(sku_name, timeout=6000)
        except Exception:
            loc.click()
            self.page.keyboard.press("Control+A")
            self.page.wait_for_timeout(80)
            self.page.keyboard.insert_text(sku_name)

        self.page.wait_for_timeout(500)
        value = self._read_editable_value(loc)
        if value.strip() != sku_name.strip():
            raise PublishError(
                f"包装规格名称写入失败：目标={sku_name!r}，当前={value!r}。"
                "已禁止回退到价格输入框，请勿手动继续发布。"
            )
        self._sku_verified = True

        # 点击当前 tab 标题，让规格浮层失焦并提交组合值；
        # 100 / 抽 / 1 / 包等其余组成部分保持源商品原值。
        try:
            self._click_visible_text("价格库存", exact=True, timeout=2500)
        except Exception:
            pass
        self.page.wait_for_timeout(500)

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

        title_ok = self._visible_text_exists(expected_title, timeout_ms=1800)
        if not title_ok:
            try:
                title_ok = self._read_editable_value(self._title_input()) == expected_title.strip()
            except Exception:
                title_ok = False
        if not title_ok:
            raise PublishError("发布前校验失败：未确认新标题已写入。")

        # SKU 在 replace_sku_name 中已对“包装规格编辑浮层最左侧输入框”做精确值校验。
        # 不再使用页面上任意可见文本/任意 input 做兜底，避免把“价格”误当成 SKU。
        if not self._sku_verified:
            raise PublishError("发布前校验失败：包装规格名称未通过精确校验。")

    def submit(self, safe_mode: bool):
        if safe_mode:
            self.step("已到发布前安全停点", 92)
            return "待确认", "已完成标题、首图、包装规格名称修改，已停在最终发布前。"

        self.step("提交发布", 92)
        self.click("publish_button", timeout=12000)
        self.wait_page_ready(800)
        self._sync_active_page()

        success_texts = self._cfg("publish_success_texts").get(
            "values", ["商品提交成功", "提交成功", "发布成功"]
        )
        for scope in self._scopes():
            for text in success_texts:
                try:
                    scope.get_by_text(text, exact=False).first.wait_for(
                        state="visible", timeout=5000
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
