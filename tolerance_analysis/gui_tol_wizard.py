"""gui_tol_wizard.py —— GUI 逐镜片公差填写向导。

流程（公差填写向导_需求与设计.md）：
  选择 zmx → lens_scanner 扫描分组 → 分组确认页 → 逐镜片填写页（含空气间隔）
  → 汇总预览页（只读，二次确认）→ 生成新的高级 Excel 配置文件。

原则：
- 只读 zmx，不打开 Zemax；输出为全新 Excel，不覆盖任何已有文件；
- 一次只显示一个镜片；预览只读，编辑一律回到逐片页；
- 每片填写后自动保存 JSON 草稿，可恢复。
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from PySide6 import QtCore, QtWidgets

from toltool import excel_io, lens_scanner, standard_templates


# 中文公差项定义：(键, 显示名, 单位提示, 小数位)
# 半径单位二选一（光圈→TFRN / mm→TRAD），单独处理。
_ITEMS = [
    ("半径", "半径", "", 4),
    ("厚度", "厚度", "mm", 4),
    ("面偏心X", "面偏心X", "mm", 4),
    ("面偏心Y", "面偏心Y", "mm", 4),
    ("面倾斜X", "面倾斜X", "度", 4),
    ("面倾斜Y", "面倾斜Y", "度", 4),
    ("元件偏心X", "元件偏心X", "mm", 4),
    ("元件偏心Y", "元件偏心Y", "mm", 4),
    ("元件倾斜X", "元件倾斜X", "度", 4),
    ("元件倾斜Y", "元件倾斜Y", "度", 4),
    ("面不规则", "面不规则", "光圈", 4),
    ("折射率", "折射率", "-", 5),
    ("阿贝%", "阿贝%", "%", 4),
    ("空气间隔", "该片后空气间隔", "mm", 4),
]

# 等级预填默认值（沿用 standard_templates._LEVEL_VALUES 的口径）
_LEVEL_DEFAULTS = {
    "宽松": {"半径": 3, "厚度": 0.05, "面倾斜X": 0.05, "面倾斜Y": 0.05,
           "元件偏心X": 0.05, "元件偏心Y": 0.05, "元件倾斜X": 0.3, "元件倾斜Y": 0.3,
           "面不规则": 1, "折射率": 0.0005, "阿贝%": 1, "空气间隔": 0.05},
    "标准": {"半径": 3, "厚度": 0.03, "面倾斜X": 0.05, "面倾斜Y": 0.05,
           "元件偏心X": 0.03, "元件偏心Y": 0.03, "元件倾斜X": 0.2, "元件倾斜Y": 0.2,
           "面不规则": 1, "折射率": 0.0005, "阿贝%": 1, "空气间隔": 0.03},
    "严格": {"半径": 3, "厚度": 0.02, "面倾斜X": 0.025, "面倾斜Y": 0.025,
           "元件偏心X": 0.02, "元件偏心Y": 0.02, "元件倾斜X": 0.1, "元件倾斜Y": 0.1,
           "面不规则": 1, "折射率": 0.0005, "阿贝%": 1, "空气间隔": 0.02},
}

_DRAFT_VERSION = 1


def _lens_surfaces(group: lens_scanner.LensGroup) -> list[int]:
    """镜片全部光学面号（start..end）。"""
    return list(range(group.start_surface, group.end_surface + 1))


def _glass_surfaces(group: lens_scanner.LensGroup) -> list[int]:
    """带玻璃材料的面号（start..end-1，每段玻璃的前表面）。"""
    return list(range(group.start_surface, group.end_surface))


def build_detail_rows(groups: list[lens_scanner.LensGroup],
                      values: dict[int, dict]) -> list[dict]:
    """把逐镜片填写值转换为 输入_公差明细 行。

    values[group.index] = {"半径": float|None, ..., "半径单位": "光圈"/"mm", "跳过": bool}
    留空(None)的项不生成行。
    """
    rows: list[dict] = []

    def add(op: str, s1: int, s2: int, val: float, note: str) -> None:
        rows.append({"操作数": op, "面1": s1, "面2": s2,
                     "Min": -abs(val), "Max": abs(val), "注释": note})

    for g in groups:
        v = values.get(g.index) or {}
        if v.get("跳过"):
            continue
        tag = f"镜片{g.index} {'+'.join(g.materials)}"
        radius_op = "TRAD" if str(v.get("半径单位", "光圈")) == "mm" else "TFRN"
        known_keys = {key for key, _n, _u, _d in _ITEMS}
        for key, val in v.items():
            if key not in known_keys or val in (None, ""):
                continue
            val = float(val)
            if key == "半径":
                for s in _lens_surfaces(g):
                    add(radius_op, s, s, val, f"{tag} 半径 S{s}")
            elif key == "厚度":
                for s in _glass_surfaces(g):
                    add("TTHI", s, s, val, f"{tag} 厚度 S{s}")
            elif key == "面偏心X":
                for s in _lens_surfaces(g):
                    add("TSDX", s, s, val, f"{tag} 面偏心X S{s}")
            elif key == "面偏心Y":
                for s in _lens_surfaces(g):
                    add("TSDY", s, s, val, f"{tag} 面偏心Y S{s}")
            elif key == "面倾斜X":
                for s in _lens_surfaces(g):
                    add("TSTX", s, s, val, f"{tag} 面倾斜X S{s}")
            elif key == "面倾斜Y":
                for s in _lens_surfaces(g):
                    add("TSTY", s, s, val, f"{tag} 面倾斜Y S{s}")
            elif key == "元件偏心X":
                add("TEDX", g.start_surface, g.end_surface, val, f"{tag} 元件偏心X")
            elif key == "元件偏心Y":
                add("TEDY", g.start_surface, g.end_surface, val, f"{tag} 元件偏心Y")
            elif key == "元件倾斜X":
                add("TETX", g.start_surface, g.end_surface, val, f"{tag} 元件倾斜X")
            elif key == "元件倾斜Y":
                add("TETY", g.start_surface, g.end_surface, val, f"{tag} 元件倾斜Y")
            elif key == "面不规则":
                for s in _lens_surfaces(g):
                    add("TIRR", s, s, val, f"{tag} 面不规则 S{s}")
            elif key == "折射率":
                for s in _glass_surfaces(g):
                    add("TIND", s, s, val, f"{tag} 折射率 S{s}")
            elif key == "阿贝%":
                for s in _glass_surfaces(g):
                    add("TABB", s, s, val, f"{tag} 阿贝% S{s}")
            elif key == "空气间隔":
                add("TTHI", g.end_surface, g.end_surface, val, f"{tag} 后空气间隔 S{g.end_surface}")
    return rows


def _draft_path(zmx_path: str) -> str:
    base = os.path.splitext(os.path.basename(zmx_path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(zmx_path)),
                        f"公差填写草稿_{base}.json")


class TolWizardDialog(QtWidgets.QDialog):
    """逐镜片公差填写向导（三页：分组确认 / 逐片填写 / 汇总预览）。"""

    def __init__(self, zmx_path: str, parent=None, outdir: str | None = None):
        super().__init__(parent)
        self._zmx = os.path.abspath(zmx_path)
        # 生成的配置 Excel 输出目录：优先主界面输出目录，否则 zmx 同目录；
        # 草稿 JSON 仍固定在 zmx 同目录（跨会话恢复不受输出目录变化影响）。
        self._outdir = os.path.abspath(outdir) if outdir else os.path.dirname(self._zmx)
        self.result_path = ""            # 生成的配置 Excel 路径
        self._scan = lens_scanner.scan(self._zmx)
        self._groups: list[lens_scanner.LensGroup] = list(self._scan.groups)
        self._values: dict[int, dict] = {}
        self._cur = 0                    # 当前填写的镜片下标（_groups 下标）

        self.setWindowTitle("公差填写向导")
        self.resize(760, 560)
        self._stack = QtWidgets.QStackedWidget()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._stack)
        self._build_group_page()      # index 0
        self._build_fill_page()       # index 1
        self._build_merit_page()      # index 2
        self._build_preview_page()    # index 3
        self._load_draft_if_any()
        self._refresh_group_page()

    def showEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        super().showEvent(event)
        try:
            from gui import _apply_dark_titlebar
            _apply_dark_titlebar(self)
        except Exception:
            pass  # 独立运行/非 Windows 时静默忽略

    # ---------------- 页面 0：分组确认 ----------------

    def _build_group_page(self) -> None:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        title = QtWidgets.QLabel(f"镜头文件：{self._zmx}")
        title.setWordWrap(True)
        lay.addWidget(title)
        if not self._scan.succeeded:
            lay.addWidget(QtWidgets.QLabel(
                "扫描失败：" + "；".join(self._scan.warnings)))
        for w in self._scan.warnings:
            hint = QtWidgets.QLabel("提示：" + w)
            hint.setWordWrap(True)
            lay.addWidget(hint)
        lay.addWidget(QtWidgets.QLabel(
            "请确认镜片分组（勾选=参与公差填写；可拆分胶合组或合并相邻组）："))
        self.lst_groups = QtWidgets.QListWidget()
        lay.addWidget(self.lst_groups, 1)
        btns = QtWidgets.QHBoxLayout()
        self.btn_split = QtWidgets.QPushButton("拆分胶合组")
        self.btn_split.clicked.connect(self._on_split_group)
        self.btn_merge = QtWidgets.QPushButton("与下一组合并")
        self.btn_merge.clicked.connect(self._on_merge_group)
        btns.addWidget(self.btn_split)
        btns.addWidget(self.btn_merge)
        btns.addStretch(1)
        lay.addLayout(btns)
        nav = QtWidgets.QHBoxLayout()
        nav.addStretch(1)
        self.btn_group_next = QtWidgets.QPushButton("开始填写 →")
        self.btn_group_next.clicked.connect(self._on_group_next)
        self.btn_group_next.setEnabled(self._scan.succeeded and bool(self._groups))
        nav.addWidget(self.btn_group_next)
        lay.addLayout(nav)
        self._stack.addWidget(page)

    def _refresh_group_page(self) -> None:
        self.lst_groups.clear()
        for g in self._groups:
            item = QtWidgets.QListWidgetItem(g.label)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            skipped = bool((self._values.get(g.index) or {}).get("跳过"))
            default_skip = g.is_filter or g.is_plate
            if g.index not in self._values and default_skip:
                skipped = True
            item.setCheckState(QtCore.Qt.Unchecked if skipped else QtCore.Qt.Checked)
            self.lst_groups.addItem(item)

    def _renumber_groups(self) -> None:
        for i, g in enumerate(self._groups, start=1):
            g.index = i

    def _on_split_group(self) -> None:
        row = self.lst_groups.currentRow()
        if row < 0 or row >= len(self._groups):
            return
        g = self._groups[row]
        if not g.is_cemented:
            QtWidgets.QMessageBox.information(self, "拆分", "所选组不是胶合组，无需拆分。")
            return
        parts = []
        for k, mat in enumerate(g.materials):
            s1 = g.start_surface + k
            parts.append(lens_scanner.LensGroup(
                index=0, start_surface=s1, end_surface=s1 + 1,
                materials=[mat], is_filter=g.is_filter, is_plate=g.is_plate))
        self._groups[row:row + 1] = parts
        self._renumber_groups()
        self._values.clear()   # 分组变了，旧填写值面号不再可靠
        self._refresh_group_page()

    def _on_merge_group(self) -> None:
        row = self.lst_groups.currentRow()
        if row < 0 or row + 1 >= len(self._groups):
            return
        a, b = self._groups[row], self._groups[row + 1]
        if a.end_surface != b.start_surface:
            QtWidgets.QMessageBox.information(
                self, "合并", "两组面号不相邻（中间有空气面），不能合并为胶合组。")
            return
        merged = lens_scanner.LensGroup(
            index=0, start_surface=a.start_surface, end_surface=b.end_surface,
            materials=a.materials + b.materials,
            is_filter=a.is_filter or b.is_filter,
            is_plate=a.is_plate and b.is_plate)
        self._groups[row:row + 2] = [merged]
        self._renumber_groups()
        self._values.clear()
        self._refresh_group_page()

    def _on_group_next(self) -> None:
        # 记录跳过状态
        for i in range(self.lst_groups.count()):
            g = self._groups[i]
            skipped = self.lst_groups.item(i).checkState() != QtCore.Qt.Checked
            self._values.setdefault(g.index, {})["跳过"] = skipped
        active = [g for g in self._groups
                  if not self._values.get(g.index, {}).get("跳过")]
        if not active:
            QtWidgets.QMessageBox.warning(self, "公差填写", "至少要勾选一个镜片。")
            return
        self._cur = self._first_active(0)
        self._show_fill_page()

    def _first_active(self, start: int) -> int:
        for i in range(start, len(self._groups)):
            if not self._values.get(self._groups[i].index, {}).get("跳过"):
                return i
        return -1

    def _prev_active(self, start: int) -> int:
        for i in range(start, -1, -1):
            if not self._values.get(self._groups[i].index, {}).get("跳过"):
                return i
        return -1

    # ---------------- 页面 1：逐片填写 ----------------

    def _build_fill_page(self) -> None:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.lb_lens_title = QtWidgets.QLabel()
        self.lb_lens_title.setStyleSheet("font-weight:bold; font-size:14px;")
        lay.addWidget(self.lb_lens_title)

        level_row = QtWidgets.QHBoxLayout()
        level_row.addWidget(QtWidgets.QLabel("按等级预填："))
        self.cb_level = QtWidgets.QComboBox()
        self.cb_level.addItems(list(_LEVEL_DEFAULTS.keys()))
        self.cb_level.setCurrentText("标准")
        btn_prefill = QtWidgets.QPushButton("填入默认值")
        btn_prefill.clicked.connect(self._on_prefill)
        level_row.addWidget(self.cb_level)
        level_row.addWidget(btn_prefill)
        level_row.addStretch(1)
        lay.addLayout(level_row)

        form_widget = QtWidgets.QWidget()
        form = QtWidgets.QGridLayout(form_widget)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self._edits: dict[str, QtWidgets.QLineEdit] = {}
        self.cb_radius_unit = QtWidgets.QComboBox()
        self.cb_radius_unit.addItems(["光圈", "mm"])
        for i, (key, name, unit, _dec) in enumerate(_ITEMS):
            row, col = divmod(i, 2)
            form.addWidget(QtWidgets.QLabel(name + (f"（{unit}）" if unit else "")),
                           row, col * 3)
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("留空=不做此项公差")
            self._edits[key] = edit
            form.addWidget(edit, row, col * 3 + 1)
            if key == "半径":
                form.addWidget(self.cb_radius_unit, row, col * 3 + 2)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(form_widget)
        scroll.setWidgetResizable(True)
        lay.addWidget(scroll, 1)

        copy_row = QtWidgets.QHBoxLayout()
        self.btn_same_prev = QtWidgets.QPushButton("同上一片")
        self.btn_same_prev.clicked.connect(self._on_copy_prev)
        self.btn_apply_rest = QtWidgets.QPushButton("应用到剩余全部")
        self.btn_apply_rest.clicked.connect(self._on_apply_rest)
        copy_row.addWidget(self.btn_same_prev)
        copy_row.addWidget(self.btn_apply_rest)
        copy_row.addStretch(1)
        lay.addLayout(copy_row)

        nav = QtWidgets.QHBoxLayout()
        self.btn_fill_back = QtWidgets.QPushButton("← 上一片")
        self.btn_fill_back.clicked.connect(self._on_fill_back)
        self.btn_fill_next = QtWidgets.QPushButton("下一片 →")
        self.btn_fill_next.clicked.connect(self._on_fill_next)
        nav.addWidget(self.btn_fill_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_fill_next)
        lay.addLayout(nav)
        self._stack.addWidget(page)

    def _show_fill_page(self) -> None:
        g = self._groups[self._cur]
        self.lb_lens_title.setText(g.label)
        stored = self._values.get(g.index) or {}
        for key, edit in self._edits.items():
            val = stored.get(key)
            edit.setText("" if val in (None, "") else str(val))
        self.cb_radius_unit.setCurrentText(str(stored.get("半径单位", "光圈")))
        prev = self._prev_active(self._cur - 1)
        self.btn_same_prev.setEnabled(prev >= 0)
        self.btn_fill_back.setText("← 上一片" if prev >= 0 else "← 返回分组")
        nxt = self._first_active(self._cur + 1)
        self.btn_fill_next.setText("下一片 →" if nxt >= 0 else "汇总预览 →")
        self._stack.setCurrentIndex(1)

    def _collect_current(self) -> bool:
        """收集当前页输入到 _values；非法数字返回 False。"""
        g = self._groups[self._cur]
        data = self._values.setdefault(g.index, {})
        for key, edit in self._edits.items():
            text = edit.text().strip()
            if not text:
                data[key] = None
                continue
            try:
                data[key] = float(text)
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "公差填写", f"「{key}」的值 {text!r} 不是有效数字。")
                return False
        data["半径单位"] = self.cb_radius_unit.currentText()
        return True

    def _on_prefill(self) -> None:
        defaults = _LEVEL_DEFAULTS[self.cb_level.currentText()]
        for key, edit in self._edits.items():
            if key in defaults:
                edit.setText(str(defaults[key]))

    def _on_copy_prev(self) -> None:
        prev = self._prev_active(self._cur - 1)
        if prev < 0:
            return
        src = self._values.get(self._groups[prev].index) or {}
        for key, edit in self._edits.items():
            val = src.get(key)
            edit.setText("" if val in (None, "") else str(val))
        self.cb_radius_unit.setCurrentText(str(src.get("半径单位", "光圈")))

    def _on_apply_rest(self) -> None:
        if not self._collect_current():
            return
        cur = dict(self._values[self._groups[self._cur].index])
        i = self._first_active(self._cur + 1)
        count = 0
        while i >= 0:
            g = self._groups[i]
            skip = self._values.get(g.index, {}).get("跳过", False)
            self._values[g.index] = dict(cur)
            self._values[g.index]["跳过"] = skip
            count += 1
            i = self._first_active(i + 1)
        self._save_draft()
        QtWidgets.QMessageBox.information(
            self, "公差填写", f"当前值已应用到后续 {count} 个镜片。")

    def _on_fill_back(self) -> None:
        if not self._collect_current():
            return
        self._save_draft()
        prev = self._prev_active(self._cur - 1)
        if prev < 0:
            self._stack.setCurrentIndex(0)
            self._refresh_group_page()
            return
        self._cur = prev
        self._show_fill_page()

    def _on_fill_next(self) -> None:
        if not self._collect_current():
            return
        self._save_draft()
        nxt = self._first_active(self._cur + 1)
        if nxt < 0:
            self._show_merit_page()
            return
        self._cur = nxt
        self._show_fill_page()

    # ---------------- 页面 2：评价函数选择 ----------------

    def _build_merit_page(self) -> None:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.addWidget(QtWidgets.QLabel(
            "选择评价函数（口径与标准模板一致；指向/焦距/FOV/补偿器评价在运行期"
            "连接 Zemax 后自动生成，最终见 used_excel.xlsx）："))

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("产品类型："))
        self.cb_merit_product = QtWidgets.QComboBox()
        self.cb_merit_product.addItems(["RX", "TX"])
        self.cb_merit_product.currentTextChanged.connect(self._on_merit_product_changed)
        top.addWidget(self.cb_merit_product)
        top.addSpacing(16)
        top.addWidget(QtWidgets.QLabel("视场序列："))
        self.cb_field_seq = QtWidgets.QComboBox()
        self.cb_field_seq.addItem("标准（0/0.5/±0.9）", "标准")
        self.cb_field_seq.addItem("完整（0/±0.25/±0.5/±0.7/±0.9/±1）", "完整")
        top.addWidget(self.cb_field_seq)
        top.addStretch(1)
        lay.addLayout(top)

        self.chk_spot = QtWidgets.QCheckBox("① 点列 Spot（RSCE，全视场）")
        self.chk_spot.setChecked(True)
        self.chk_genc = QtWidgets.QCheckBox("② 包围圆能量 GENC（95%，0+边缘视场）")
        self.chk_genc.setChecked(True)
        mtf_row = QtWidgets.QHBoxLayout()
        self.chk_mtf = QtWidgets.QCheckBox("③ MTF（GMTT/GMTS，全视场）  频率(lp/mm)：")
        self.chk_mtf.setChecked(True)
        self.ed_mtf_freq = QtWidgets.QLineEdit("34")
        self.ed_mtf_freq.setMaximumWidth(80)
        mtf_row.addWidget(self.chk_mtf)
        mtf_row.addWidget(self.ed_mtf_freq)
        mtf_row.addStretch(1)
        self.chk_pointing = QtWidgets.QCheckBox(
            "④ 指向类（中心指向偏移 + 多视场指向角，运行期生成）")
        self.chk_pointing.setChecked(True)
        self.chk_efl_fov = QtWidgets.QCheckBox(
            "⑤ 焦距偏移% + 视场角 FOV（运行期生成）")
        self.chk_efl_fov.setChecked(True)
        lay.addWidget(self.chk_spot)
        lay.addWidget(self.chk_genc)
        lay.addLayout(mtf_row)
        lay.addWidget(self.chk_pointing)
        lay.addWidget(self.chk_efl_fov)
        hint = QtWidgets.QLabel(
            "说明：选择补偿器模式后，运行期会自动生成补偿专用评价函数"
            "（GMTA 单行，频率=预览页「补偿线对」，默认跟随上面的 MTF 频率），"
            "无需在此勾选。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

        nav = QtWidgets.QHBoxLayout()
        btn_back = QtWidgets.QPushButton("← 上一步")
        btn_back.clicked.connect(self._on_merit_back)
        btn_next = QtWidgets.QPushButton("汇总预览 →")
        btn_next.clicked.connect(self._on_merit_next)
        nav.addWidget(btn_back)
        nav.addStretch(1)
        nav.addWidget(btn_next)
        lay.addLayout(nav)
        self._stack.addWidget(page)

    def _on_merit_product_changed(self, text: str) -> None:
        is_tx = text.strip().upper() == "TX"
        if is_tx:
            self.chk_mtf.setChecked(False)
        self.chk_mtf.setEnabled(not is_tx)
        self.ed_mtf_freq.setEnabled(not is_tx)
        # TX 产品约定不做后焦补偿（与标准模板/pipeline 行为一致）
        if hasattr(self, "cb_comp_mode"):
            if is_tx:
                self.cb_comp_mode.setCurrentText("无")
            self.cb_comp_mode.setEnabled(not is_tx)
            tip = "TX 不做后焦补偿，固定为无。" if is_tx else ""
            self.cb_comp_mode.setToolTip(tip)
            self._sync_comp_fields_enabled()

    def _sync_comp_fields_enabled(self) -> None:
        """补偿器模式=无 时禁用补偿面/Min/Max/线对输入。"""
        on = self.cb_comp_mode.currentText().strip() != "无" \
            and self.cb_comp_mode.isEnabled()
        for w in (self.ed_comp_surface, self.ed_comp_min,
                  self.ed_comp_max, self.ed_comp_freq):
            w.setEnabled(on)

    def _show_merit_page(self) -> None:
        self._stack.setCurrentIndex(2)

    def _on_merit_back(self) -> None:
        self._cur = self._prev_active(len(self._groups) - 1)
        self._show_fill_page()

    def _on_merit_next(self) -> None:
        product = self.cb_merit_product.currentText().strip().upper()
        mtf_on = self.chk_mtf.isChecked() and product != "TX"
        if mtf_on:
            try:
                freq = float(self.ed_mtf_freq.text().strip())
                if freq <= 0:
                    raise ValueError
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "公差填写",
                    f"MTF 频率 {self.ed_mtf_freq.text().strip()!r} 不是有效正数。")
                return
        if not (self.chk_spot.isChecked() or self.chk_genc.isChecked() or mtf_on or
                self.chk_pointing.isChecked() or self.chk_efl_fov.isChecked()):
            QtWidgets.QMessageBox.warning(self, "公差填写", "至少选择一个评价函数类别。")
            return
        self._show_preview_page()

    # ---------------- 页面 3：汇总预览（只读二次确认） ----------------

    def _build_preview_page(self) -> None:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.addWidget(QtWidgets.QLabel(
            "公差汇总预览（只读）。确认无误后点「确认生成」，"
            "生成新的高级 Excel 配置文件；如需修改请返回逐片填写。"))
        self.lb_merit_summary = QtWidgets.QLabel()
        self.lb_merit_summary.setWordWrap(True)
        lay.addWidget(self.lb_merit_summary)
        self.tbl_preview = QtWidgets.QTableWidget()
        self.tbl_preview.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.tbl_preview, 1)

        run_group = QtWidgets.QGroupBox("运行参数")
        run_form = QtWidgets.QGridLayout(run_group)
        run_form.setHorizontalSpacing(10)
        run_form.setVerticalSpacing(6)
        self.cb_comp_mode = QtWidgets.QComboBox()
        self.cb_comp_mode.addItems(["无", "全部优化DLS", "全部优化OD"])
        self.cb_comp_mode.currentTextChanged.connect(
            lambda _t: self._sync_comp_fields_enabled())
        self.ed_comp_surface = QtWidgets.QLineEdit()
        self.ed_comp_surface.setPlaceholderText("留空=不加 COMP")
        self.sp_num_runs = QtWidgets.QSpinBox()
        self.sp_num_runs.setRange(1, 100000)
        self.sp_num_runs.setValue(20)
        self.sp_num_save = QtWidgets.QSpinBox()
        self.sp_num_save.setRange(0, self.sp_num_runs.value())
        self.sp_num_save.setValue(0)
        self.sp_num_runs.valueChanged.connect(self.sp_num_save.setMaximum)
        self.chk_wc_bc = QtWidgets.QCheckBox("保存 Worst/Best Case")
        self.ed_comp_freq = QtWidgets.QLineEdit("34")
        self.ed_comp_freq.setToolTip(
            "补偿专用评价函数（GMTA 单行）的空间频率；默认跟随评价函数页的 MTF 频率。")
        # 用户手动改过后不再跟随 MTF 频率自动预填
        self._comp_freq_edited = False
        self.ed_comp_freq.textEdited.connect(
            lambda _t: setattr(self, "_comp_freq_edited", True))
        run_form.addWidget(QtWidgets.QLabel("补偿器模式"), 0, 0)
        run_form.addWidget(self.cb_comp_mode, 0, 1)
        run_form.addWidget(QtWidgets.QLabel("后焦补偿面"), 0, 2)
        run_form.addWidget(self.ed_comp_surface, 0, 3)
        self.ed_comp_min = QtWidgets.QLineEdit()
        self.ed_comp_min.setPlaceholderText("留空=自由调整")
        self.ed_comp_max = QtWidgets.QLineEdit()
        self.ed_comp_max.setPlaceholderText("留空=自由调整")
        tip = ("补偿器允许的行程（相对名义厚度，mm），如 -0.1 / 0.1；\n"
               "写入 TDE COMP 硬限位，并在补偿评价函数中加 CTGT/CTLT 厚度软约束。")
        self.ed_comp_min.setToolTip(tip)
        self.ed_comp_max.setToolTip(tip)
        run_form.addWidget(QtWidgets.QLabel("补偿Min(mm)"), 1, 0)
        run_form.addWidget(self.ed_comp_min, 1, 1)
        run_form.addWidget(QtWidgets.QLabel("补偿Max(mm)"), 1, 2)
        run_form.addWidget(self.ed_comp_max, 1, 3)
        run_form.addWidget(QtWidgets.QLabel("蒙特卡洛次数"), 2, 0)
        run_form.addWidget(self.sp_num_runs, 2, 1)
        run_form.addWidget(QtWidgets.QLabel("保存数量"), 2, 2)
        run_form.addWidget(self.sp_num_save, 2, 3)
        run_form.addWidget(QtWidgets.QLabel("补偿线对(lp/mm)"), 3, 0)
        run_form.addWidget(self.ed_comp_freq, 3, 1)
        run_form.addWidget(self.chk_wc_bc, 3, 2, 1, 2)
        run_form.setColumnStretch(1, 1)
        run_form.setColumnStretch(3, 1)
        lay.addWidget(run_group)

        nav = QtWidgets.QHBoxLayout()
        btn_back = QtWidgets.QPushButton("← 返回修改")
        btn_back.clicked.connect(self._on_preview_back)
        self.btn_generate = QtWidgets.QPushButton("确认生成")
        self.btn_generate.clicked.connect(self._on_generate)
        nav.addWidget(btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_generate)
        lay.addLayout(nav)
        self._stack.addWidget(page)
        self._sync_comp_fields_enabled()   # 初始：模式=无 → 补偿输入禁用

    def _merit_summary_text(self) -> str:
        parts = []
        if self.chk_spot.isChecked():
            parts.append("SPOT")
        if self.chk_genc.isChecked():
            parts.append("GENC")
        if self.chk_mtf.isChecked():
            parts.append(f"MTF({self.ed_mtf_freq.text().strip()})")
        if self.chk_pointing.isChecked():
            parts.append("指向")
        if self.chk_efl_fov.isChecked():
            parts.append("EFL/FOV")
        seq = self.cb_field_seq.currentData()
        return (f"评价：{' + '.join(parts) if parts else '（未选择）'}，"
                f"视场={seq}，产品={self.cb_merit_product.currentText()}")

    def _show_preview_page(self) -> None:
        rows = build_detail_rows(self._groups, self._values)
        headers = ["操作数", "面1", "面2", "Min", "Max", "注释"]
        self.lb_merit_summary.setText(self._merit_summary_text())
        # 补偿线对默认与评价函数页的 MTF 频率一致（用户手动改过则不覆盖）
        if not self._comp_freq_edited:
            mtf_freq = self.ed_mtf_freq.text().strip()
            if self.chk_mtf.isChecked() and mtf_freq:
                self.ed_comp_freq.setText(mtf_freq)
        self.tbl_preview.clear()
        self.tbl_preview.setColumnCount(len(headers))
        self.tbl_preview.setHorizontalHeaderLabels(headers)
        self.tbl_preview.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, h in enumerate(headers):
                self.tbl_preview.setItem(
                    r, c, QtWidgets.QTableWidgetItem(str(row.get(h, ""))))
        self.tbl_preview.resizeColumnsToContents()
        self.btn_generate.setEnabled(bool(rows))
        if not rows:
            QtWidgets.QMessageBox.warning(
                self, "公差填写", "没有任何有效公差项（全部留空），无法生成配置。")
        self._stack.setCurrentIndex(3)

    def _on_preview_back(self) -> None:
        self._show_merit_page()

    def _on_generate(self) -> None:
        rows = build_detail_rows(self._groups, self._values)
        if not rows:
            return
        comp_off = self.cb_comp_mode.currentText().strip() == "无"
        comp_surface = ""
        if not comp_off:
            comp_surface = self.ed_comp_surface.text().strip()
            if comp_surface:
                try:
                    comp_surface = int(float(comp_surface))
                except ValueError:
                    QtWidgets.QMessageBox.warning(
                        self, "公差填写", f"后焦补偿面 {comp_surface!r} 不是有效面号。")
                    return
        base = os.path.splitext(os.path.basename(self._zmx))[0]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            os.makedirs(self._outdir, exist_ok=True)
        except OSError as e:
            QtWidgets.QMessageBox.warning(
                self, "公差填写", f"输出目录不可用：{self._outdir}\n{e}")
            return
        out = os.path.join(self._outdir, f"公差填写_{base}_{stamp}.xlsx")
        wc_bc = "Y" if self.chk_wc_bc.isChecked() else "N"
        product = self.cb_merit_product.currentText().strip().upper()
        field_seq = str(self.cb_field_seq.currentData())
        target_fields = (standard_templates.FULL_TARGET_FIELDS if field_seq == "完整"
                         else standard_templates.STANDARD_TARGET_FIELDS)
        template_name = "完整视场分析" if field_seq == "完整" else "标准分析"
        mtf_on = self.chk_mtf.isChecked() and product != "TX"
        try:
            mtf_freq = float(self.ed_mtf_freq.text().strip() or 34)
            if mtf_on and mtf_freq <= 0:
                raise ValueError
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self, "公差填写", f"MTF 频率 {self.ed_mtf_freq.text().strip()!r} 不是有效正数。")
            return
        if self.sp_num_save.value() > self.sp_num_runs.value():
            QtWidgets.QMessageBox.warning(self, "公差填写", "保存数量不能大于蒙特卡洛次数。")
            return
        # 补偿器模式=无时跳过 comp 参数校验（字段已禁用，残留值不参与生成）
        comp_freq = 34.0
        cmin, cmax = "", ""
        if not comp_off:
            try:
                comp_freq = float(self.ed_comp_freq.text().strip() or 34)
                if comp_freq <= 0:
                    raise ValueError
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "公差填写",
                    f"补偿线对 {self.ed_comp_freq.text().strip()!r} 不是有效正数。")
                return
            comp_limits = {}
            for key, edit in (("补偿Min", self.ed_comp_min), ("补偿Max", self.ed_comp_max)):
                text = edit.text().strip()
                if not text:
                    comp_limits[key] = ""
                    continue
                try:
                    comp_limits[key] = float(text)
                except ValueError:
                    QtWidgets.QMessageBox.warning(
                        self, "公差填写", f"{key} 的值 {text!r} 不是有效数字。")
                    return
            cmin, cmax = comp_limits["补偿Min"], comp_limits["补偿Max"]
            if (cmin != "" and cmin > 0) or (cmax != "" and cmax < 0) \
                    or (cmin != "" and cmax != "" and cmin > cmax):
                QtWidgets.QMessageBox.warning(
                    self, "公差填写",
                    "补偿Min/Max 需满足 Min ≤ 0 ≤ Max（相对名义厚度的行程范围）。")
                return
        mfe_rows, report_rows = standard_templates.build_custom_mfe_report(
            field_seq=field_seq,
            include_spot=self.chk_spot.isChecked(),
            include_genc=self.chk_genc.isChecked(),
            include_mtf=mtf_on,
            mtf_freq=mtf_freq,
            center_wave=0)
        has_static_merit = bool(mfe_rows)
        dyn = self.chk_pointing.isChecked() or self.chk_efl_fov.isChecked()
        try:
            excel_io.write_detail_config(
                out, rows,
                mfe_rows=mfe_rows, report_rows=report_rows,
                extra_run_params={
                    "源镜头文件": self._zmx,
                    "面数指纹": self._scan.fingerprint,
                    "产品类型": product,
                    "标准模板": template_name,
                    "目标归一化视场": ",".join(f"{float(field):g}" for field in target_fields),
                    "目标视场来源策略": "自动推断",
                    "补偿器模式": self.cb_comp_mode.currentText(),
                    "后焦补偿面": comp_surface,
                    "补偿线对": comp_freq,
                    "补偿Min": cmin,
                    "补偿Max": cmax,
                    "蒙特卡洛次数": self.sp_num_runs.value(),
                    "保存数量": self.sp_num_save.value(),
                    "保存WorstCase": wc_bc,
                    "保存BestCase": wc_bc,
                    "中心波长号": 0,
                    "启用动态评价项": "Y" if dyn else "N",
                    "启用中心指向偏移": "Y" if self.chk_pointing.isChecked() else "N",
                    "启用指向角": "Y" if self.chk_pointing.isChecked() else "N",
                    "启用焦距偏移百分比": "Y" if self.chk_efl_fov.isChecked() else "N",
                    "启用FOV": "Y" if self.chk_efl_fov.isChecked() else "N",
                    "启用视场映射": "Y" if has_static_merit else "N",
                    "视场插入策略": "自动插入",
                })
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "公差填写", f"生成配置失败：{type(e).__name__}: {e}")
            return
        self.result_path = out
        self._remove_draft()
        QtWidgets.QMessageBox.information(
            self, "公差填写",
            f"已生成配置文件：\n{out}\n\n"
            "评价函数已按所选类别写入；指向/焦距/FOV/补偿器评价将在运行期自动生成。")
        self.accept()

    # ---------------- 草稿 ----------------

    def reject(self) -> None:  # noqa: N802（Qt 命名）
        """中途关闭（X / Esc）时静默保存草稿，下次可恢复。"""
        self._save_draft_silent()
        super().reject()

    def _collect_current_silent(self) -> None:
        """静默收集当前填写页输入（忽略非法数字，不弹窗）。"""
        if self._stack.currentIndex() != 1 or not self._groups:
            return
        g = self._groups[self._cur]
        data = self._values.setdefault(g.index, {})
        for key, edit in self._edits.items():
            text = edit.text().strip()
            if not text:
                data[key] = None
                continue
            try:
                data[key] = float(text)
            except ValueError:
                continue  # 非法值不覆盖已有草稿值
        data["半径单位"] = self.cb_radius_unit.currentText()

    def _save_draft_silent(self) -> None:
        self._collect_current_silent()
        if any(v for v in self._values.values()):
            self._save_draft()

    def _merit_run_state(self) -> dict:
        """评价函数页 + 预览页运行参数的当前选择（存入草稿）。"""
        return {
            "product": self.cb_merit_product.currentText(),
            "field_seq": str(self.cb_field_seq.currentData()),
            "spot": self.chk_spot.isChecked(),
            "genc": self.chk_genc.isChecked(),
            "mtf": self.chk_mtf.isChecked(),
            "mtf_freq": self.ed_mtf_freq.text().strip(),
            "pointing": self.chk_pointing.isChecked(),
            "efl_fov": self.chk_efl_fov.isChecked(),
            "comp_mode": self.cb_comp_mode.currentText(),
            "comp_surface": self.ed_comp_surface.text().strip(),
            "comp_min": self.ed_comp_min.text().strip(),
            "comp_max": self.ed_comp_max.text().strip(),
            "comp_freq": self.ed_comp_freq.text().strip(),
            "comp_freq_edited": self._comp_freq_edited,
            "num_runs": self.sp_num_runs.value(),
            "num_save": self.sp_num_save.value(),
            "wc_bc": self.chk_wc_bc.isChecked(),
        }

    def _restore_merit_run_state(self, state: dict) -> None:
        if not state:
            return
        try:
            self.cb_merit_product.setCurrentText(str(state.get("product", "RX")))
            idx = self.cb_field_seq.findData(state.get("field_seq", "标准"))
            if idx >= 0:
                self.cb_field_seq.setCurrentIndex(idx)
            self.chk_spot.setChecked(bool(state.get("spot", True)))
            self.chk_genc.setChecked(bool(state.get("genc", True)))
            if self.chk_mtf.isEnabled():
                self.chk_mtf.setChecked(bool(state.get("mtf", True)))
            if state.get("mtf_freq"):
                self.ed_mtf_freq.setText(str(state["mtf_freq"]))
            self.chk_pointing.setChecked(bool(state.get("pointing", True)))
            self.chk_efl_fov.setChecked(bool(state.get("efl_fov", True)))
            if self.cb_comp_mode.isEnabled():
                self.cb_comp_mode.setCurrentText(str(state.get("comp_mode", "无")))
            self.ed_comp_surface.setText(str(state.get("comp_surface", "")))
            self.ed_comp_min.setText(str(state.get("comp_min", "")))
            self.ed_comp_max.setText(str(state.get("comp_max", "")))
            if state.get("comp_freq"):
                self.ed_comp_freq.setText(str(state["comp_freq"]))
            self._comp_freq_edited = bool(state.get("comp_freq_edited", False))
            self.sp_num_runs.setValue(int(state.get("num_runs", 20)))
            self.sp_num_save.setValue(int(state.get("num_save", 0)))
            self.chk_wc_bc.setChecked(bool(state.get("wc_bc", False)))
        except (TypeError, ValueError):
            pass  # 草稿字段异常时保留控件默认值

    def _save_draft(self) -> None:
        try:
            data = {
                "version": _DRAFT_VERSION,
                "zmx": self._zmx,
                "fingerprint": self._scan.fingerprint,
                "groups": [
                    {"index": g.index, "start": g.start_surface,
                     "end": g.end_surface, "materials": g.materials,
                     "is_filter": g.is_filter, "is_plate": g.is_plate}
                    for g in self._groups
                ],
                "values": {str(k): v for k, v in self._values.items()},
                "merit_run": self._merit_run_state(),
            }
            with open(_draft_path(self._zmx), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # 草稿失败不阻断填写

    def _remove_draft(self) -> None:
        try:
            path = _draft_path(self._zmx)
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def _load_draft_if_any(self) -> None:
        path = _draft_path(self._zmx)
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if data.get("fingerprint") != self._scan.fingerprint:
            QtWidgets.QMessageBox.information(
                self, "公差填写",
                "检测到旧草稿，但镜头文件面结构已改动，草稿作废，将重新开始。")
            self._remove_draft()
            return
        ret = QtWidgets.QMessageBox.question(
            self, "公差填写", "检测到上次未完成的填写草稿，是否继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ret != QtWidgets.QMessageBox.Yes:
            self._remove_draft()
            return
        try:
            self._groups = [
                lens_scanner.LensGroup(
                    index=int(g["index"]), start_surface=int(g["start"]),
                    end_surface=int(g["end"]), materials=list(g["materials"]),
                    is_filter=bool(g.get("is_filter")),
                    is_plate=bool(g.get("is_plate")))
                for g in data.get("groups", [])
            ] or self._groups
            self._values = {int(k): v for k, v in (data.get("values") or {}).items()}
        except (KeyError, TypeError, ValueError):
            self._groups = list(self._scan.groups)
            self._values = {}
            return
        self._restore_merit_run_state(data.get("merit_run") or {})
