from __future__ import annotations

import os
import queue
import shutil
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QProgressBar, QTableWidgetItem, QVBoxLayout, QWidget
)

from app.main_window import SectionCard, button
from app.main_window_v211 import MainWindow as V211MainWindow, PausableBrowserWorker


_TASK_STATUS = {
    "待执行": ("待执行", "#64748B", "#F1F5F9", "#E2E8F0"),
    "排队中": ("排队中", "#3154D9", "#EEF3FF", "#D9E4FF"),
    "执行中": ("执行中", "#2563EB", "#EAF2FF", "#CFE0FF"),
    "待确认": ("待确认", "#A15C00", "#FFF7E6", "#FDE3AF"),
    "失败": ("失败", "#C4322B", "#FFF0EF", "#FFD6D2"),
}

_STORE_STATUS = {
    "未登录": ("未登录", "#64748B", "#F1F5F9", "#E2E8F0"),
    "浏览器已打开": ("浏览器已打开", "#087A4B", "#EAFBF3", "#C9F2DC"),
    "已连接": ("浏览器已打开", "#087A4B", "#EAFBF3", "#C9F2DC"),
    "浏览器已关闭": ("浏览器已关闭", "#64748B", "#F1F5F9", "#E2E8F0"),
    "连接已断开": ("连接已断开", "#C4322B", "#FFF0EF", "#FFD6D2"),
    "浏览器连接已断开": ("连接已断开", "#C4322B", "#FFF0EF", "#FFD6D2"),
}


def _clean_status(raw) -> str:
    return str(raw or "").replace("\x00", "").strip()


def fixed_status_pill(raw, *, store=False):
    mapping = _STORE_STATUS if store else _TASK_STATUS
    value = _clean_status(raw)
    key = value if value in mapping else ""
    if not key:
        for candidate in mapping:
            if candidate and candidate in value:
                key = candidate
                break
    if key:
        text, fg, bg, border = mapping[key]
    else:
        text, fg, bg, border = ("未知状态", "#7C3AED", "#F5F0FF", "#E5D8FF")

    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    lab.setTextFormat(Qt.PlainText)
    lab.setFixedHeight(24)
    lab.setMinimumWidth(78 if not store else 96)
    font = QFont("Microsoft YaHei UI", 9)
    font.setWeight(QFont.DemiBold)
    lab.setFont(font)
    lab.setStyleSheet(
        f"QLabel{{background:{bg};color:{fg};border:1px solid {border};"
        "border-radius:9px;padding:0px 9px;margin:0px;}}"
    )
    return lab


class SwitchableBrowserWorker(PausableBrowserWorker):
    """在 V2.1.1 暂停/自动重连能力上，增加人工关闭浏览器的实时感知。

    正常人工关闭 Edge/Chrome 窗口时，不自动把它重新拉起；Worker 会退出，
    软件无需重启即可选择另一个店铺 Profile。
    """

    browser_closed = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._external_context_closed = threading.Event()
        self._internal_closing = False
        self._closed_notified = False
        self._dead_heartbeat_count = 0

    def _on_context_closed(self):
        if not self._internal_closing and not self._stop:
            self._external_context_closed.set()

    def _close_browser(self):
        self._internal_closing = True
        try:
            super()._close_browser()
        finally:
            self._internal_closing = False

    def _start_browser(self):
        self._external_context_closed.clear()
        self._closed_notified = False
        self._dead_heartbeat_count = 0
        page = super()._start_browser()
        try:
            if self.browser and self.browser.context:
                self.browser.context.on("close", lambda *_: self._on_context_closed())
        except Exception:
            pass
        return page

    def _manual_close_detected(self) -> bool:
        if self._external_context_closed.is_set():
            return True
        if not self.connected or self.browser is None:
            return False
        try:
            # 允许 RPA 自己关闭单个发布页；只在整个 Context/所有页面都没了时判定关闭。
            pages = list(self.browser.context.pages) if self.browser.context else []
            if pages:
                if self.page is None or self.page.is_closed():
                    self.page = pages[-1]
                self._dead_heartbeat_count = 0
                return False
            self._dead_heartbeat_count += 1
        except Exception:
            self._dead_heartbeat_count += 1
        return self._dead_heartbeat_count >= 3

    def _notify_browser_closed(self):
        if self._closed_notified:
            return
        self._closed_notified = True
        self.connected = False
        self._pause_remaining("浏览器已关闭")
        self.connection_state.emit(False, "浏览器已关闭")
        self.browser_closed.emit("浏览器已关闭")
        self._stop = True
        self._pause_requested.clear()
        self._resume_gate.set()

    def _reconnect(self, attempts=2) -> bool:
        # 人工关闭浏览器 = 明确结束当前店铺会话，不自动重开。
        if self._external_context_closed.is_set():
            self._notify_browser_closed()
            return False
        return super()._reconnect(attempts=attempts)

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
                    self._wait_if_paused(str(task["task_code"]))
                    if self._stop:
                        break
                    self._execute_publish(task, template, safe_mode)
                    if self._manual_close_detected():
                        self._notify_browser_closed()
                        break
        finally:
            self._close_browser()


