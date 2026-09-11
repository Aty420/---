from __future__ import annotations

import queue
import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from app.main_window import MetricCard, SectionCard, button
from app.main_window_v209 import ResilientBrowserWorker, _is_connection_error
from app.main_window_v210 import MainWindow as V210MainWindow, status_pill
from app.rpa.publisher import DouDianSimilarPublisher


class PausableBrowserWorker(ResilientBrowserWorker):
    """V2.1.1: 在 V2.0.9 自动重连基础上增加可暂停/继续队列。

    暂停采用安全步骤边界：当前网页动作不会被强制掐断；到下一个 RPA
    步骤前进入等待，继续后从原位置继续，不重新执行已经完成的步骤。
    """

    pause_state = Signal(bool, str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pause_requested = threading.Event()
        self._resume_gate = threading.Event()
        self._resume_gate.set()
        self._pause_announced = False

    @property
    def paused(self) -> bool:
        return self._pause_requested.is_set()

    def request_pause(self):
        self._pause_requested.set()
        self._resume_gate.clear()
        self.pause_state.emit(True, "已请求暂停，将在当前安全步骤完成后暂停。")

    def request_resume(self):
        self._pause_requested.clear()
        self._resume_gate.set()
        self._pause_announced = False
        self.pause_state.emit(False, "继续执行批量任务。")

    def request_stop(self):
        self._stop = True
        self._pause_requested.clear()
        self._resume_gate.set()
        try:
            self.commands.put(("stop", None, None, None))
        except Exception:
            pass

    def _wait_if_paused(self, code: str = ""):
        if not self._pause_requested.is_set():
            return
        if not self._pause_announced:
            suffix = f" · {code}" if code else ""
            self.pause_state.emit(True, f"执行已暂停{suffix}")
            self._pause_announced = True
        while self._pause_requested.is_set() and not self._stop:
            self._resume_gate.wait(0.25)
        if not self._stop and self._pause_announced:
            self._pause_announced = False
            suffix = f" · {code}" if code else ""
            self.pause_state.emit(False, f"执行已继续{suffix}")

    def _execute_publish(self, task, template, safe_mode):
        tid = int(task["id"])
        code = str(task["task_code"])

        self._wait_if_paused(code)
        if self._stop:
            return

        if not self._is_live():
            if not self._reconnect(attempts=2):
                self.task_error.emit(tid, code, "浏览器连接中断，自动重连失败；批量队列已暂停。")
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

                pub = DouDianSimilarPublisher(
                    self.page,
                    self.selector_file,
                    self.screenshot_dir,
                    step_cb=step_callback,
                )
                status, text = pub.run(task, template, safe_mode=safe_mode)
                self.page = pub.page
                self.task_done.emit(tid, code, status, text)

                if status == "成功" and not safe_mode and not pub.ready_for_next:
                    self.info.emit(f"{code} 已发布成功，但未恢复商品管理页，正在重建浏览器环境。")
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
                    self._wait_if_paused(str(task["task_code"]))
                    if self._stop:
                        break
                    self._execute_publish(task, template, safe_mode)
        finally:
            self._close_browser()


class MainWindow(V210MainWindow):
    """V2.1.1 task UX layer. 商品发布动作本身保持不变。"""

    def __init__(self, root: Path):
        self.session_success_count = 0
        super().__init__(root)
        self.db.purge_completed_tasks()
        self.refresh_all()

    # ---------- dashboard ----------
    def _dashboard_page(self):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.m_total = MetricCard("裂变任务", "0", "当前未完成任务")
        self.m_pending = MetricCard("待处理", "0", "待执行 / 排队 / 待确认")
        self.m_success = MetricCard("本次完成", "0", "本次启动后成功发布")
        self.m_failed = MetricCard("失败任务", "0", "可重新执行")
        for m in [self.m_total, self.m_pending, self.m_success, self.m_failed]:
            metrics.addWidget(m)
        lay.addLayout(metrics)

        row = QHBoxLayout()
        row.setSpacing(14)
        quick = SectionCard(
            "批量发布控制台",
            "任务执行中可随时请求暂停；当前网页动作完成后停在安全步骤边界，继续后从原位置执行。",
        )
        q = QHBoxLayout()
        q.setSpacing(8)
        b1 = button("导入裂变 Excel", "primary")
        b1.clicked.connect(self.import_excel)
        b2 = button("运行选中任务")
        b2.clicked.connect(self.run_selected_task)
        b3 = button("运行全部待执行")
        b3.clicked.connect(self.run_pending_tasks)
        self.pause_button = button("暂停执行", "danger")
        self.pause_button.clicked.connect(self.pause_execution)
        self.resume_button = button("继续执行", "primary")
        self.resume_button.clicked.connect(self.resume_execution)
        self.resume_button.setEnabled(False)
        for w in (b1, b2, b3, self.pause_button, self.resume_button):
            q.addWidget(w)
        q.addStretch(1)
        quick.body.addLayout(q)

        tip = QLabel(
            "执行链路：搜索源商品 → 发布相似品 → 改标题 → 替换第一张主图 → 改 SKU 名称 → "
            "发布前校验 → 提交 → 成功后删除任务记录 → 返回商品管理继续下一条"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            "background:rgba(246,248,255,190);color:#53627A;"
            "border:1px solid rgba(225,232,255,210);border-radius:10px;padding:12px;font-size:11px;"
        )
        quick.body.addWidget(tip)
        row.addWidget(quick, 2)

        run = SectionCard("当前运行", "浏览器、队列与任务状态")
        self.run_status = QLabel("未启动")
        self.run_status.setStyleSheet("font-size:22px;font-weight:700;color:#111827;")
        self.run_desc = QLabel("选择店铺并打开浏览器后，即可执行裂变任务。")
        self.run_desc.setWordWrap(True)
        self.run_desc.setStyleSheet("color:#7B8497;font-size:11px;")
        self.run_progress = QProgressBar()
        self.run_progress.setValue(0)
        run.body.addWidget(self.run_status)
        run.body.addWidget(self.run_desc)
        run.body.addWidget(self.run_progress)
        row.addWidget(run, 1)
        lay.addLayout(row)

        card = SectionCard("当前任务", "只展示未完成和失败任务；成功任务完成后自动从任务池删除。")
        self.dashboard_table = self._table(["任务编号", "源模板", "新标题", "SKU名称", "状态"])
        card.body.addWidget(self.dashboard_table)
        lay.addWidget(card, 1)
        return p

    def pause_execution(self):
        worker = self.browser_worker
        if not worker or not worker.isRunning() or not getattr(worker, "connected", False):
            QMessageBox.information(self, "当前没有可暂停任务", "请先启动店铺浏览器并执行任务。")
            return
        if getattr(worker, "paused", False):
            return
        worker.request_pause()
        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(True)
        self.run_status.setText("正在暂停")
        self.run_desc.setText("等待当前 RPA 安全步骤完成后暂停。")

    def resume_execution(self):
        worker = self.browser_worker
        if not worker or not worker.isRunning():
            QMessageBox.information(self, "无法继续", "浏览器任务线程未运行，请先重新打开当前店铺。")
            return
        if not getattr(worker, "paused", False):
            return
        worker.request_resume()
        self.pause_button.setEnabled(True)
        self.resume_button.setEnabled(False)
        self.run_status.setText("继续执行")
        self.run_desc.setText("队列已恢复，将从暂停位置继续。")

    def _pause_state_changed(self, paused: bool, message: str):
        if hasattr(self, "pause_button"):
            self.pause_button.setEnabled(not paused)
        if hasattr(self, "resume_button"):
            self.resume_button.setEnabled(paused)
        self.run_status.setText("已暂停" if paused else "执行中")
        self.run_desc.setText(message)
        self.db.add_log("INFO", message)
        self.refresh_logs()

    # ---------- browser ----------
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

        self.browser_worker = PausableBrowserWorker(
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
        self.browser_worker.start()
        self.db.add_log("INFO", f"启动店铺浏览器：{store['name']}")

    # ---------- tasks: pending / failed split ----------
    def _tasks_page(self):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        act = QHBoxLayout()
        act.setSpacing(8)
        imp = button("导入 Excel", "primary")
        imp.clicked.connect(self.import_excel)
        one = button("运行当前行")
        one.clicked.connect(self.run_selected_task)
        selected = button("运行已选择", "primary")
        selected.clicked.connect(self.run_selected_tasks)
        pending = button("运行全部待执行")
        pending.clicked.connect(self.run_pending_tasks)
        select_all = button("全选")
        select_all.clicked.connect(self.select_all_tasks)
        clear = button("取消选择")
        clear.clicked.connect(self.clear_task_selection)
        retry = button("重置失败任务")
        retry.clicked.connect(self.reset_failed)
        for w in (imp, one, selected, pending, select_all, clear, retry):
            act.addWidget(w)
        act.addStretch(1)

        self.selection_count = QLabel("已选择 0 条")
        self.selection_count.setObjectName("SelectionCount")
        act.addWidget(self.selection_count)

        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText("搜索任务编号 / 标题 / 模板")
        self.task_search.setFixedWidth(275)
        self.task_search.textChanged.connect(self.refresh_tasks)
        act.addWidget(self.task_search)
        lay.addLayout(act)

        self.task_tabs = QTabWidget()
        self.task_tabs.setDocumentMode(True)

        pending_page = QWidget()
        pl = QVBoxLayout(pending_page)
        pl.setContentsMargins(0, 8, 0, 0)
        pending_card = SectionCard(
            "待执行任务",
            "包含待执行、排队中、执行中和待确认任务。成功任务完成后自动删除。",
        )
        self.pending_table = self._table(
            ["ID", "任务编号", "源商品模板", "新标题", "SKU名称", "新首图",
             "进度", "当前步骤", "状态", "次数", "错误"]
        )
        self.pending_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pending_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pending_table.itemSelectionChanged.connect(self._update_selection_count)
        pending_card.body.addWidget(self.pending_table)
        pl.addWidget(pending_card)

        failed_page = QWidget()
        fl = QVBoxLayout(failed_page)
        fl.setContentsMargins(0, 8, 0, 0)
        failed_card = SectionCard(
            "失败任务",
            "失败任务单独保留，排查后点击“重置失败任务”即可重新回到待执行。",
        )
        self.failed_table = self._table(
            ["ID", "任务编号", "源商品模板", "新标题", "SKU名称", "新首图",
             "进度", "当前步骤", "状态", "次数", "错误"]
        )
        self.failed_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.failed_table.setSelectionMode(QAbstractItemView.SingleSelection)
        failed_card.body.addWidget(self.failed_table)
        fl.addWidget(failed_card)

        self.task_tabs.addTab(pending_page, "待执行任务")
        self.task_tabs.addTab(failed_page, "失败任务")
        lay.addWidget(self.task_tabs, 1)

        self.tasks_table = self.pending_table
        return p

    def _fill_task_table(self, table, rows):
        table.setRowCount(len(rows))
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
            table.setCellWidget(r, 8, status_pill(x["status"]))
            table.setItem(r, 9, QTableWidgetItem(str(x["attempts"])))
            table.setItem(r, 10, QTableWidgetItem(x["last_error"] or ""))
        table.resizeColumnsToContents()
        table.setColumnWidth(3, 390)
        table.setColumnWidth(10, 300)

    def refresh_tasks(self):
        if not hasattr(self, "pending_table"):
            return
        rows = self.db.tasks()
        q = self.task_search.text().strip().lower() if hasattr(self, "task_search") else ""
        if q:
            rows = [
                x for x in rows
                if q in str(x["task_code"]).lower()
                or q in str(x["new_title"]).lower()
                or q in str(x["template_name"]).lower()
            ]

        failed = [x for x in rows if str(x["status"]).strip() == "失败"]
        pending = [
            x for x in rows
            if str(x["status"]).strip() not in ("失败", "成功")
        ]
        self._fill_task_table(self.pending_table, pending)
        self._fill_task_table(self.failed_table, failed)
        self.task_tabs.setTabText(0, f"待执行任务 ({len(pending)})")
        self.task_tabs.setTabText(1, f"失败任务 ({len(failed)})")
        self._update_selection_count()

    def refresh_dashboard(self):
        rows = [x for x in self.db.tasks() if str(x["status"]).strip() != "成功"][:7]
        self.dashboard_table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [x["task_code"], x["template_name"], x["new_title"], x["sku_name"]]
            for c, v in enumerate(vals):
                self.dashboard_table.setItem(r, c, QTableWidgetItem(str(v)))
            self.dashboard_table.setCellWidget(r, 4, status_pill(x["status"]))
        self.dashboard_table.resizeColumnsToContents()
        self.dashboard_table.setColumnWidth(2, 420)

    def refresh_all(self):
        s = self.db.stats()
        self.m_total.value.setText(str(s["total"]))
        self.m_pending.value.setText(str(s["pending"]))
        self.m_success.value.setText(str(self.session_success_count))
        self.m_failed.value.setText(str(s["failed"]))
        self.refresh_dashboard()
        self.refresh_tasks()
        self.refresh_stores()
        self.refresh_templates()
        self.refresh_logs()

    # ---------- completed tasks are not persisted ----------
    def _task_done(self, tid, code, status, text):
        if status == "成功":
            self.db.add_log("INFO", text, code)
            self.db.delete_task(int(tid))
            self.session_success_count += 1
            self.run_status.setText("成功")
            self.run_desc.setText(f"{code} · {text}")
            self.run_progress.setValue(100)
            self.refresh_all()
            return

        super()._task_done(tid, code, status, text)
