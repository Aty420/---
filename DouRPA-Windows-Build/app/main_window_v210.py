from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QProgressBar, QTableWidgetItem, QVBoxLayout, QWidget
)

from app.main_window import MetricCard, SectionCard, StatusDot, button
from app.main_window_v209 import MainWindow as V209MainWindow


_TASK_STATUS = {
    "待执行": ("待执行", "#64748B", "#F1F5F9", "#E2E8F0"),
    "排队中": ("排队中", "#3154D9", "#EEF3FF", "#D9E4FF"),
    "执行中": ("执行中", "#2563EB", "#EAF2FF", "#CFE0FF"),
    "待确认": ("待确认", "#A15C00", "#FFF7E6", "#FDE3AF"),
    "成功": ("成功", "#087A4B", "#EAFBF3", "#C9F2DC"),
    "失败": ("失败", "#C4322B", "#FFF0EF", "#FFD6D2"),
}

_STORE_STATUS = {
    "未登录": ("未登录", "#64748B", "#F1F5F9", "#E2E8F0"),
    "浏览器已打开": ("已连接", "#087A4B", "#EAFBF3", "#C9F2DC"),
    "已连接": ("已连接", "#087A4B", "#EAFBF3", "#C9F2DC"),
    "连接已断开": ("已断开", "#C4322B", "#FFF0EF", "#FFD6D2"),
    "浏览器连接已断开": ("已断开", "#C4322B", "#FFF0EF", "#FFD6D2"),
}


def _normalize_status(raw, mapping):
    text = str(raw or "").strip().replace("\x00", "")
    if text in mapping:
        return text
    # 防止数据库里带前后缀或旧日志拼接；只接受明确已知状态。
    for key in mapping:
        if key and key in text:
            return key
    return ""


def status_pill(raw, store=False):
    mapping = _STORE_STATUS if store else _TASK_STATUS
    key = _normalize_status(raw, mapping)
    if key:
        text, fg, bg, border = mapping[key]
    else:
        # 未识别的乱码状态不直接显示，避免 UI 出现乱码。
        text, fg, bg, border = ("未知状态", "#7C3AED", "#F5F0FF", "#E5D8FF")
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    lab.setTextFormat(Qt.PlainText)
    lab.setMinimumWidth(76)
    lab.setMaximumHeight(28)
    font = QFont("Microsoft YaHei UI", 9)
    font.setWeight(QFont.DemiBold)
    lab.setFont(font)
    lab.setStyleSheet(
        f"QLabel{{background:{bg};color:{fg};border:1px solid {border};"
        "border-radius:10px;padding:4px 10px;}}"
    )
    return lab


