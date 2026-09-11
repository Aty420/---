APP_STYLESHEET = r"""
* {
    font-family: "Microsoft YaHei UI", "Segoe UI";
    outline: none;
}
QMainWindow, QWidget#Root {
    color: #182033;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #F2F6FF,
        stop:0.38 #F7F5FF,
        stop:0.72 #EEF8FA,
        stop:1 #F8FAFF
    );
}
QFrame#Sidebar {
    background: qlineargradient(
        x1:0, y1:0, x2:0.85, y2:1,
        stop:0 rgba(12, 20, 38, 250),
        stop:0.55 rgba(17, 29, 54, 248),
        stop:1 rgba(23, 35, 64, 246)
    );
    border: 0;
    border-right: 1px solid rgba(255,255,255,18);
}
QLabel#BrandIcon {
    background: rgba(255,255,255,16);
    border: 1px solid rgba(255,255,255,22);
    border-radius: 13px;
}
QLabel#BrandName {
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 700;
}
QLabel#BrandSub {
    color: #8FA0C1;
    font-size: 9px;
    letter-spacing: 1px;
}
QFrame#SideDivider {
    background: rgba(255,255,255,16);
    border: 0;
}
QPushButton#NavButton {
    color: #9EAAC1;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 12px 14px;
    text-align: left;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#NavButton:hover {
    background: rgba(255,255,255,7);
    color: #FFFFFF;
    border: 1px solid rgba(255,255,255,8);
}
QPushButton#NavButton[active="true"] {
    background: qlineargradient(
        x1:0,y1:0,x2:1,y2:0,
        stop:0 rgba(86,127,255,55),
        stop:1 rgba(86,127,255,18)
    );
    color: #FFFFFF;
    border: 1px solid rgba(117,151,255,42);
}
QFrame#SidebarMiniCard {
    background: rgba(255,255,255,7);
    border: 1px solid rgba(255,255,255,12);
    border-radius: 14px;
}
QLabel#SidebarMiniTitle {
    color: #EEF3FF;
    font-size: 10px;
    font-weight: 700;
}
QLabel#SidebarMiniText {
    color: #AAB7D1;
    font-size: 10px;
}
QLabel#SidebarMiniSub {
    color: #687894;
    font-size: 9px;
}
QFrame#Topbar {
    background: transparent;
    border: 0;
}
QLabel#PageTitle {
    font-size: 25px;
    font-weight: 700;
    color: #101828;
}
QLabel#PageSub {
    font-size: 11px;
    color: #7D879B;
}
QFrame#ConnectionPill {
    background: rgba(255,255,255,170);
    border: 1px solid rgba(255,255,255,210);
    border-radius: 14px;
}
QLabel#EngineStatus {
    color: #536176;
    font-size: 10px;
    font-weight: 600;
}
QFrame#Card {
    background: rgba(255,255,255,214);
    border: 1px solid rgba(255,255,255,235);
    border-radius: 20px;
}
QLabel#MetricTitle {
    color: #7D879A;
    font-size: 11px;
}
QLabel#MetricValue {
    color: #101828;
    font-size: 29px;
    font-weight: 700;
}
QLabel#MetricHint {
    color: #A0A8B7;
    font-size: 10px;
}
QLabel#SectionTitle {
    color: #101828;
    font-size: 16px;
    font-weight: 700;
}
QLabel#SectionSub {
    color: #8A94A8;
    font-size: 10px;
}
QLabel#SelectionCount {
    color: #667085;
    font-size: 10px;
    padding: 0 6px;
}
QPushButton#PrimaryButton {
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 #4B72F8,
        stop:1 #6D5DF7
    );
    color: #FFFFFF;
    border: 1px solid rgba(255,255,255,40);
    border-radius: 11px;
    padding: 10px 17px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #3F66EE,stop:1 #6052EA);
}
QPushButton#PrimaryButton:pressed { background: #465FD6; }
QPushButton#SecondaryButton {
    background: rgba(255,255,255,172);
    color: #344054;
    border: 1px solid rgba(201,211,229,175);
    border-radius: 11px;
    padding: 9px 15px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#SecondaryButton:hover {
    background: rgba(255,255,255,235);
    border-color: #BFCBE0;
}
QPushButton#DangerButton {
    background: rgba(255,241,241,190);
    color: #C7352D;
    border: 1px solid rgba(255,194,189,190);
    border-radius: 11px;
    padding: 9px 14px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#DangerButton:hover { background: #FFE9E7; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 38px;
    background: rgba(255,255,255,190);
    color: #1D2939;
    border: 1px solid rgba(204,214,231,180);
    border-radius: 11px;
    padding: 0 11px;
    selection-background-color: #D8E2FF;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    background: rgba(255,255,255,235);
    border: 1px solid #829BFF;
}
QComboBox::drop-down { border: 0; width: 28px; }
QTableWidget {
    background: rgba(255,255,255,118);
    border: 1px solid rgba(232,237,246,155);
    border-radius: 13px;
    gridline-color: rgba(232,237,246,120);
    color: #344054;
    selection-background-color: rgba(224,232,255,210);
    selection-color: #182033;
}
QHeaderView::section {
    background: rgba(245,248,253,205);
    color: #6E788A;
    border: 0;
    border-bottom: 1px solid rgba(224,230,240,190);
    padding: 10px 8px;
    font-size: 10px;
    font-weight: 600;
}
QTableWidget::item {
    border-bottom: 1px solid rgba(236,240,247,180);
    padding: 8px;
}
QTableWidget::item:selected {
    background: rgba(224,232,255,205);
    color: #172033;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: rgba(150,161,180,125);
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: rgba(116,130,153,155); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: rgba(150,161,180,125);
    border-radius: 4px;
    min-width: 30px;
}
QProgressBar {
    border: 0;
    background: rgba(218,225,237,165);
    border-radius: 4px;
    height: 7px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4E7FFF,stop:1 #7A68FF);
    border-radius: 4px;
}
QPlainTextEdit, QTextEdit {
    background: rgba(12,20,36,238);
    color: #C3CEE1;
    border: 1px solid rgba(53,69,98,150);
    border-radius: 14px;
    padding: 12px;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 10px;
    selection-background-color: #354D7B;
}
QCheckBox {
    color: #344054;
    spacing: 8px;
    font-size: 11px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #C8D2E2;
    border-radius: 5px;
    background: rgba(255,255,255,200);
}
QCheckBox::indicator:checked {
    background: #5A75F5;
    border-color: #5A75F5;
}
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: transparent;
    color: #7A8497;
    padding: 9px 14px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #526DE7;
    border-bottom: 2px solid #667CF5;
    font-weight: 600;
}
QToolTip {
    background: #111827;
    color: #FFFFFF;
    border: 0;
    padding: 6px;
}
QMessageBox {
    background: #F7F9FD;
}
"""