class MainWindow(V211MainWindow):
    """V2.1.2 store/cache/status lifecycle layer. 发布动作不修改。"""

    def __init__(self, root: Path):
        super().__init__(root)
        # 软件重新打开时，历史“已打开”只是上次运行残留，统一纠正为已关闭。
        self.db.mark_runtime_stores_closed()
        self.refresh_all()

    # ---------- store lifecycle ----------
    def _stop_current_browser(self, timeout_ms=6000) -> bool:
        worker = self.browser_worker
        if not worker or not worker.isRunning():
            return True
        try:
            worker.request_stop()
            worker.wait(timeout_ms)
        except Exception:
            return False
        return not worker.isRunning()

    def open_store_browser(self):
        store = self._selected_store()
        if not store:
            self.db.add_store("默认店铺", str(self.root / "data" / "profiles" / "default"))
            store = self.db.stores()[0]
            self.refresh_all()

        # 如果旧 Worker 仍在退场，短暂等待；无需关闭整个 DouRPA。
        if self.browser_worker and self.browser_worker.isRunning():
            if getattr(self.browser_worker, "connected", False):
                active = self.db.store(self.active_store_id) if self.active_store_id else None
                active_name = active["name"] if active else "当前店铺"
                QMessageBox.information(
                    self,
                    "浏览器正在运行",
                    f"{active_name} 的浏览器仍在运行。\n\n"
                    "直接关闭该 Edge/Chrome 浏览器窗口即可结束当前店铺运行状态；"
                    "关闭后无需退出 DouRPA，就可以选择并打开其他店铺。",
                )
                return
            self.browser_worker.request_stop()
            self.browser_worker.wait(2500)
            if self.browser_worker.isRunning():
                QMessageBox.warning(self, "正在结束旧浏览器", "请稍等 1~2 秒后再次点击打开店铺。")
                return

        self.active_store_id = int(store["id"])
        self.run_status.setText("正在启动浏览器")
        self.run_desc.setText(f"店铺：{store['name']}")
        self.run_progress.setValue(3)

        self.browser_worker = SwitchableBrowserWorker(
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
        self.browser_worker.pause_state.connect(self._pause_state_changed)
        self.browser_worker.browser_closed.connect(self._browser_closed)
        self.browser_worker.start()
        self.db.add_log("INFO", f"启动店铺浏览器：{store['name']}")

    def _browser_closed(self, message: str):
        store_id = self.active_store_id
        if store_id:
            self.db.update_store_status(store_id, "浏览器已关闭", touch_login=False)
        self.active_store_id = None
        self.engine_label.setText("浏览器已关闭")
        self.run_status.setText("浏览器已关闭")
        self.run_desc.setText("当前店铺浏览器已关闭，可直接选择其他店铺并打开。")
        self.run_progress.setValue(0)
        if hasattr(self, "pause_button"):
            self.pause_button.setEnabled(False)
        if hasattr(self, "resume_button"):
            self.resume_button.setEnabled(False)
        self.db.add_log("INFO", message)
        self.refresh_all()

    def _connection_state(self, connected: bool, msg: str):
        # 人工关闭浏览器时显示“浏览器已关闭”，不再显示成连接异常。
        if not connected and "浏览器已关闭" in str(msg):
            self._browser_closed("浏览器已关闭")
            return
        if connected:
            self.engine_label.setText("浏览器已连接")
            self.run_desc.setText(msg)
            if self.active_store_id:
                self.db.update_store_status(self.active_store_id, "浏览器已打开", touch_login=False)
            self.db.add_log("INFO", msg)
        else:
            self.engine_label.setText("浏览器连接已断开")
            self.run_status.setText("浏览器连接异常")
            self.run_desc.setText(msg)
            if self.active_store_id:
                self.db.update_store_status(self.active_store_id, "连接已断开", touch_login=False)
            self.db.add_log("ERROR", msg)
        self.refresh_all()

    def delete_selected_store(self):
        row = self.store_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "未选择店铺", "请先选择需要删除的店铺。")
            return
        item = self.store_table.item(row, 0)
        if not item:
            return
        store_id = int(item.text())
        store = self.db.store(store_id)
        if not store:
            self.refresh_all()
            return

        active_now = (
            self.active_store_id == store_id
            and self.browser_worker
            and self.browser_worker.isRunning()
        )
        extra = "\n\n该店铺浏览器正在运行，删除前会先关闭浏览器。" if active_now else ""
        answer = QMessageBox.question(
            self,
            "删除店铺",
            f"确认删除店铺“{store['name']}”？\n\n"
            "• 店铺记录会删除\n"
            "• 对应浏览器 Profile、Cookie、登录状态等登录缓存会一并删除\n"
            "• 关联源商品模板会自动解除店铺绑定\n"
            "• 已导入任务数据不会因此删除"
            + extra,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if active_now and not self._stop_current_browser():
            QMessageBox.critical(self, "删除失败", "当前浏览器未能完全关闭，为避免损坏 Profile，未执行删除。")
            return

        profile_dir = Path(str(store["profile_dir"]))
        try:
            # Profile 是 DouRPA 自己创建的登录缓存目录；删除店铺时按用户要求同步删除。
            if profile_dir.exists():
                shutil.rmtree(profile_dir)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "删除失败",
                f"店铺登录缓存目录无法删除：\n{profile_dir}\n\n{exc}\n\n店铺记录尚未删除。",
            )
            return

        self.db.delete_store(store_id)
        if self.active_store_id == store_id:
            self.active_store_id = None
        self.db.add_log("INFO", f"删除店铺及登录缓存：{store['name']}")
        self.engine_label.setText("RPA 引擎就绪")
        self.run_status.setText("浏览器已关闭")
        self.run_desc.setText("店铺及对应登录缓存已删除。")
        self.run_progress.setValue(0)
        self.refresh_all()

    # ---------- status rendering bug fix ----------
    def _fill_task_table(self, table, rows):
        table.setRowCount(len(rows))
        table.verticalHeader().setDefaultSectionSize(40)
        for r, x in enumerate(rows):
            vals = [
                x["id"], x["task_code"], x["template_name"], x["new_title"],
                x["sku_name"], Path(x["cover_image"]).name
            ]
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(str(v)))
            prog = QProgressBar()
            prog.setValue(int(x["progress"]))
            table.setCellWidget(r, 6, prog)
            table.setItem(r, 7, QTableWidgetItem(x["current_step"] or "等待"))
            table.setCellWidget(r, 8, fixed_status_pill(x["status"]))
            table.setItem(r, 9, QTableWidgetItem(str(x["attempts"])))
            table.setItem(r, 10, QTableWidgetItem(x["last_error"] or ""))
            table.setRowHeight(r, 40)
        table.resizeColumnsToContents()
        table.setColumnWidth(3, 390)
        table.setColumnWidth(8, 94)
        table.setColumnWidth(10, 300)

    def refresh_dashboard(self):
        rows = [x for x in self.db.tasks() if _clean_status(x["status"]) != "成功"][:7]
        self.dashboard_table.setRowCount(len(rows))
        self.dashboard_table.verticalHeader().setDefaultSectionSize(40)
        for r, x in enumerate(rows):
            vals = [x["task_code"], x["template_name"], x["new_title"], x["sku_name"]]
            for c, v in enumerate(vals):
                self.dashboard_table.setItem(r, c, QTableWidgetItem(str(v)))
            self.dashboard_table.setCellWidget(r, 4, fixed_status_pill(x["status"]))
            self.dashboard_table.setRowHeight(r, 40)
        self.dashboard_table.resizeColumnsToContents()
        self.dashboard_table.setColumnWidth(2, 420)
        self.dashboard_table.setColumnWidth(4, 94)

    def refresh_stores(self):
        if not hasattr(self, "store_table"):
            return
        rows = self.db.stores()
        self.store_table.setRowCount(len(rows))
        self.store_table.verticalHeader().setDefaultSectionSize(40)
        for r, x in enumerate(rows):
            vals = [x["id"], x["name"], x["profile_dir"]]
            for c, v in enumerate(vals):
                self.store_table.setItem(r, c, QTableWidgetItem(str(v)))
            self.store_table.setCellWidget(r, 3, fixed_status_pill(x["status"], store=True))
            self.store_table.setItem(r, 4, QTableWidgetItem(x["last_login"] or "-"))
            self.store_table.setRowHeight(r, 40)
        self.store_table.resizeColumnsToContents()
        self.store_table.setColumnWidth(2, 430)
        self.store_table.setColumnWidth(3, 116)

        if hasattr(self, "tpl_store"):
            current = self.tpl_store.currentData()
            self.tpl_store.blockSignals(True)
            self.tpl_store.clear()
            self.tpl_store.addItem("未指定店铺", None)
            for s in rows:
                self.tpl_store.addItem(s["name"], s["id"])
            idx = self.tpl_store.findData(current)
            self.tpl_store.setCurrentIndex(idx if idx >= 0 else 0)
            self.tpl_store.blockSignals(False)

    # ---------- cache settings ----------
    def _path_row(self, layout, label_text: str, path: Path, attr_name: str):
        row = QHBoxLayout()
        row.setSpacing(10)
        label = QLabel(label_text)
        label.setFixedWidth(120)
        edit = QLineEdit(str(path))
        edit.setReadOnly(True)
        edit.setCursorPosition(0)
        setattr(self, attr_name, edit)
        row.addWidget(label)
        row.addWidget(edit, 1)
        layout.addLayout(row)

    def _settings_page(self):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        c = SectionCard(
            "执行策略",
            "首次校准时建议开启安全停点。确认标题、第一张主图和 SKU 都替换正确后，再关闭它进行自动提交。",
        )
        from PySide6.QtWidgets import QCheckBox
        self.safe_mode = QCheckBox("首次测试模式：停在最终发布前，不自动点击发布商品")
        self.safe_mode.setChecked(True)
        c.body.addWidget(self.safe_mode)
        lay.addWidget(c)

        cache = SectionCard(
            "缓存与数据目录",
            "下面列出 DouRPA 所有主要本地数据位置。更改缓存总目录会迁移现有数据，并从下次启动开始使用新地址。",
        )
        self._path_row(cache.body, "缓存总目录", self.root, "cache_root_edit")
        self._path_row(cache.body, "任务数据库", self.root / "data" / "app.db", "db_path_edit")
        self._path_row(cache.body, "店铺登录缓存", self.root / "data" / "profiles", "profiles_path_edit")
        self._path_row(cache.body, "失败截图", self.root / "screenshots", "screenshots_path_edit")
        self._path_row(cache.body, "运行日志目录", self.root / "logs", "logs_path_edit")
        self._path_row(cache.body, "页面配置", self.root / "config", "config_path_edit")
        self._path_row(cache.body, "Excel 模板", self.root / "samples", "samples_path_edit")

        buttons = QHBoxLayout()
        change = button("更改缓存总目录", "primary")
        change.clicked.connect(self.change_cache_root)
        open_dir = button("打开当前缓存目录")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root))))
        buttons.addWidget(change)
        buttons.addWidget(open_dir)
        buttons.addStretch(1)
        cache.body.addLayout(buttons)
        lay.addWidget(cache)

        warn = QLabel(
            "缓存目录切换会复制数据库、店铺登录 Profile、截图、配置与模板。"
            "为避免浏览器 Profile 被占用，修改前必须先关闭当前店铺浏览器；迁移完成后重启 DouRPA 生效。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "background:#FFF9ED;color:#8A5B10;border:1px solid #FCE6B0;"
            "border-radius:10px;padding:12px;"
        )
        lay.addWidget(warn)
        lay.addStretch(1)
        return p

    def _migrate_cache(self, target: Path):
        current = self.root.resolve()
        target = target.resolve()
        target.mkdir(parents=True, exist_ok=True)

        # 避免目标目录位于当前缓存内部，造成递归复制。
        try:
            target.relative_to(current)
            raise ValueError("新缓存目录不能放在当前缓存目录内部。")
        except ValueError as exc:
            if str(exc).startswith("新缓存目录"):
                raise
        except Exception:
            pass

        for folder in ("config", "samples", "screenshots", "logs"):
            src = current / folder
            dst = target / folder
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.mkdir(parents=True, exist_ok=True)

        # data 下除 app.db 外照常迁移（主要是浏览器 Profile）。
        src_data = current / "data"
        dst_data = target / "data"
        dst_data.mkdir(parents=True, exist_ok=True)
        if src_data.exists():
            for child in src_data.iterdir():
                if child.name == "app.db":
                    continue
                dest = dst_data / child.name
                if child.is_dir():
                    shutil.copytree(child, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, dest)

        # SQLite 用 backup API，避免运行中的数据库直接文件复制不完整。
        target_db = dst_data / "app.db"
        with self.db.connect() as src_conn, sqlite3.connect(target_db) as dst_conn:
            src_conn.backup(dst_conn)

        # 迁移后的 DB 中，店铺 Profile 路径必须改到新缓存目录。
        old_profiles = (current / "data" / "profiles").resolve()
        new_profiles = (target / "data" / "profiles").resolve()
        with sqlite3.connect(target_db) as conn:
            rows = list(conn.execute("SELECT id, profile_dir FROM stores"))
            for store_id, raw_path in rows:
                try:
                    rel = Path(raw_path).resolve().relative_to(old_profiles)
                except Exception:
                    continue
                conn.execute(
                    "UPDATE stores SET profile_dir=?, status='浏览器已关闭' WHERE id=?",
                    (str(new_profiles / rel), store_id),
                )
            conn.commit()

    def change_cache_root(self):
        if self.browser_worker and self.browser_worker.isRunning():
            QMessageBox.warning(
                self,
                "请先关闭浏览器",
                "更改缓存地址前，请先关闭当前店铺浏览器窗口。关闭后无需退出 DouRPA，再回来修改即可。",
            )
            return

        chosen = QFileDialog.getExistingDirectory(self, "选择新的 DouRPA 缓存总目录", str(self.root.parent))
        if not chosen:
            return
        target = Path(chosen)
        if target.resolve() == self.root.resolve():
            QMessageBox.information(self, "地址未变化", "选择的目录就是当前缓存目录。")
            return

        answer = QMessageBox.question(
            self,
            "迁移缓存数据",
            f"是否将现有 DouRPA 数据迁移到：\n\n{target}\n\n"
            "迁移内容包含任务数据库、店铺登录缓存、截图、配置和模板。\n"
            "原目录会保留作为备份，不会自动删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            self._migrate_cache(target)
            settings = QSettings("LocalOps", "DouRPA")
            settings.setValue("cache_root", str(target.resolve()))
            settings.sync()
        except Exception as exc:
            QMessageBox.critical(self, "迁移失败", f"缓存数据迁移失败：\n\n{exc}")
            return

        # 显示下次启动将使用的路径；当前进程继续使用旧 root，避免中途切数据库。
        for edit, path in (
            (self.cache_root_edit, target),
            (self.db_path_edit, target / "data" / "app.db"),
            (self.profiles_path_edit, target / "data" / "profiles"),
            (self.screenshots_path_edit, target / "screenshots"),
            (self.logs_path_edit, target / "logs"),
            (self.config_path_edit, target / "config"),
            (self.samples_path_edit, target / "samples"),
        ):
            edit.setText(str(path))
            edit.setCursorPosition(0)

        QMessageBox.information(
            self,
            "迁移完成",
            f"缓存数据已迁移到：\n{target}\n\n"
            "新地址将在下一次启动 DouRPA 时正式生效。当前旧目录暂时保留作为备份。",
        )
