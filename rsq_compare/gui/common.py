"""모든 화면에 동일하게 적용하는 표시 규칙."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont,QKeySequence
from PySide6.QtWidgets import QApplication,QTableView,QAbstractItemView,QHeaderView,QMessageBox

STYLE='''
QWidget { color:#15263c; font-size:10pt; }
QMainWindow,QDialog { background:#f5f7fb; }
QTabWidget::pane { border:1px solid #b8c8dc; background:white; }
QTabBar::tab { color:#44566e; padding:9px 14px; background:#e9edf3; border:1px solid #c3cede; }
QTabBar::tab:selected { color:#102e57; font-weight:bold; background:#dcecff; border-bottom:3px solid #1769aa; }
QTabBar::tab:focus { outline:none; border-top:2px dashed #b65e00; }
QPushButton { padding:7px 12px; border:1px solid #9aaec7; border-radius:4px; background:#fff; }
QPushButton:hover { background:#e7f1ff; }
QPushButton:focus,QLineEdit:focus,QComboBox:focus { border:2px dashed #a55300; }
QPushButton[primary="true"] { background:#173e6c; color:white; font-weight:bold; }
QPushButton[danger="true"] { color:#a21d26; border-color:#cf959a; }
QTableView,QTableWidget { background:white; alternate-background-color:#f1f5fa; selection-background-color:#cce1fb; selection-color:#102e57; gridline-color:#d7e0eb; }
QHeaderView::section { background:#e3ebf5; color:#183754; padding:6px; font-weight:bold; }
QLineEdit,QComboBox,QDoubleSpinBox { background:white; padding:5px; border:1px solid #98abc2; }
QToolTip { background:#fffbe8; color:#15263c; border:1px solid #ac9d63; }
'''


def apply_theme(app):
    app.setFont(QFont('Malgun Gothic' if __import__('sys').platform=='win32' else 'Noto Sans CJK KR',10))
    app.setStyleSheet(STYLE)


class CopyTable(QTableView):
    def keyPressEvent(self,e):
        if e.matches(QKeySequence.Copy):
            indices=self.selectionModel().selectedIndexes()
            if indices:
                rows=sorted({i.row() for i in indices});cols=sorted({i.column() for i in indices})
                QApplication.clipboard().setText('\n'.join('\t'.join(str(self.model().data(self.model().index(r,c),Qt.ToolTipRole) or '') for c in cols) for r in rows))
            return
        super().keyPressEvent(e)
    def mouseDoubleClickEvent(self,e):
        index=self.indexAt(e.position().toPoint())
        if index.isValid():QMessageBox.information(self,'값 전체 보기',str(self.model().data(index,Qt.ToolTipRole) or '빈값'))
        else:super().mouseDoubleClickEvent(e)
