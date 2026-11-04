"""pandas DataFrame을 Qt 표(QTableView)에 보여주기 위한 모델.

화면에서는 숫자를 보기 좋게 반올림해서 보여주지만, 실제 값은 바꾸지 않는다.
마우스를 올리면(툴팁) 원본 값을 그대로 볼 수 있다.
"""
from __future__ import annotations

import math
import numbers

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

DISPLAY_DECIMALS = 4
LEVEL_COLORS = {"오류": QColor("#fde2e1"), "주의": QColor("#fff4d6")}


class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, highlight_col: str | None = None, parent=None, check_column=None, on_check=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        self._hl = highlight_col
        self._check_column = check_column
        self._on_check = on_check

    def set_df(self, df: pd.DataFrame | None, highlight_col: str | None = None):
        self.beginResetModel()
        self._df = df if df is not None else pd.DataFrame()
        self._hl = highlight_col
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df.columns)

    @staticmethod
    def _is_missing(v) -> bool:
        if v is None:
            return True
        try:
            return bool(pd.isna(v))
        except (TypeError, ValueError):
            return False

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        v = self._df.iat[index.row(), index.column()]
        if role == Qt.CheckStateRole and self._df.columns[index.column()]==self._check_column:
            return Qt.Checked if bool(v) else Qt.Unchecked
        if role == Qt.DisplayRole:
            if self._df.columns[index.column()]==self._check_column:return ''
            if self._is_missing(v):
                return ""
            if isinstance(v, float):
                if not math.isfinite(v):
                    return str(v)
                s = f"{v:.{DISPLAY_DECIMALS}f}".rstrip("0").rstrip(".")
                return "0" if s in ("-0", "") else s
            return str(v)
        if role == Qt.ToolTipRole:
            return "빈값 (원본에 값 없음 · 0으로 바꾸지 않음)" if self._is_missing(v) else repr(v) if isinstance(v, float) else str(v)
        if role == Qt.TextAlignmentRole:
            if isinstance(v, numbers.Number) and not isinstance(v, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.BackgroundRole and self._hl is not None and self._hl in self._df.columns:
            lv = self._df.iat[index.row(), self._df.columns.get_loc(self._hl)]
            c = LEVEL_COLORS.get(str(lv))
            if c is None and isinstance(lv, str) and "요약 결과 없음" in lv:
                c = LEVEL_COLORS["주의"]
            return QBrush(c) if c else None
        return None

    def flags(self,index):
        flags=super().flags(index)
        if index.isValid() and self._df.columns[index.column()]==self._check_column:flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self,index,value,role=Qt.EditRole):
        if role==Qt.CheckStateRole and self._df.columns[index.column()]==self._check_column:
            checked=value==Qt.Checked or value==Qt.Checked.value
            self._df.iat[index.row(),index.column()]=checked
            self.dataChanged.emit(index,index,[Qt.CheckStateRole])
            if self._on_check:self._on_check(index.row(),checked)
            return True
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section]) if section < len(self._df.columns) else None
        return str(section + 1)
