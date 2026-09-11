from __future__ import annotations

import queue
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox

from app.main_window import MainWindow as BaseMainWindow
from app.rpa.browser import BrowserManager
from app.rpa.publisher import DouDianSimilarPublisher


_CONNECTION_MARKERS = (
    "connection closed while reading from the driver",
    "connection closed",
    "target page, context or browser has been closed",
    "browser has been closed",
    "page has been closed",
    "playwright connection closed",
    "object has been collected",
)


def _is_connection_error(exc: Exception | str) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONNECTION_MARKERS)


class ResilientBrowserWorker(QThread):
    """V2.0.9: 浏览器真实存活检测、自动重连、失败时暂停后续队列。"""

    ready = Signal(str)
    info = Signal(str)
    task_step = Signal(int, str, str, int)
    task_done = Signal(int, str, str, str)
    task_error = Signal(int, str, str)
    connection_state = Signal(bool, str)
    queue_paused = Signal(object, str)

    def __init__(self, profile_dir: Path, selector_file: Path, screenshot_dir: Path, parent=None):
        super().__init__(parent)
        self.profile_dir = profile_dir
        self.selector_file = selector_file
        self.screenshot_dir = screenshot_dir
        self.commands = queue.Queue()
        self._stop = False
        self.browser: BrowserManager | None = None
        self.page = None
        self.connected = False

    def enqueue_publish(self, task: dict, template: dict, safe_mode: bool):
        self.commands.put(("publish", task, template, safe_mode))

    def request_stop(self):
        self.commands.put(("stop", None, None, None))

    def request_reconnect(self):
        self.commands.put(("reconnect", None, None, None))

    def _close_browser(self):
        browser, self.browser = self.browser, None
        self.page = None
        self.connected = False
        if browser:
            try:
                browser.stop()
            except Exception:
                pass

    def _start_browser(self):
        self._close_browser()
        browser = BrowserManager(self.profile_dir)
        page = browser.start()
        page.goto("https://fxg.jinritemai.com/", wait_until="domcontentloaded", timeout=60000)
        self.browser = browser
        self.page = page
        self.connected = True
        self.connection_state.emit(True, "浏览器已连接")
        return page

    def _is_live(self) -> bool:
        if not self.connected or self.page is None or self.browser is None:
            return False
        try:
            if self.page.is_closed():
                return False
            # 不只看 QThread 是否存活，真正访问 Playwright driver/context。
            pages = self.page.context.pages
            if not pages:
                return False
            _ = self.page.url
            return True
        except Exception:
            return False

    def _reconnect(self, attempts=2) -> bool:
        last = None
        for i in range(1, attempts + 1):
            try:
                self.info.emit(f"浏览器连接已断开，正在自动重连（{i}/{attempts}）…")
                self._start_browser()
                self.info.emit("浏览器自动重连成功，继续执行任务。")
                return True
            except Exception as exc:
                last = exc
                self._close_browser()
                time.sleep(1.2)
        self.connection_state.emit(False, f"浏览器重连失败：{last}")
        return False

    def _pause_remaining(self, reason: str):
        paused = []
        preserved = []
        while True:
            try:
                item = self.commands.get_nowait()
            except queue.Empty:
                break
            cmd, task, template, safe_mode = item
            if cmd == "publish" and task is not None:
                paused.append((int(task["id"]), str(task["task_code"])))
            else:
                preserved.append(item)
        for item in preserved:
            self.commands.put(item)
        if paused:
            self.queue_paused.emit(paused, reason)

    def _execute_publish(self, task, template, safe_mode):
        tid = int(task["id"])
        code = str(task["task_code"])

        # 每条任务开始前先做真实连接检查。
        if not self._is_live():
            if not self._reconnect(attempts=2):
                self.task_error.emit(tid, code, "浏览器连接中断，自动重连失败；批量队列已暂停。")
                self._pause_remaining("浏览器连接中断，自动重连失败")
                return

        retried = False
        while True:
            pub = None
            try:
                pub = DouDianSimilarPublisher(
                    self.page,
                    self.selector_file,
                    self.screenshot_dir,
                    step_cb=lambda step, prog, tid=tid, code=code: self.task_step.emit(
                        tid, code, step, prog
                    ),
                )
                status, text = pub.run(task, template, safe_mode=safe_mode)
                # publisher 可能切换/关闭过标签页，下一条必须接着使用它最后确认的 page。
                self.page = pub.page
                self.task_done.emit(tid, code, status, text)

                if status == "成功" and not safe_mode and not pub.ready_for_next:
                    # 当前商品已经发布成功，禁止重跑当前任务。只恢复浏览器环境。
                    self.info.emit(
                        f"{code} 已发布成功，但未恢复商品管理页，正在重建浏览器环境。"
                    )
                    if not self._reconnect(attempts=2):
                        self._pause_remaining(
                            "当前商品已发布成功，但无法恢复商品管理/浏览器连接；后续任务已暂停"
                        )
                return

            except Exception as exc:
                # 尽量保留 publisher 最后的 page 引用。
                if pub is not None:
                    try:
                        self.page = pub.page
                    except Exception:
                        pass

                if _is_connection_error(exc):
                    # 如果已经点击过“发布商品”，自动重跑可能制造重复商品，必须禁止。
                    if pub is not None and getattr(pub, "publish_clicked", False):
                        self.task_error.emit(
                            tid,
                            code,
                            "提交发布后浏览器连接断开。为避免重复发布，当前任务不自动重试；请人工确认是否已发布，批量队列已暂停。",
                        )
                        self._pause_remaining("提交后连接中断，为避免重复发布已暂停批量队列")
                        return

                    if not retried:
                        self.info.emit(f"{code} 执行中检测到浏览器连接断开，准备重连并重试当前任务 1 次。")
                        if self._reconnect(attempts=2):
                            retried = True
                            continue

                    self.task_error.emit(
                        tid, code, "浏览器连接中断且自动重连失败；当前任务失败，后续批量任务已暂停。"
                    )
                    self._pause_remaining("浏览器连接中断，自动重连失败")
                    return

                # 普通页面/数据错误仍按单条失败处理，不影响下一条。
                self.task_error.emit(tid, code, str(exc))
                return

    def run(self):
        try:
            try:
                self._start_browser()
                self.ready.emit("浏览器已打开。首次使用请在网页中人工扫码/完成安全验证。")
            except Exception as exc:
                self.connected = False
                self.ready.emit(f"浏览器启动失败：{exc}")
                self.connection_state.emit(False, f"浏览器启动失败：{exc}")

            while not self._stop:
                try:
                    cmd, task, template, safe_mode = self.commands.get(timeout=.25)
                except queue.Empty:
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
                    self._execute_publish(task, template, safe_mode)
        finally:
            self._close_browser()


