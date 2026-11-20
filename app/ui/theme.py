"""浅色研究台 / 专业终端主题。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

BG = "#F4F6FA"
BG2 = "#FFFFFF"
PANEL = "#FFFFFF"
PANEL2 = "#FFFFFF"
CARD = "#FFFFFF"
BORDER = "#E3E8F0"
ACCENT = "#A9762A"
ACCENT2 = "#0E8C86"
TEXT = "#1B2733"
MUTED = "#6F7F92"
UP = "#D64545"
DOWN = "#1F9D67"
FLAT = "#6F7F92"
BLUE = "#3B6FD4"
PURPLE = "#7A5EA8"
SOFT = "#F7F9FC"

QSS = f"""
* {{ outline: none; }}
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QFrame#Card, QFrame#MetricCard, QFrame#Panel {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#Sidebar {{ background: {BG2}; border-right: 1px solid {BORDER}; }}
QFrame#TopBar {{ background: {BG2}; border-bottom: 1px solid {BORDER}; }}
QLabel {{ background: transparent; }}
QLabel#CardTitle {{ font-size: 13px; font-weight: 600; color: #334155; }}
QLabel#CardSub {{ font-size: 11px; color: {MUTED}; }}
QLabel#PageTitle {{ font-size: 23px; font-weight: 700; color: {TEXT}; }}
QLabel#PageSub {{ font-size: 11px; color: {MUTED}; }}
QLabel#BigValue {{ font-size: 27px; font-weight: 700; }}
QLabel#MetricLabel {{ font-size: 11px; color: {MUTED}; }}
QLabel#MetricValue {{ font-size: 20px; font-weight: 700; }}
QLabel#MetricSub {{ font-size: 10px; color: {MUTED}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#SectionLabel {{ color: {MUTED}; font-size: 10px; letter-spacing: 1px; }}
QLabel#BadgeUp {{ background: #FDF1F1; color: {UP}; border: 1px solid #F1C9C9;
                  border-radius: 10px; padding: 2px 9px; font-size: 11px; }}
QLabel#BadgeDown {{ background: #EFF9F4; color: {DOWN}; border: 1px solid #C5E6D8;
                    border-radius: 10px; padding: 2px 9px; font-size: 11px; }}
QLabel#BadgeNeutral {{ background: #F3F6FA; color: {MUTED}; border: 1px solid {BORDER};
                       border-radius: 10px; padding: 2px 9px; font-size: 11px; }}
QLabel#BadgeGold {{ background: #FBF5EA; color: {ACCENT}; border: 1px solid #E8D6B8;
                    border-radius: 10px; padding: 2px 9px; font-size: 11px; }}
QPushButton {{
    background: #F5F7FB; color: {TEXT}; border: 1px solid #DCE3ED;
    border-radius: 7px; padding: 7px 14px;
}}
QPushButton:hover {{ background: #EDF3FA; border-color: #C9D5E4; }}
QPushButton:pressed {{ background: #E5EDF7; }}
QPushButton:disabled {{ color: #A5B1C0; background: #F7F9FC; }}
QPushButton#Primary {{ background: {ACCENT}; color: #FFFFFF; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #8F6422; }}
QPushButton#Primary:disabled {{ background: #D9C4A2; color: #FFFFFF; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid #DCE3ED; color: {MUTED}; }}
QPushButton#Ghost:hover {{ color: {TEXT}; border-color: #BFCBDC; background: #F7F9FC; }}
QPushButton#Nav {{
    text-align: left; padding: 9px 14px; border-radius: 8px;
    background: transparent; border: none; color: #50627A; font-size: 13px;
}}
QPushButton#Nav:hover {{ background: #F2F6FB; color: {TEXT}; }}
QPushButton#Nav:checked {{ background: #FFFFFF; color: {TEXT}; border-left: 3px solid {ACCENT}; font-weight: 600; }}
QPushButton#ModeTab {{
    background: transparent; border: none; border-bottom: 2px solid transparent;
    color: {MUTED}; padding: 7px 8px; font-size: 12px; font-weight: 500;
}}
QPushButton#ModeTab:hover {{ color: {TEXT}; }}
QPushButton#ModeTab:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: 700; }}
QPushButton#Segment {{
    background: transparent; border: 1px solid transparent; color: {MUTED};
    padding: 5px 10px; border-radius: 6px; font-size: 11px;
}}
QPushButton#Segment:hover {{ background: #F4F7FB; color: {TEXT}; }}
QPushButton#Segment:checked {{ background: #FBF6EC; color: {ACCENT}; border: 1px solid #EAD9BF; font-weight: 600; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #FFFFFF; border: 1px solid #DCE3ED; border-radius: 6px;
    padding: 6px 9px; color: {TEXT}; selection-background-color: #E8F0FB;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{
    background: #FFFFFF; border: 1px solid {BORDER}; selection-background-color: #EAF1FA;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0px; border: none; background: transparent;
}}
QTableWidget {{
    background: transparent; border: none; gridline-color: transparent;
    alternate-background-color: #FAFBFD; selection-background-color: #E8F0FB;
    selection-color: {TEXT};
}}
QTableWidget::item {{ padding: 5px 6px; border-bottom: 1px solid #EDF1F7; }}
QHeaderView::section {{
    background: #F7F9FC; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 6px; font-size: 11px; font-weight: 500;
}}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; background: #FFFFFF; }}
QTabBar::tab {{
    background: transparent; color: {MUTED}; padding: 7px 15px; margin-right: 2px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: #334155; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C9D4E2; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #AEBED2; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; }}
QScrollBar::handle:horizontal {{ background: #C9D4E2; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QPlainTextEdit, QTextBrowser, QTextEdit {{
    background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 8px;
    color: #334155; selection-background-color: #E8F0FB;
}}
QSplitter::handle {{ background: transparent; width: 8px; height: 8px; }}
QCheckBox {{ spacing: 7px; color: #50627A; }}
QProgressBar {{ background: #F1F5FA; border: 1px solid {BORDER}; border-radius: 5px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ padding: 5px 4px; border-bottom: 1px solid #EDF1F7; color: #334155; }}
QListWidget::item:selected {{ background: #EAF1FA; }}
QToolTip {{ background: #FFFFFF; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
QStatusBar {{ background: {BG2}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QMenu {{ background: #FFFFFF; border: 1px solid {BORDER}; }}
QMenu::item {{ padding: 6px 20px; }}
QMenu::item:selected {{ background: #EAF1FA; }}
"""


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.AlternateBase, QColor("#FAFBFD"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor("#E8F0FB"))
    pal.setColor(QPalette.HighlightedText, QColor(TEXT))
    pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(pal)
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    app.setStyleSheet(QSS)


def color_for(v: float) -> str:
    if v > 0.0001:
        return UP
    if v < -0.0001:
        return DOWN
    return FLAT