class MainWindow(V209MainWindow):
    """V2.1.0 UI/UX upgrade.

    RPA execution remains inherited from V2.0.9. This class only adds:
    - store deletion
    - multi-select batch execution
    - normalized status display
    - redesigned glass UI shell
    """

    def __init__(self, root: Path):
        super().__init__(root)
        self.setWindowTitle("DouRPA Pro · 抖店相似品批量发布")
        self._install_glass_shadows()

    # ---------- visual shell ----------
    def _sidebar(self):
        panel = QFrame()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(246)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 22, 18, 20)
        lay.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(11)
        icon = QLabel()
        icon.setObjectName("BrandIcon")
        icon.setFixedSize(46, 46)
        pix = QApplication.windowIcon().pixmap(42, 42)
        icon.setPixmap(pix)
        icon.setAlignment(Qt.AlignCenter)

        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand = QLabel("DouRPA Pro")
        brand.setObjectName("BrandName")
        sub = QLabel("AUTOMATION STUDIO")
        sub.setObjectName("BrandSub")
        brand_text.addWidget(brand)
        brand_text.addWidget(sub)
        brand_row.addWidget(icon)
        brand_row.addLayout(brand_text, 1)
        lay.addLayout(brand_row)

        divider = QFrame()
        divider.setObjectName("SideDivider")
        divider.setFixedHeight(1)
        lay.addSpacing(12)
        lay.addWidget(divider)
        lay.addSpacing(10)

        self.nav = []
        items = [
            ("工作台", 0),
            ("裂变任务", 1),
            ("店铺管理", 2),
            ("源商品模板", 3),
            ("运行日志", 4),
            ("系统设置", 5),
        ]
        for order, (text, idx) in enumerate(items, start=1):
            b = QPushButton(f"{order:02d}    {text}")
            b.setObjectName("NavButton")
            b.setProperty("active", idx == 0)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=idx: self.switch_page(i))
            lay.addWidget(b)
            self.nav.append(b)

        lay.addStretch(1)

        footer = QFrame()
        footer.setObjectName("SidebarMiniCard")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(13, 12, 13, 12)
        fl.setSpacing(4)
        a = QLabel("核心执行范围")
        a.setObjectName("SidebarMiniTitle")
        b = QLabel("标题 · 第一张主图 · SKU名称")
        b.setObjectName("SidebarMiniText")
        c = QLabel("其余商品信息保持继承")
        c.setObjectName("SidebarMiniSub")
        fl.addWidget(a)
        fl.addWidget(b)
        fl.addWidget(c)
        lay.addWidget(footer)
        return panel

    def _topbar(self):
        f = QFrame()
        f.setObjectName("Topbar")
        f.setFixedHeight(72)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(4, 0, 0, 0)

        titles = [
            ("工作台", "任务总览、浏览器连接与发布进度"),
            ("裂变任务", "批量管理相似品发布任务"),
            ("店铺管理", "独立店铺 Profile 与登录状态"),
            ("源商品模板", "管理源商品定位与复用模板"),
            ("运行日志", "查看自动化节点、错误与恢复信息"),
            ("系统设置", "控制发布安全停点与页面配置"),
        ]
        self._titles = titles

        vl = QVBoxLayout()
        vl.setSpacing(2)
        self.page_title = QLabel(titles[0][0])
        self.page_title.setObjectName("PageTitle")
        self.page_sub = QLabel(titles[0][1])
        self.page_sub.setObjectName("PageSub")
        vl.addWidget(self.page_title)
        vl.addWidget(self.page_sub)
        lay.addLayout(vl)
        lay.addStretch(1)

        live = QFrame()
        live.setObjectName("ConnectionPill")
        ll = QHBoxLayout(live)
        ll.setContentsMargins(12, 7, 12, 7)
        ll.setSpacing(7)
        ll.addWidget(StatusDot("#18B26B", 8))
        self.engine_label = QLabel("RPA 引擎就绪")
        self.engine_label.setObjectName("EngineStatus")
        ll.addWidget(self.engine_label)
        lay.addWidget(live)
        lay.addSpacing(8)

        b = button("打开当前店铺", "primary")
        b.clicked.connect(self.open_store_browser)
        lay.addWidget(b)
        return f

    def _install_glass_shadows(self):
        for frame in self.findChildren(QFrame):
            if frame.objectName() != "Card":
                continue
            effect = QGraphicsDropShadowEffect(frame)
            effect.setBlurRadius(34)
            effect.setOffset(0, 9)
            effect.setColor(QColor(41, 61, 94, 28))
            frame.setGraphicsEffect(effect)

    # ---------- tasks ----------
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

        card = SectionCard(
            "裂变任务队列",
            "支持 Ctrl / Shift 多选，也可以先点“全选”，再执行已选择任务。成功任务不会被批量重复发布。",
        )
        self.tasks_table = self._table(
            ["ID", "任务编号", "源商品模板", "新标题", "SKU名称", "新首图",
             "进度", "当前步骤", "状态", "次数", "错误"]
        )
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tasks_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tasks_table.itemSelectionChanged.connect(self._update_selection_count)
        card.body.addWidget(self.tasks_table)
        lay.addWidget(card, 1)
        return p

    def select_all_tasks(self):
        self.tasks_table.selectAll()
        self._update_selection_count()

    def clear_task_selection(self):
        self.tasks_table.clearSelection()
        self._update_selection_count()

    def _update_selection_count(self):
        if not hasattr(self, "selection_count") or not hasattr(self, "tasks_table"):
            return
        rows = self.tasks_table.selectionModel().selectedRows()
        self.selection_count.setText(f"已选择 {len(rows)} 条")

    def run_selected_tasks(self):
        if not self._ensure_browser():
            return
        rows = sorted({idx.row() for idx in self.tasks_table.selectionModel().selectedRows()})
        if not rows:
            QMessageBox.information(self, "未选择任务", "请先在裂变任务表格中选择一条或多条任务。")
            return

        tasks = []
        for r in rows:
            item = self.tasks_table.item(r, 0)
            if item:
                task = self.db.task(int(item.text()))
                if task:
                    tasks.append(task)

        actionable = []
        skipped = []
        for task in tasks:
            status = _normalize_status(task["status"], _TASK_STATUS)
            if status in ("成功", "执行中", "排队中", "待确认"):
                skipped.append(f"{task['task_code']}（{status or '未知状态'}）")
                continue
            actionable.append(task)

        if not actionable:
            QMessageBox.information(
                self, "没有可执行任务",
                "选中的任务均处于成功、执行中、排队中或待确认状态，为避免重复发布未加入队列。"
            )
            return

        if self.safe_mode.isChecked() and len(actionable) > 1:
            QMessageBox.information(
                self, "安全停点已开启",
                "批量选定执行前请先关闭“首次测试模式”。安全模式下建议一次只运行 1 条任务。"
            )
            return

        queued = 0
        errors = []
        for task in actionable:
            try:
                self._queue_task(task)
                queued += 1
            except Exception as exc:
                errors.append(f"{task['task_code']}: {exc}")

        self.refresh_all()
        self.run_status.setText(f"选定批量队列 · {queued} 条")
        self.run_desc.setText("已选择的任务将按顺序逐条执行。")
        parts = []
        if skipped:
            parts.append("已跳过：\n" + "\n".join(skipped[:12]))
        if errors:
            parts.append("未加入队列：\n" + "\n".join(errors[:12]))
        if parts:
            QMessageBox.information(self, "批量选择结果", "\n\n".join(parts))

    # ---------- stores ----------
    def _stores_page(self):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 0, 0, 0)

        card = SectionCard(
            "店铺 Profile",
            "每个店铺使用独立浏览器 Profile 保存登录状态。删除店铺记录不会删除已导入任务。",
        )
        form = QHBoxLayout()
        form.setSpacing(8)
        self.store_name = QLineEdit()
        self.store_name.setPlaceholderText("例如：心相印店铺A")
        add = button("新增店铺", "primary")
        add.clicked.connect(self.add_store)
        login = button("打开选中店铺")
        login.clicked.connect(self.open_store_browser)
        delete = button("删除选中店铺", "danger")
        delete.clicked.connect(self.delete_selected_store)
        form.addWidget(self.store_name, 1)
        form.addWidget(add)
        form.addWidget(login)
        form.addWidget(delete)
        card.body.addLayout(form)

        self.store_table = self._table(["ID", "店铺名称", "Profile目录", "状态", "最后打开"])
        self.store_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.store_table.setSelectionMode(QAbstractItemView.SingleSelection)
        card.body.addWidget(self.store_table)
        lay.addWidget(card, 1)
        return p

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

        if (
            self.active_store_id == store_id
            and self.browser_worker
            and self.browser_worker.isRunning()
        ):
            QMessageBox.warning(
                self, "店铺正在使用",
                "当前店铺浏览器仍在运行。请先关闭 DouRPA/当前浏览器后，再删除这个店铺。"
            )
            return

        answer = QMessageBox.question(
            self,
            "删除店铺",
            f"确认从 DouRPA 删除店铺“{store['name']}”？\n\n"
            "关联的源商品模板会自动解除店铺绑定；任务数据不会删除。\n"
            "本地浏览器 Profile 登录缓存会保留，避免误删登录数据。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.db.delete_store(store_id)
        if self.active_store_id == store_id:
            self.active_store_id = None
        self.db.add_log("INFO", f"删除店铺：{store['name']}")
        self.refresh_all()

    # ---------- normalized status rendering ----------
    def refresh_dashboard(self):
        rows = self.db.tasks()[:7]
        self.dashboard_table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [x["task_code"], x["template_name"], x["new_title"], x["sku_name"]]
            for c, v in enumerate(vals):
                self.dashboard_table.setItem(r, c, QTableWidgetItem(str(v)))
            self.dashboard_table.setCellWidget(r, 4, status_pill(x["status"]))
        self.dashboard_table.resizeColumnsToContents()
        self.dashboard_table.setColumnWidth(2, 420)

    def refresh_tasks(self):
        rows = self.db.tasks()
        q = self.task_search.text().strip().lower() if hasattr(self, "task_search") else ""
        if q:
            rows = [
                x for x in rows
                if q in str(x["task_code"]).lower()
                or q in str(x["new_title"]).lower()
                or q in str(x["template_name"]).lower()
            ]

        self.tasks_table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [
                x["id"], x["task_code"], x["template_name"], x["new_title"],
                x["sku_name"], Path(x["cover_image"]).name
            ]
            for c, v in enumerate(vals):
                self.tasks_table.setItem(r, c, QTableWidgetItem(str(v)))

            prog = QProgressBar()
            prog.setValue(int(x["progress"]))
            self.tasks_table.setCellWidget(r, 6, prog)
            self.tasks_table.setItem(r, 7, QTableWidgetItem(x["current_step"] or "等待"))
            self.tasks_table.setCellWidget(r, 8, status_pill(x["status"]))
            self.tasks_table.setItem(r, 9, QTableWidgetItem(str(x["attempts"])))
            self.tasks_table.setItem(r, 10, QTableWidgetItem(x["last_error"] or ""))

        self.tasks_table.resizeColumnsToContents()
        self.tasks_table.setColumnWidth(3, 390)
        self.tasks_table.setColumnWidth(10, 300)
        self._update_selection_count()

    def refresh_stores(self):
        rows = self.db.stores()
        self.store_table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [x["id"], x["name"], x["profile_dir"]]
            for c, v in enumerate(vals):
                self.store_table.setItem(r, c, QTableWidgetItem(str(v)))
            self.store_table.setCellWidget(r, 3, status_pill(x["status"], store=True))
            self.store_table.setItem(r, 4, QTableWidgetItem(x["last_login"] or "-"))

        self.store_table.resizeColumnsToContents()
        self.store_table.setColumnWidth(2, 430)

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
