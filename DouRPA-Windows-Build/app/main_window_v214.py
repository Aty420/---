from __future__ import annotations

import queue
import random
import time
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from app.main_window_v209 import _is_connection_error
from app.main_window_v212 import SwitchableBrowserWorker
from app.main_window_v213 import MainWindow as V213MainWindow
from app.rpa.publisher import DouDianSimilarPublisher


MERCHANT_HOME = "https://fxg.jinritemai.com/"


class DelayedLoginBrowserWorker(SwitchableBrowserWorker):
    """V2.1.4

    在现有自动重连、暂停/继续、人工关闭浏览器识别基础上增加：
    1. 每次成功发布后，下一条任务随机等待 10~15 秒；
    2. 抖店登录成功后页面一直转圈时，直接取消当前登录状态并回登录页。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_publish_not_before = 0.0
        self._last_login_probe = 0.0
        self._login_success_seen_at = None
        self._login_force_attempts = 0
        self._last_login_force_at = 0.0

    # ---------- login watchdog ----------
    def _start_browser(self):
        page = super()._start_browser()
        self._next_publish_not_before = 0.0
        self._last_login_probe = 0.0
        self._login_success_seen_at = None
        self._login_force_attempts = 0
        self._last_login_force_at = 0.0
        self.info.emit("店铺浏览器已启动，正在检查抖店登录/跳转状态。")
        return page

    def _frame_text_visible(self, page, text: str) -> bool:
        try:
            frames = list(page.frames)
        except Exception:
            frames = []
        for frame in frames:
            try:
                loc = frame.get_by_text(text, exact=False).first
                if loc.is_visible(timeout=120):
                    return True
            except Exception:
                continue
        return False

    def _pick_live_page(self):
        try:
            if not self.browser or not self.browser.context:
                return self.page
            pages = [p for p in self.browser.context.pages if not p.is_closed()]
            if not pages:
                return self.page

            # 优先当前 page；如果当前已经失效，则采用最后一个页面。
            if self.page in pages:
                return self.page
            self.page = pages[-1]
            return self.page
        except Exception:
            return self.page

    def _merchant_ready(self, page) -> bool:
        """判断真正的抖店商家后台是否已经渲染完成，而不是只看 URL。"""
        markers = ("商品管理", "订单管理", "售后工作台", "店铺", "用户")
        for marker in markers:
            if self._frame_text_visible(page, marker):
                return True
        return False

    def _looks_like_login_page(self, page) -> bool:
        """仍处在登录/扫码页时不要主动干预。"""
        login_markers = ("扫码登录", "账号登录", "验证码登录", "抖音扫码", "登录抖店")
        return any(self._frame_text_visible(page, x) for x in login_markers)

    def _reset_login_state(self, page):
        """登录成功后持续转圈：直接清除当前店铺登录态，回到登录页重新登录。"""
        now = time.monotonic()

        # 每个浏览器会话只自动重置一次，避免用户正在重新登录时被反复清掉。
        if self._login_force_attempts >= 1:
            return

        self._login_force_attempts = 1
        self._last_login_force_at = now
        self.info.emit(
            "检测到登录成功后页面持续加载，正在取消当前登录状态并返回登录页…"
        )

        try:
            context = self.browser.context if self.browser else None
            if context is None:
                return

            # 1) 清 Cookie：这是抖店登录态最关键的数据。
            try:
                context.clear_cookies()
            except Exception:
                pass

            # 2) 清当前已打开页面的 localStorage / sessionStorage。
            try:
                pages = [p for p in context.pages if not p.is_closed()]
            except Exception:
                pages = []

            for p in pages:
                try:
                    p.evaluate(
                        """() => {
                            try { localStorage.clear(); } catch (e) {}
                            try { sessionStorage.clear(); } catch (e) {}
                        }"""
                    )
                except Exception:
                    pass

            # 3) 关闭多余标签，只保留一个，避免旧登录成功页继续占用。
            live_pages = []
            for p in pages:
                try:
                    if not p.is_closed():
                        live_pages.append(p)
                except Exception:
                    pass

            target = live_pages[0] if live_pages else context.new_page()
            for p in live_pages[1:]:
                try:
                    p.close()
                except Exception:
                    pass

            self.page = target

            # 4) 回到抖店入口。清 Cookie 后应重新出现登录页。
            target.goto(
                MERCHANT_HOME,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            target.wait_for_timeout(1200)

            self._login_success_seen_at = None
            self.info.emit(
                "当前店铺登录状态已取消，请重新扫码/登录。"
            )
        except Exception as exc:
            self.info.emit(f"取消登录状态未完成：{exc}")

    def _login_watchdog_tick(self, force: bool = False):
        """检测“登录成功后一直转圈”，不是简单把它当成未跳转。"""
        now = time.monotonic()
        if not force and now - self._last_login_probe < 0.8:
            return
        self._last_login_probe = now

        page = self._pick_live_page()
        if page is None:
            return
        try:
            if page.is_closed():
                return
        except Exception:
            return

        # 后台真正加载完成后立即结束登录监控。
        if self._merchant_ready(page):
            if self._login_success_seen_at is not None or self._login_force_attempts:
                self.info.emit("抖店工作台加载完成。")
            self._login_success_seen_at = None
            self._login_force_attempts = 0
            return

        # 还在扫码/输入验证码阶段，不主动刷新，避免干扰人工登录。
        if self._looks_like_login_page(page):
            self._login_success_seen_at = None
            return

        success_visible = self._frame_text_visible(page, "登录成功")
        waiting_visible = (
            self._frame_text_visible(page, "等待跳转")
            or self._frame_text_visible(page, "正在跳转")
            or self._frame_text_visible(page, "加载中")
        )

        if not success_visible:
            return

        if self._login_success_seen_at is None:
            self._login_success_seen_at = now
            self.info.emit("检测到登录成功，正在等待抖店工作台完成加载…")
            return

        # 已显示“登录成功”，但 8 秒后工作台仍未真正加载：
        # 按用户要求，不再尝试刷新/强行进入后台，而是直接取消登录状态。
        elapsed = now - self._login_success_seen_at
        if elapsed < 8.0:
            return

        if waiting_visible or not self._merchant_ready(page):
            self._reset_login_state(page)

    # ---------- 10~15s inter-task cooldown ----------
    def _schedule_next_publish_delay(self, code: str):
        seconds = random.uniform(10.0, 15.0)
        self._next_publish_not_before = time.monotonic() + seconds
        self.info.emit(
            f"{code} 已发布成功。下一条任务将在 {seconds:.1f} 秒后开始。"
        )

    def _wait_before_publish(self, code: str):
        deadline = self._next_publish_not_before
        if deadline <= 0:
            return

        announced_second = None
        while not self._stop:
            self._wait_if_paused(code)
            if self._stop:
                return

            self._login_watchdog_tick()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._next_publish_not_before = 0.0
                self.info.emit(f"任务间隔结束，准备执行 {code}。")
                return

            whole = max(1, int(remaining + 0.999))
            # 只在倒计时变化时写日志，避免每 0.25 秒刷屏。
            if whole != announced_second and (whole <= 5 or whole % 5 == 0):
                announced_second = whole
                self.info.emit(f"距离下一条任务约 {whole} 秒。")
            time.sleep(min(0.25, remaining))

    # ---------- publish ----------
    def _execute_publish(self, task, template, safe_mode):
        tid = int(task["id"])
        code = str(task["task_code"])

        self._wait_if_paused(code)
        if self._stop:
            return

        if not self._is_live():
            if not self._reconnect(attempts=2):
                self.task_error.emit(
                    tid, code, "浏览器连接中断，自动重连失败；批量队列已暂停。"
                )
                self._pause_remaining("浏览器连接中断，自动重连失败")
                return

        retried = False
        while True:
            pub = None
            try:
                def step_callback(step, prog, tid=tid, code=code):
                    self.task_step.emit(tid, code, step, prog)
                    self._wait_if_paused(code)
                    if self._stop:
                        raise RuntimeError("任务执行已停止")

                    # V2.1.4.3：每个 RPA 步骤统一额外等待 2 秒。
                    # step() 在实际动作前同步触发，所以这里会让页面有更充分的
                    # 渲染/响应时间，同时不改变原有动作顺序。
                    delay_deadline = time.monotonic() + 2.0
                    while time.monotonic() < delay_deadline:
                        self._wait_if_paused(code)
                        if self._stop:
                            raise RuntimeError("任务执行已停止")
                        time.sleep(min(0.2, delay_deadline - time.monotonic()))

                pub = DouDianSimilarPublisher(
                    self.page,
                    self.selector_file,
                    self.screenshot_dir,
                    step_cb=step_callback,
                )
                status, text = pub.run(task, template, safe_mode=safe_mode)
                self.page = pub.page
                self.task_done.emit(tid, code, status, text)

                if status == "成功" and not safe_mode:
                    # 无论商品管理页是否已经恢复，下一条都必须经过 10~15 秒间隔。
                    self._schedule_next_publish_delay(code)

                    if not pub.ready_for_next:
                        self.info.emit(
                            f"{code} 已发布成功，但未恢复商品管理页，正在重建浏览器环境。"
                        )
                        if not self._reconnect(attempts=2):
                            self._pause_remaining(
                                "当前商品已发布成功，但无法恢复商品管理/浏览器连接；后续任务已暂停"
                            )
                return

            except Exception as exc:
                if pub is not None:
                    try:
                        self.page = pub.page
                    except Exception:
                        pass

                if self._stop:
                    return

                if _is_connection_error(exc):
                    if pub is not None and getattr(pub, "publish_clicked", False):
                        self.task_error.emit(
                            tid,
                            code,
                            "提交发布后浏览器连接断开。为避免重复发布，"
                            "当前任务不自动重试；请人工确认是否已发布，批量队列已暂停。",
                        )
                        self._pause_remaining(
                            "提交后连接中断，为避免重复发布已暂停批量队列"
                        )
                        return

                    if not retried:
                        self.info.emit(
                            f"{code} 执行中检测到浏览器连接断开，"
                            "准备重连并重试当前任务 1 次。"
                        )
                        if self._reconnect(attempts=2):
                            retried = True
                            continue

                    self.task_error.emit(
                        tid,
                        code,
                        "浏览器连接中断且自动重连失败；"
                        "当前任务失败，后续批量任务已暂停。",
                    )
                    self._pause_remaining("浏览器连接中断，自动重连失败")
                    return

                self.task_error.emit(tid, code, str(exc))
                return

    def run(self):
        try:
            try:
                self._start_browser()
                self.ready.emit(
                    "浏览器已打开。已登录会直接进入抖店；"
                    "未登录时请人工扫码/完成安全验证。"
                )
            except Exception as exc:
                self.connected = False
                self.ready.emit(f"浏览器启动失败：{exc}")
                self.connection_state.emit(False, f"浏览器启动失败：{exc}")

            while not self._stop:
                try:
                    cmd, task, template, safe_mode = self.commands.get(timeout=.25)
                except queue.Empty:
                    # 空闲时处理登录成功页卡住问题，同时继续侦测人工关闭浏览器。
                    self._login_watchdog_tick()
                    if self._manual_close_detected():
                        self._notify_browser_closed()
                        break
                    continue

                if cmd == "stop":
                    self._stop = True
                    break

                if cmd == "reconnect":
                    ok = self._reconnect(attempts=2)
                    if ok:
                        self.ready.emit("浏览器已重新连接，可继续执行任务。")
                    continue

                if cmd == "publish":
                    code = str(task["task_code"])
                    self._wait_before_publish(code)
                    self._wait_if_paused(code)
                    if self._stop:
                        break
                    self._execute_publish(task, template, safe_mode)
                    if self._manual_close_detected():
                        self._notify_browser_closed()
                        break
        finally:
            self._close_browser()


class MainWindow(V213MainWindow):
    """V2.1.4: inter-task delay + DouDian login redirect recovery."""

    def open_store_browser(self):
        store = self._selected_store()
        if not store:
            self.db.add_store(
                "默认店铺",
                str(self.root / "data" / "profiles" / "default"),
            )
            store = self.db.stores()[0]
            self.refresh_all()

        if self.browser_worker and self.browser_worker.isRunning():
            if getattr(self.browser_worker, "connected", False):
                active = (
                    self.db.store(self.active_store_id)
                    if self.active_store_id else None
                )
                active_name = active["name"] if active else "当前店铺"
                QMessageBox.information(
                    self,
                    "浏览器正在运行",
                    f"{active_name} 的浏览器仍在运行。\n\n"
                    "需要切换店铺时，请先在工作台点击“结束运行”，"
                    "再选择其他店铺并打开。",
                )
                return

            self.browser_worker.request_stop()
            self.browser_worker.wait(2500)
            if self.browser_worker.isRunning():
                QMessageBox.warning(
                    self,
                    "正在结束旧浏览器",
                    "请稍等 1~2 秒后再次点击打开店铺。",
                )
                return

        self.active_store_id = int(store["id"])
        self.run_status.setText("正在启动浏览器")
        self.run_desc.setText(f"店铺：{store['name']}")
        self.run_progress.setValue(3)

        worker = DelayedLoginBrowserWorker(
            Path(store["profile_dir"]),
            self.root / "config" / "selectors.json",
            self.root / "screenshots",
            self,
        )
        self.browser_worker = worker
        worker.ready.connect(
            lambda msg, sid=int(store["id"]): self._browser_ready(sid, msg)
        )
        worker.task_step.connect(self._task_step)
        worker.task_done.connect(self._task_done)
        worker.task_error.connect(self._task_error)
        worker.info.connect(self._worker_info)
        worker.connection_state.connect(self._connection_state)
        worker.queue_paused.connect(self._queue_paused)
        worker.pause_state.connect(self._pause_state_changed)
        worker.browser_closed.connect(self._browser_closed)
        worker.finished.connect(lambda w=worker: self._worker_finished_cleanup(w))
        worker.start()
        self.db.add_log("INFO", f"启动店铺浏览器：{store['name']}")