class MainWindow(BaseMainWindow):
    """V2.0.9 UI 兼容层：使用可重连 Worker，不改动原高级 UI。"""

    def open_store_browser(self):
        store = self._selected_store()
        if not store:
            self.db.add_store("默认店铺", str(self.root / "data" / "profiles" / "default"))
            store = self.db.stores()[0]
            self.refresh_all()

        if self.browser_worker and self.browser_worker.isRunning():
            if getattr(self.browser_worker, "connected", False):
                QMessageBox.information(
                    self,
                    "浏览器已运行",
                    "当前浏览器 Profile 已经连接。关闭软件后可切换到其他店铺 Profile。",
                )
            else:
                self.run_status.setText("正在重新连接浏览器")
                self.run_desc.setText("正在恢复当前店铺 Profile…")
                self.browser_worker.request_reconnect()
            return

        self.active_store_id = int(store["id"])
        self.run_status.setText("正在启动浏览器")
        self.run_desc.setText(f"店铺：{store['name']}")
        self.run_progress.setValue(3)

        self.browser_worker = ResilientBrowserWorker(
            Path(store["profile_dir"]),
            self.root / "config" / "selectors.json",
            self.root / "screenshots",
            self,
        )
        self.browser_worker.ready.connect(
            lambda msg, sid=int(store["id"]): self._browser_ready(sid, msg)
        )
        self.browser_worker.task_step.connect(self._task_step)
        self.browser_worker.task_done.connect(self._task_done)
        self.browser_worker.task_error.connect(self._task_error)
        self.browser_worker.info.connect(self._worker_info)
        self.browser_worker.connection_state.connect(self._connection_state)
        self.browser_worker.queue_paused.connect(self._queue_paused)
        self.browser_worker.start()
        self.db.add_log("INFO", f"启动店铺浏览器：{store['name']}")

    def _ensure_browser(self):
        if not self.browser_worker or not self.browser_worker.isRunning():
            QMessageBox.information(
                self,
                "先打开店铺",
                "请先在“店铺管理”选择目标店铺并打开浏览器，确认已登录后再执行任务。",
            )
            return False
        if not getattr(self.browser_worker, "connected", False):
            QMessageBox.information(
                self,
                "浏览器连接已断开",
                "请先点击“打开当前店铺”重新连接。软件会继续复用原店铺 Profile 和登录状态。",
            )
            return False
        return True

    def _worker_info(self, msg: str):
        self.db.add_log("INFO", msg)
        self.run_desc.setText(msg)
        self.refresh_logs()

    def _connection_state(self, connected: bool, msg: str):
        if connected:
            self.engine_label.setText("浏览器已连接")
            self.run_desc.setText(msg)
            if self.active_store_id:
                self.db.update_store_status(self.active_store_id, "浏览器已打开")
        else:
            self.engine_label.setText("浏览器连接已断开")
            self.run_status.setText("浏览器连接异常")
            self.run_desc.setText(msg)
            if self.active_store_id:
                self.db.update_store_status(self.active_store_id, "连接已断开")
        self.db.add_log("INFO" if connected else "ERROR", msg)
        self.refresh_all()

    def _queue_paused(self, items, reason: str):
        # 后续尚未开始的任务不能被误标“失败”；恢复为待执行，等重连后重新批量运行。
        for tid, code in items:
            self.db.update_task(
                int(tid),
                status="待执行",
                progress=0,
                step="批量已暂停，等待浏览器恢复",
                error="",
            )
            self.db.add_log("INFO", f"批量暂停，任务已恢复为待执行：{reason}", str(code))
        self.run_status.setText("批量已暂停")
        self.run_desc.setText(reason)
        self.refresh_all()
