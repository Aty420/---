from __future__ import annotations

import queue
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
)

from app.db import Database
from app.excel_service import import_tasks, create_sample
from app.rpa.browser import BrowserManager
from app.rpa.publisher import DouDianSimilarPublisher


class StatusDot(QWidget):
    def __init__(self, color="#22C55E", size=9, parent=None):
        super().__init__(parent); self.color = QColor(color); self.setFixedSize(size + 2, size + 2)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen); p.setBrush(self.color)
        p.drawEllipse(1, 1, self.width()-2, self.height()-2)


class MetricCard(QFrame):
    def __init__(self, title: str, value="0", hint="", parent=None):
        super().__init__(parent); self.setObjectName("Card")
        lay = QVBoxLayout(self); lay.setContentsMargins(18,16,18,16); lay.setSpacing(4)
        t=QLabel(title); t.setObjectName("MetricTitle")
        self.value=QLabel(value); self.value.setObjectName("MetricValue")
        h=QLabel(hint); h.setObjectName("MetricHint")
        lay.addWidget(t); lay.addWidget(self.value); lay.addWidget(h); self.setMinimumHeight(110)


class SectionCard(QFrame):
    def __init__(self, title: str, subtitle="", parent=None):
        super().__init__(parent); self.setObjectName("Card")
        self.body=QVBoxLayout(self); self.body.setContentsMargins(18,16,18,18); self.body.setSpacing(12)
        t=QLabel(title); t.setObjectName("SectionTitle"); self.body.addWidget(t)
        if subtitle:
            s=QLabel(subtitle); s.setObjectName("SectionSub"); s.setWordWrap(True); self.body.addWidget(s)


def button(text: str, kind="secondary"):
    b=QPushButton(text); b.setCursor(Qt.PointingHandCursor)
    b.setObjectName({"primary":"PrimaryButton","danger":"DangerButton"}.get(kind,"SecondaryButton")); return b


def badge(text: str):
    palette={
        "成功":("#ECFDF3","#027A48"), "失败":("#FEF3F2","#B42318"),
        "执行中":("#EEF4FF","#2D5BD1"), "待执行":("#F2F4F7","#475467"),
        "待确认":("#FFF7E8","#B54708"), "排队中":("#F0F5FF","#3B5CCC"), "浏览器已打开":("#ECFDF3","#027A48"),
        "未登录":("#F2F4F7","#475467")
    }
    bg,fg=palette.get(text,("#F2F4F7","#475467")); lab=QLabel(text); lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(f"background:{bg};color:{fg};border-radius:8px;padding:4px 8px;font-size:10px;font-weight:600;")
    return lab


class BrowserWorker(QThread):
    ready = Signal(str)
    info = Signal(str)
    task_step = Signal(int, str, str, int)
    task_done = Signal(int, str, str, str)
    task_error = Signal(int, str, str)

    def __init__(self, profile_dir: Path, selector_file: Path, screenshot_dir: Path, parent=None):
        super().__init__(parent)
        self.profile_dir=profile_dir; self.selector_file=selector_file; self.screenshot_dir=screenshot_dir
        self.commands=queue.Queue(); self._stop=False

    def enqueue_publish(self, task: dict, template: dict, safe_mode: bool):
        self.commands.put(("publish", task, template, safe_mode))

    def request_stop(self):
        self.commands.put(("stop", None, None, None))

    def run(self):
        browser=None
        try:
            browser=BrowserManager(self.profile_dir); page=browser.start()
            page.goto("https://fxg.jinritemai.com/", wait_until="domcontentloaded", timeout=60000)
            self.ready.emit("浏览器已打开。首次使用请在网页中人工扫码/完成安全验证。")
            while not self._stop:
                try:
                    cmd,task,template,safe_mode=self.commands.get(timeout=.25)
                except queue.Empty:
                    continue
                if cmd=="stop":
                    self._stop=True; break
                if cmd!="publish":
                    continue
                tid=int(task["id"]); code=str(task["task_code"])
                try:
                    pub=DouDianSimilarPublisher(
                        page,self.selector_file,self.screenshot_dir,
                        step_cb=lambda step,prog,tid=tid,code=code:self.task_step.emit(tid,code,step,prog)
                    )
                    status,text=pub.run(task,template,safe_mode=safe_mode)
                    self.task_done.emit(tid,code,status,text)
                except Exception as exc:
                    self.task_error.emit(tid,code,str(exc))
        except Exception as exc:
            self.ready.emit(f"浏览器启动失败：{exc}")
        finally:
            if browser:
                try: browser.stop()
                except Exception: pass


