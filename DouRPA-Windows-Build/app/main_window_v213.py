from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from app.main_window import MetricCard, SectionCard, button
from app.main_window_v212 import MainWindow as V212MainWindow


class MainWindow(V212MainWindow):
    """V2.1.3: add explicit End Run control and definitive browser-session cleanup.

    All publishing, pause/resume, store/cache and UI behavior from V2.1.2 is preserved.
    """

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
            "任务执行中可随时暂停；当前网页动作完成后停在安全步骤边界，继续后从原位置执行。",
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
        self.end_run_button = button("结束运行", "danger")
        self.end_run_button.setEnabled(False)
        self.end_run_button.clicked.connect(self.end_current_run)
        run.body.addWidget(self.run_status)
        run.body.addWidget(self.run_desc)
        run.body.addWidget(self.run_progress)
        run.body.addWidget(self.end_run_button)
        row.addWidget(run, 1)
        lay.addLayout(row)

        card = SectionCard("当前任务", "只展示未完成和失败任务；成功任务完成后自动从任务池删除。")
        self.dashboard_table = self._table(["任务编号", "源模板", "新标题", "SKU名称", "状态"])
        card.body.addWidget(self.dashboard_table)
        lay.addWidget(card, 1)
        return p

    def _set_end_run_enabled(self, enabled: bool):
        if hasattr(self, "end_run_button"):
            self.end_run_button.setEnabled(bool(enabled))

    def _browser_ready(self, store_id, msg):
        super()._browser_ready(store_id, msg)
        if not str(msg).startswith("浏览器启动失败"):
            self._set_end_run_enabled(True)

    def _browser_closed(self, message: str):
        super()._browser_closed(message)
        self._set_end_run_enabled(False)
        # Worker 已结束后释放对象引用，下一次打开其他店铺不再受旧 Worker 状态影响。
        worker = self.browser_worker
        if not worker or not worker.isRunning():
            self.browser_worker = None

    def _connection_state(self, connected: bool, msg: str):
        super()._connection_state(connected, msg)
        if connected:
            self._set_end_run_enabled(True)
        elif "浏览器已关闭" in str(msg):
            self._set_end_run_enabled(False)

    def open_store_browser(self):
        previous = self.browser_worker
        super().open_store_browser()
        worker = self.browser_worker
        # 连接 QThread.finished 作为最后一道兜底：无论人工关闭、主动结束还是线程异常退出，
        # UI 都会释放当前店铺运行状态。
        if worker is not None and worker is not previous:
            try:
                worker.finished.connect(lambda w=worker: self._worker_finished_cleanup(w))
            except Exception:
                pass

    def _worker_finished_cleanup(self, worker):
        # 忽略已经被新 Worker 替换后的旧 finished 信号。
        if self.browser_worker is not worker:
            return
        store_id = self.active_store_id
        if store_id:
            try:
                self.db.update_store_status(store_id, "浏览器已关闭", touch_login=False)
            except Exception:
                pass
        self.active_store_id = None
        self.browser_worker = None
        self.engine_label.setText("浏览器已关闭")
        self.run_status.setText("浏览器已关闭")
        self.run_desc.setText("当前店铺运行已结束，可直接选择并打开其他店铺。")
        self.run_progress.setValue(0)
        self._set_end_run_enabled(False)
        if hasattr(self, "pause_button"):
            self.pause_button.setEnabled(False)
        if hasattr(self, "resume_button"):
            self.resume_button.setEnabled(False)
        self.refresh_all()

    def end_current_run(self):
        """Explicitly terminate the current store/browser run without closing DouRPA."""
        worker = self.browser_worker
        if not worker or not worker.isRunning():
            self._worker_finished_cleanup(worker) if worker else None
            self.run_status.setText("浏览器已关闭")
            self.run_desc.setText("当前没有正在运行的店铺浏览器，可直接选择其他店铺。")
            self._set_end_run_enabled(False)
            return

        active = self.db.store(self.active_store_id) if self.active_store_id else None
        active_name = active["name"] if active else "当前店铺"

        answer = QMessageBox.question(
            self,
            "结束运行",
            f"确认结束“{active_name}”当前运行？\n\n"
            "• 当前店铺浏览器会由 DouRPA 主动关闭\n"
            "• 排队中任务会恢复为待执行\n"
            "• 如果有正在执行的任务，会标记为失败，避免自动重跑造成重复发布\n"
            "• 结束后无需关闭软件，可立即切换并打开其他店铺",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.run_status.setText("正在结束运行")
        self.run_desc.setText("正在关闭当前店铺浏览器并释放运行状态…")
        self._set_end_run_enabled(False)

        # 先修正任务状态，再关闭 Worker，避免正在运行/排队任务永远留在错误状态。
        try:
            self.db.end_runtime_tasks()
        except Exception:
            pass

        try:
            worker.request_stop()
            finished = worker.wait(8000)
        except Exception:
            finished = False

        if not finished and worker.isRunning():
            self._set_end_run_enabled(True)
            self.run_status.setText("结束运行失败")
            self.run_desc.setText("浏览器线程暂未完全结束，请稍等几秒后再次点击“结束运行”。")
            QMessageBox.warning(
                self,
                "尚未完全结束",
                "当前浏览器线程仍在收尾。为避免损坏店铺登录 Profile，没有强制终止进程。\n\n"
                "请等待几秒后再次点击“结束运行”。",
            )
            self.refresh_all()
            return

        # finished 信号通常会自动进入 cleanup；这里再执行一次幂等清理，确保 UI 立即更新。
        if self.browser_worker is worker:
            self._worker_finished_cleanup(worker)
        self.db.add_log("INFO", f"用户主动结束店铺运行：{active_name}")
        self.refresh_all()
