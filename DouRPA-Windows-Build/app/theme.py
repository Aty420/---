APP_STYLESHEET = r"""
* {
    font-family: "Microsoft YaHei UI", "Segoe UI";
    outline: none;
}
QMainWindow, QWidget#Root {
    background: #F5F7FB;
    color: #182033;
}
QFrame#Sidebar {
    background: #0E1525;
    border: none;
}
QLabel#BrandName {
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 700;
}
QLabel#BrandSub {
    color: #7F8BA4;
    font-size: 11px;
}
QPushButton#NavButton {
    color: #9CA8BF;
    background: transparent;
    border: 0;
    border-radius: 10px;
    padding: 11px 14px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}
QPushButton#NavButton:hover {
    background: #151F33;
    color: #FFFFFF;
}
QPushButton#NavButton[active="true"] {
    background: #1A2B4C;
    color: #FFFFFF;
    border-left: 3px solid #5B8CFF;
}
QFrame#Topbar {
    background: transparent;
    border: 0;
}
QLabel#PageTitle {
    font-size: 24px;
    font-weight: 700;
    color: #111827;
}
QLabel#PageSub {
    font-size: 12px;
    color: #7B8497;
}
QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #E9EDF5;
    border-radius: 16px;
}
QLabel#MetricTitle {
    color: #7E8798;
    font-size: 12px;
}
QLabel#MetricValue {
    color: #111827;
    font-size: 27px;
    font-weight: 700;
}
QLabel#MetricHint {
    color: #98A2B3;
    font-size: 11px;
}
QLabel#SectionTitle {
    color: #111827;
    font-size: 16px;
    font-weight: 700;
}
QLabel#SectionSub {
    color: #8A94A7;
    font-size: 11px;
}
QPushButton#PrimaryButton {
    background: #356DFF;
    color: #FFFFFF;
    border: 0;
    border-radius: 10px;
    padding: 10px 16px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #2D62ED; }
QPushButton#PrimaryButton:pressed { background: #2757D6; }
QPushButton#SecondaryButton {
    background: #FFFFFF;
    color: #344054;
    border: 1px solid #DCE2EC;
    border-radius: 10px;
    padding: 9px 15px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#SecondaryButton:hover { background: #F7F9FC; }
QPushButton#DangerButton {
    background: #FFF2F2;
    color: #D92D20;
    border: 1px solid #FFD5D2;
    border-radius: 9px;
    padding: 8px 13px;
    font-size: 12px;
    font-weight: 600;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 37px;
    background: #FFFFFF;
    color: #1D2939;
    border: 1px solid #DDE3ED;
    border-radius: 9px;
    padding: 0 10px;
    selection-background-color: #C8D7FF;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #6C93FF;
}
QComboBox::drop-down { border: 0; width: 28px; }
QTableWidget {
    background: #FFFFFF;
    border: 0;
    gridline-color: #EFF2F6;
    color: #344054;
    selection-background-color: #EDF3FF;
    selection-color: #182033;
}
QHeaderView::section {
    background: #F8FAFD;
    color: #667085;
    border: 0;
    border-bottom: 1px solid #E8ECF3;
    padding: 10px 8px;
    font-size: 11px;
    font-weight: 600;
}
QTableWidget::item {
    border-bottom: 1px solid #F0F2F6;
    padding: 8px;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #CCD3DF;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar {
    border: 0;
    background: #EEF2F7;
    border-radius: 4px;
    height: 7px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #4E7FFF;
    border-radius: 4px;
}
QTextEdit {
    background: #0D1422;
    color: #B7C4DB;
    border: 1px solid #202B41;
    border-radius: 12px;
    padding: 10px;
    font-family: Consolas, "Microsoft YaHei UI";
    font-size: 11px;
}
QCheckBox { color: #344054; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #CBD3DF;
    border-radius: 5px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #356DFF;
    border-color: #356DFF;
}
QTabWidget::pane { border: 0; }
QTabBar::tab {
    background: transparent;
    color: #7A8497;
    padding: 9px 14px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #2D62ED;
    border-bottom: 2px solid #356DFF;
    font-weight: 600;
}
QToolTip {
    background: #111827;
    color: #FFFFFF;
    border: 0;
    padding: 6px;
}
"""