class MainWindow(QMainWindow):
    def __init__(self, root: Path):
        super().__init__(); self.root=root; self.db=Database(root/"data"/"app.db")
        self.browser_worker: BrowserWorker|None=None; self.active_store_id: int|None=None; self.current_page=0
        sample=root/"samples"/"相似品批量任务模板.xlsx"
        if not sample.exists(): create_sample(sample)

        self.setWindowTitle("DouRPA Pro · 抖店相似品批量发布")
        self.resize(1510,920); self.setMinimumSize(1220,780)
        rootw=QWidget(); rootw.setObjectName("Root"); self.setCentralWidget(rootw)
        outer=QHBoxLayout(rootw); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        content=QWidget(); cl=QVBoxLayout(content); cl.setContentsMargins(28,18,28,22); cl.setSpacing(14)
        cl.addWidget(self._topbar())
        self.stack=QStackedWidget();
        for p in [self._dashboard_page(),self._tasks_page(),self._stores_page(),self._templates_page(),self._logs_page(),self._settings_page()]:
            self.stack.addWidget(p)
        cl.addWidget(self.stack,1); outer.addWidget(content,1)
        self.refresh_all()

    # ---------- shell ----------
    def _sidebar(self):
        f=QFrame(); f.setObjectName("Sidebar"); f.setFixedWidth(238)
        lay=QVBoxLayout(f); lay.setContentsMargins(18,22,18,20); lay.setSpacing(8)
        brand=QLabel("DouRPA Pro"); brand.setObjectName("BrandName")
        sub=QLabel("SIMILAR PRODUCT PUBLISHER"); sub.setObjectName("BrandSub")
        lay.addWidget(brand); lay.addWidget(sub); lay.addSpacing(18)
        self.nav=[]
        items=[("  ◈  工作台",0),("  ▦  裂变任务",1),("  ◉  店铺管理",2),("  ◫  源商品模板",3),("  ≡  运行日志",4),("  ⚙  系统设置",5)]
        for text,idx in items:
            b=QPushButton(text); b.setObjectName("NavButton"); b.setProperty("active",idx==0); b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False,i=idx:self.switch_page(i)); lay.addWidget(b); self.nav.append(b)
        lay.addStretch(1)
        box=QFrame(); box.setStyleSheet("background:#131D30;border:1px solid #1E2A43;border-radius:12px;")
        bl=QVBoxLayout(box); bl.setContentsMargins(12,12,12,12)
        a=QLabel("只改 3 个字段"); a.setStyleSheet("color:#E5EAF3;font-weight:700;font-size:11px;")
        b=QLabel("标题 · 第一张主图 · SKU名称\n其余继承内容不主动修改")
        b.setStyleSheet("color:#7F8BA4;font-size:10px;"); bl.addWidget(a); bl.addWidget(b); lay.addWidget(box)
        return f

    def _topbar(self):
        f=QFrame(); f.setObjectName("Topbar"); f.setFixedHeight(64); lay=QHBoxLayout(f); lay.setContentsMargins(0,0,0,0)
        titles=[
            ("工作台","查看裂变任务、发布进度与当前浏览器状态"),
            ("裂变任务","批量发布相似品，只修改标题、首图与 SKU 名称"),
            ("店铺管理","每个店铺使用独立浏览器 Profile 保存登录状态"),
            ("源商品模板","保存源商品定位关键词，以后直接复用"),
            ("运行日志","失败节点会自动记录并保存全页截图"),
            ("系统设置","首次测试建议开启发布前安全停点")]
        self._titles=titles; vl=QVBoxLayout(); vl.setSpacing(2)
        self.page_title=QLabel(titles[0][0]); self.page_title.setObjectName("PageTitle")
        self.page_sub=QLabel(titles[0][1]); self.page_sub.setObjectName("PageSub")
        vl.addWidget(self.page_title); vl.addWidget(self.page_sub); lay.addLayout(vl); lay.addStretch(1)
        lay.addWidget(StatusDot()); self.engine_label=QLabel("本地 RPA 引擎就绪"); self.engine_label.setStyleSheet("color:#667085;font-size:11px;")
        lay.addWidget(self.engine_label); lay.addSpacing(10)
        b=button("打开当前店铺","primary"); b.clicked.connect(self.open_store_browser); lay.addWidget(b); return f

    # ---------- pages ----------
    def _dashboard_page(self):
        p=QWidget(); lay=QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(14)
        metrics=QHBoxLayout(); metrics.setSpacing(12)
        self.m_total=MetricCard("裂变任务","0","任务池总量"); self.m_pending=MetricCard("待处理","0","待执行 / 待确认")
        self.m_success=MetricCard("发布成功","0","检测到提交成功"); self.m_failed=MetricCard("异常","0","可重试任务")
        for m in [self.m_total,self.m_pending,self.m_success,self.m_failed]: metrics.addWidget(m)
        lay.addLayout(metrics)
        row=QHBoxLayout(); row.setSpacing(14)
        quick=SectionCard("批量发布控制台","推荐首次先运行 1 条并停在最终发布前，确认页面定位正确后再关闭安全模式。")
        q=QHBoxLayout(); b1=button("导入裂变 Excel","primary"); b1.clicked.connect(self.import_excel)
        b2=button("运行选中任务"); b2.clicked.connect(self.run_selected_task)
        b3=button("运行全部待执行"); b3.clicked.connect(self.run_pending_tasks)
        q.addWidget(b1); q.addWidget(b2); q.addWidget(b3); q.addStretch(1); quick.body.addLayout(q)
        tip=QLabel("执行链路：搜索源商品 → 发布相似品 → 改标题 → 替换第一张主图 → 改 SKU 名称 → 发布前校验 → 提交 → 识别“商品提交成功”")
        tip.setWordWrap(True); tip.setStyleSheet("background:#F6F8FF;color:#53627A;border:1px solid #E1E8FF;border-radius:10px;padding:12px;font-size:11px;")
        quick.body.addWidget(tip); row.addWidget(quick,2)
        run=SectionCard("当前运行","浏览器与任务状态")
        self.run_status=QLabel("未启动"); self.run_status.setStyleSheet("font-size:22px;font-weight:700;color:#111827;")
        self.run_desc=QLabel("选择店铺并打开浏览器后，即可执行裂变任务。"); self.run_desc.setWordWrap(True); self.run_desc.setStyleSheet("color:#7B8497;font-size:11px;")
        self.run_progress=QProgressBar(); self.run_progress.setValue(0)
        run.body.addWidget(self.run_status); run.body.addWidget(self.run_desc); run.body.addWidget(self.run_progress); row.addWidget(run,1)
        lay.addLayout(row)
        card=SectionCard("最近任务","最近导入与执行的裂变任务")
        self.dashboard_table=self._table(["任务编号","源模板","新标题","SKU名称","状态"]); card.body.addWidget(self.dashboard_table); lay.addWidget(card,1)
        return p

    def _tasks_page(self):
        p=QWidget(); lay=QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(12)
        act=QHBoxLayout(); imp=button("导入 Excel","primary"); imp.clicked.connect(self.import_excel)
        one=button("运行选中"); one.clicked.connect(self.run_selected_task); allb=button("运行全部待执行"); allb.clicked.connect(self.run_pending_tasks)
        retry=button("重置失败任务"); retry.clicked.connect(self.reset_failed)
        for b in [imp,one,allb,retry]: act.addWidget(b)
        act.addStretch(1); self.task_search=QLineEdit(); self.task_search.setPlaceholderText("搜索任务编号 / 标题 / 模板"); self.task_search.setFixedWidth(290); self.task_search.textChanged.connect(self.refresh_tasks)
        act.addWidget(self.task_search); lay.addLayout(act)
        card=SectionCard("裂变任务队列","Excel 仅需要：任务编号、源商品模板、新标题、SKU名称、新首图。")
        self.tasks_table=self._table(["ID","任务编号","源商品模板","新标题","SKU名称","新首图","进度","当前步骤","状态","次数","错误"])
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.tasks_table.setSelectionMode(QAbstractItemView.SingleSelection)
        card.body.addWidget(self.tasks_table); lay.addWidget(card,1); return p

    def _stores_page(self):
        p=QWidget(); lay=QVBoxLayout(p); lay.setContentsMargins(0,0,0,0)
        card=SectionCard("店铺 Profile","首次人工扫码登录；登录状态保存在本地独立 Profile，不尝试绕过验证码或安全验证。")
        form=QHBoxLayout(); self.store_name=QLineEdit(); self.store_name.setPlaceholderText("例如：心相印店铺A")
        add=button("新增店铺","primary"); add.clicked.connect(self.add_store); login=button("打开选中店铺"); login.clicked.connect(self.open_store_browser)
        form.addWidget(self.store_name,1); form.addWidget(add); form.addWidget(login); card.body.addLayout(form)
        self.store_table=self._table(["ID","店铺名称","Profile目录","状态","最后打开"]); self.store_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        card.body.addWidget(self.store_table); lay.addWidget(card,1); return p

    def _templates_page(self):
        p=QWidget(); lay=QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(12)
        formcard=SectionCard("新增 / 更新源商品模板","模板只保存“去哪家店、用什么关键词找到哪个源商品”，不会复制整套属性。")
        r1=QHBoxLayout(); self.tpl_name=QLineEdit(); self.tpl_name.setPlaceholderText("模板名称，例如：心相印悬挂抽纸18提")
        self.tpl_store=QComboBox(); self.tpl_mode=QComboBox(); self.tpl_mode.addItems(["商品ID/关键词","商品ID","商品标题"])
        r1.addWidget(self.tpl_name,2); r1.addWidget(self.tpl_store,1); r1.addWidget(self.tpl_mode,1); formcard.body.addLayout(r1)
        r2=QHBoxLayout(); self.tpl_keyword=QLineEdit(); self.tpl_keyword.setPlaceholderText("源商品搜索关键词 / 商品ID（建议尽量精确）")
        self.tpl_note=QLineEdit(); self.tpl_note.setPlaceholderText("备注，可留空")
        save=button("保存模板","primary"); save.clicked.connect(self.save_template)
        r2.addWidget(self.tpl_keyword,2); r2.addWidget(self.tpl_note,1); r2.addWidget(save); formcard.body.addLayout(r2); lay.addWidget(formcard)
        listcard=SectionCard("模板库","同一个源链接可以重复生成大量不同标题、首图和 SKU 名称的相似品任务。")
        self.tpl_table=self._table(["ID","模板名称","店铺","搜索方式","源商品关键词/ID","备注"]); self.tpl_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        delb=button("删除选中模板","danger"); delb.clicked.connect(self.delete_template); listcard.body.addWidget(self.tpl_table); listcard.body.addWidget(delb,0,Qt.AlignLeft)
        lay.addWidget(listcard,1); return p

    def _logs_page(self):
        p=QWidget(); lay=QVBoxLayout(p); lay.setContentsMargins(0,0,0,0)
        c=SectionCard("运行日志","RPA 页面结构变化时，优先查看失败节点、截图和 config/selectors.json。")
        self.log_edit=QPlainTextEdit(); self.log_edit.setReadOnly(True); c.body.addWidget(self.log_edit)
        b=button("刷新日志"); b.clicked.connect(self.refresh_logs); c.body.addWidget(b,0,Qt.AlignLeft); lay.addWidget(c,1); return p

    def _settings_page(self):
        p=QWidget(); lay=QVBoxLayout(p); lay.setContentsMargins(0,0,0,0); lay.setSpacing(12)
        c=SectionCard("执行策略","首次校准时建议开启安全停点。确认标题、第一张主图和 SKU 都替换正确后，再关闭它进行自动提交。")
        self.safe_mode=QCheckBox("首次测试模式：停在最终发布前，不自动点击发布商品"); self.safe_mode.setChecked(True)
        c.body.addWidget(self.safe_mode)
        path=QLineEdit(str(self.root/"config"/"selectors.json")); path.setReadOnly(True); c.body.addWidget(QLabel("页面选择器配置")); c.body.addWidget(path)
        warn=QLabel("软件不会绕过扫码、验证码、滑块或其他安全校验。遇到平台验证时，请在浏览器中人工完成，然后继续任务。")
        warn.setWordWrap(True); warn.setStyleSheet("background:#FFF9ED;color:#8A5B10;border:1px solid #FCE6B0;border-radius:10px;padding:12px;")
        c.body.addWidget(warn); lay.addWidget(c); lay.addStretch(1); return p

    def _table(self, headers):
        t=QTableWidget(0,len(headers)); t.setHorizontalHeaderLabels(headers); t.verticalHeader().setVisible(False); t.setShowGrid(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers); t.horizontalHeader().setStretchLastSection(True); return t

    # ---------- refresh ----------
    def switch_page(self,idx):
        self.current_page=idx; self.stack.setCurrentIndex(idx); title,sub=self._titles[idx]; self.page_title.setText(title); self.page_sub.setText(sub)
        for i,b in enumerate(self.nav): b.setProperty("active",i==idx); b.style().unpolish(b); b.style().polish(b)
        self.refresh_all()

    def refresh_all(self):
        s=self.db.stats(); self.m_total.value.setText(str(s["total"])); self.m_pending.value.setText(str(s["pending"])); self.m_success.value.setText(str(s["success"])); self.m_failed.value.setText(str(s["failed"]))
        self.refresh_dashboard(); self.refresh_tasks(); self.refresh_stores(); self.refresh_templates(); self.refresh_logs()

    def refresh_dashboard(self):
        rows=self.db.tasks()[:7]; self.dashboard_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=[x["task_code"],x["template_name"],x["new_title"],x["sku_name"]]
            for c,v in enumerate(vals): self.dashboard_table.setItem(r,c,QTableWidgetItem(str(v)))
            self.dashboard_table.setCellWidget(r,4,badge(x["status"]))
        self.dashboard_table.resizeColumnsToContents(); self.dashboard_table.setColumnWidth(2,420)

    def refresh_tasks(self):
        rows=self.db.tasks(); q=self.task_search.text().strip().lower() if hasattr(self,"task_search") else ""
        if q: rows=[x for x in rows if q in str(x["task_code"]).lower() or q in str(x["new_title"]).lower() or q in str(x["template_name"]).lower()]
        self.tasks_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=[x["id"],x["task_code"],x["template_name"],x["new_title"],x["sku_name"],Path(x["cover_image"]).name]
            for c,v in enumerate(vals): self.tasks_table.setItem(r,c,QTableWidgetItem(str(v)))
            prog=QProgressBar(); prog.setValue(int(x["progress"])); self.tasks_table.setCellWidget(r,6,prog)
            self.tasks_table.setItem(r,7,QTableWidgetItem(x["current_step"] or "等待")); self.tasks_table.setCellWidget(r,8,badge(x["status"]))
            self.tasks_table.setItem(r,9,QTableWidgetItem(str(x["attempts"]))); self.tasks_table.setItem(r,10,QTableWidgetItem(x["last_error"] or ""))
        self.tasks_table.resizeColumnsToContents(); self.tasks_table.setColumnWidth(3,380); self.tasks_table.setColumnWidth(10,300)

    def refresh_stores(self):
        rows=self.db.stores(); self.store_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=[x["id"],x["name"],x["profile_dir"]]
            for c,v in enumerate(vals): self.store_table.setItem(r,c,QTableWidgetItem(str(v)))
            self.store_table.setCellWidget(r,3,badge(x["status"])); self.store_table.setItem(r,4,QTableWidgetItem(x["last_login"] or "-"))
        self.store_table.resizeColumnsToContents(); self.store_table.setColumnWidth(2,430)
        # template store dropdown
        if hasattr(self,"tpl_store"):
            current=self.tpl_store.currentData(); self.tpl_store.blockSignals(True); self.tpl_store.clear(); self.tpl_store.addItem("未指定店铺",None)
            for s in rows: self.tpl_store.addItem(s["name"],s["id"])
            idx=self.tpl_store.findData(current); self.tpl_store.setCurrentIndex(idx if idx>=0 else 0); self.tpl_store.blockSignals(False)

    def refresh_templates(self):
        if not hasattr(self,"tpl_table"): return
        rows=self.db.templates(); self.tpl_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=[x["id"],x["name"],x["store_name"] or "-",x["search_mode"],x["source_keyword"],x["note"]]
            for c,v in enumerate(vals): self.tpl_table.setItem(r,c,QTableWidgetItem(str(v)))
        self.tpl_table.resizeColumnsToContents(); self.tpl_table.setColumnWidth(4,360)

    def refresh_logs(self):
        if not hasattr(self,"log_edit"): return
        lines=[f'[{x["created_at"]}] {x["level"]:<5} {x["product_code"]:<14} {x["message"]}' for x in reversed(self.db.logs(500))]
        self.log_edit.setPlainText("\n".join(lines) if lines else "暂无运行日志")

    # ---------- actions ----------
    def import_excel(self):
        path,_=QFileDialog.getOpenFileName(self,"选择相似品任务 Excel",str(self.root/"samples"),"Excel (*.xlsx)")
        if not path: return
        try:
            rows=import_tasks(Path(path)); missing=sorted({x["template_name"] for x in rows if not self.db.template(x["template_name"])})
            if missing:
                QMessageBox.warning(self,"模板不存在","以下源商品模板尚未创建：\n\n"+"\n".join(missing)+"\n\n请先在“源商品模板”中保存后再导入。")
                return
            self.db.upsert_tasks(rows); self.db.add_log("INFO",f"导入裂变任务 {len(rows)} 条"); self.refresh_all()
            QMessageBox.information(self,"导入完成",f"已导入/更新 {len(rows)} 条相似品任务。")
        except Exception as exc: QMessageBox.critical(self,"导入失败",str(exc))

    def add_store(self):
        name=self.store_name.text().strip()
        if not name: QMessageBox.warning(self,"提示","请输入店铺名称。"); return
        safe="".join(ch for ch in name if ch.isalnum() or ch in "_-") or "shop"
        self.db.add_store(name,str(self.root/"data"/"profiles"/safe)); self.store_name.clear(); self.refresh_all()

    def save_template(self):
        name=self.tpl_name.text().strip(); keyword=self.tpl_keyword.text().strip()
        if not name or not keyword: QMessageBox.warning(self,"信息不完整","模板名称和源商品关键词/ID不能为空。"); return
        self.db.save_template(name,self.tpl_store.currentData(),self.tpl_mode.currentText(),keyword,self.tpl_note.text().strip())
        self.db.add_log("INFO",f"保存源商品模板：{name}"); self.tpl_name.clear(); self.tpl_keyword.clear(); self.tpl_note.clear(); self.refresh_all()

    def delete_template(self):
        r=self.tpl_table.currentRow()
        if r<0: return
        item=self.tpl_table.item(r,0)
        if item and QMessageBox.question(self,"删除模板","确认删除选中的源商品模板？")==QMessageBox.Yes:
            self.db.delete_template(int(item.text())); self.refresh_all()

    def _selected_store(self):
        stores=self.db.stores(); r=self.store_table.currentRow() if hasattr(self,"store_table") else -1
        if 0<=r<len(stores): return stores[r]
        return stores[0] if stores else None

    def open_store_browser(self):
        store=self._selected_store()
        if not store:
            self.db.add_store("默认店铺",str(self.root/"data"/"profiles"/"default")); store=self.db.stores()[0]; self.refresh_all()
        if self.browser_worker and self.browser_worker.isRunning():
            QMessageBox.information(self,"浏览器已运行","当前浏览器 Profile 已经打开。关闭软件后可切换到其他店铺 Profile。"); return
        self.active_store_id=int(store["id"]); self.run_status.setText("正在启动浏览器"); self.run_desc.setText(f"店铺：{store['name']}"); self.run_progress.setValue(3)
        self.browser_worker=BrowserWorker(Path(store["profile_dir"]),self.root/"config"/"selectors.json",self.root/"screenshots",self)
        self.browser_worker.ready.connect(lambda msg,sid=int(store["id"]):self._browser_ready(sid,msg))
        self.browser_worker.task_step.connect(self._task_step); self.browser_worker.task_done.connect(self._task_done); self.browser_worker.task_error.connect(self._task_error)
        self.browser_worker.start(); self.db.add_log("INFO",f"启动店铺浏览器：{store['name']}")

    def _browser_ready(self,store_id,msg):
        if msg.startswith("浏览器启动失败"):
            self.run_status.setText("浏览器启动失败"); self.run_desc.setText(msg); self.engine_label.setText("RPA 引擎异常"); self.db.add_log("ERROR",msg); return
        self.db.update_store_status(store_id,"浏览器已打开"); self.run_status.setText("浏览器已打开"); self.run_desc.setText(msg); self.engine_label.setText("浏览器已连接"); self.run_progress.setValue(5); self.refresh_all()

    def _selected_task(self):
        r=self.tasks_table.currentRow() if hasattr(self,"tasks_table") else -1
        if r>=0:
            item=self.tasks_table.item(r,0)
            if item: return self.db.task(int(item.text()))
        rows=self.db.tasks(); return rows[0] if rows else None

    def _validate_for_run(self,task):
        template=self.db.template(task["template_name"])
        if not template: raise ValueError(f"源商品模板不存在：{task['template_name']}")
        if not Path(task["cover_image"]).exists(): raise ValueError(f"新首图不存在：{task['cover_image']}")
        if template["store_id"] and self.active_store_id and int(template["store_id"])!=int(self.active_store_id):
            raise ValueError(f"模板绑定店铺“{template['store_name']}”，与当前打开的店铺不一致。")
        return template

    def _ensure_browser(self):
        if not self.browser_worker or not self.browser_worker.isRunning():
            QMessageBox.information(self,"先打开店铺","请先在“店铺管理”选择目标店铺并打开浏览器，确认已登录后再执行任务。")
            return False
        return True

    def _queue_task(self,task):
        template=self._validate_for_run(task); self.db.update_task(task["id"],status="排队中",progress=1,step="已加入队列",error="",inc_attempt=True)
        self.browser_worker.enqueue_publish(dict(task),dict(template),self.safe_mode.isChecked())

    def run_selected_task(self):
        if not self._ensure_browser(): return
        task=self._selected_task()
        if not task: QMessageBox.information(self,"暂无任务","请先创建源商品模板并导入裂变 Excel。"); return
        try: self._queue_task(task); self.refresh_all(); self.run_status.setText(f"处理中 · {task['task_code']}")
        except Exception as exc: QMessageBox.critical(self,"无法执行",str(exc))

    def run_pending_tasks(self):
        if not self._ensure_browser(): return
        if self.safe_mode.isChecked():
            QMessageBox.information(self,"首次测试模式","安全停点开启时请一次只运行 1 条任务。确认页面定位正确后，关闭安全停点再启动批量发布。")
            return
        rows=self.db.tasks(("待执行",))
        if not rows: QMessageBox.information(self,"没有待执行任务","当前没有状态为“待执行”的任务。"); return
        queued=0; errors=[]
        for t in rows:
            try: self._queue_task(t); queued+=1
            except Exception as exc: errors.append(f"{t['task_code']}: {exc}")
        self.refresh_all(); self.run_status.setText(f"批量队列 · {queued} 条"); self.run_desc.setText("任务会按顺序逐条执行，单条失败不会修改其他任务。")
        if errors: QMessageBox.warning(self,"部分任务未加入队列","\n".join(errors[:12]))

    def reset_failed(self):
        self.db.reset_failed(); self.db.add_log("INFO","已重置全部失败任务"); self.refresh_all()

    def _task_step(self,tid,code,step,progress):
        self.db.update_task(tid,status="执行中",progress=progress,step=step); self.db.add_log("INFO",step,code)
        self.run_status.setText(f"{code} · {step}"); self.run_desc.setText("RPA 正按录制流程执行"); self.run_progress.setValue(progress); self.refresh_tasks()

    def _task_done(self,tid,code,status,text):
        self.db.update_task(tid,status=status,progress=100 if status=="成功" else 92,step="完成" if status=="成功" else "等待人工确认",error="",result=text)
        self.db.add_log("INFO",text,code); self.run_status.setText(status); self.run_desc.setText(f"{code} · {text}"); self.run_progress.setValue(100 if status=="成功" else 92); self.refresh_all()
        if status=="待确认": QMessageBox.information(self,"已到安全停点",f"{code}\n\n{text}\n\n请在浏览器确认页面无误。")

    def _task_error(self,tid,code,msg):
        short=msg.splitlines()[0] if msg else "未知错误"; self.db.update_task(tid,status="失败",progress=0,step="执行失败",error=short)
        self.db.add_log("ERROR",short,code); self.run_status.setText("执行异常"); self.run_desc.setText(f"{code} · {short}"); self.run_progress.setValue(0); self.refresh_all()

    def closeEvent(self,event):
        if self.browser_worker and self.browser_worker.isRunning(): self.browser_worker.request_stop(); self.browser_worker.wait(5000)
        event.accept()
