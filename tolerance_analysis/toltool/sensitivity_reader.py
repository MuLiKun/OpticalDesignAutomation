"""读取 ZTD SensitivityData 并导出单 REPORT Top20 敏感度排序。

实测 API（ZOS 2023 R1）：
  SensitivityData 不是矩阵，是对象：
    .NumberOfCriteria       = 1(判据) + N(REPORT)
    .NumberOfResultOperands = M(TDE 公差项，不含 COMP)
    .GetCriterion(i)        → ISensitivityCriterionMetadata
      .Name                 判据名（Criterion 0=UserScript，其余=-1）
      .NominalValue         标称值
      .GetEffectByOperand(j) → ISensitivityOperandEffect
        .EstimatedChangeMaximum  最大变化量
        .EstimatedChangeMinimum  最小变化量
    .GetOperand(j)          → ISensitivityOperandMetadata
      .OperandType          公差向导类型（TFRN/TTHI/…）
      .Comment              注释
      .Minimum / .Maximum   公差范围
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .ztd_reader import parse_summary_labels


_TOP_N = 20


@dataclass
class SensitivityItem:
    report_label: str
    rank: int
    nominal_value: float
    operand: str
    tolerance_label: str
    tolerance_type: str
    surface_or_element: str
    tolerance_range: str
    delta: float
    abs_delta: float
    risk: str = ""


@dataclass
class SensitivityResult:
    succeeded: bool
    ztd_path: str
    items: list[SensitivityItem] = field(default_factory=list)
    diagnostics: list[tuple[str, str]] = field(default_factory=list)
    message: str = ""


_KIND_MAP = {
    "TRAD": "半径",
    "TTHI": "厚度",
    "TSDX": "面偏心X",
    "TSDY": "面偏心Y",
    "TSTX": "面倾斜X",
    "TSTY": "面倾斜Y",
    "TEDX": "元件偏心X",
    "TEDY": "元件偏心Y",
    "TETX": "元件倾斜X",
    "TETY": "元件倾斜Y",
    "TIRR": "面不规则",
    "TIND": "折射率",
    "TABB": "阿贝数",
    "COMP": "补偿器",
}


def _clean(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("none", "nan") else text


def _as_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _report_labels(report_meta=None, report_labels=None) -> list[str]:
    labels = []
    if report_labels:
        labels = [_clean(x) for x in report_labels]
    elif report_meta:
        labels = [_clean(row.get("标签")) for row in report_meta]
    return [x for x in labels if x]


def _report_info_by_label(report_meta=None) -> dict[str, dict[str, str]]:
    out = {}
    for row in list(report_meta or []):
        label = _clean(row.get("标签"))
        if label:
            out[label] = row
    return out



def _nominal_from_meta(row: dict | None) -> float:
    if not row:
        return float("nan")
    for key in ("名义值", "Nominal", "nominal"):
        value = _as_float(row.get(key))
        if math.isfinite(value):
            return value
    return float("nan")


def _summary_nominals(summary: str) -> dict[str, float]:
    return {label: nominal for label, nominal in parse_summary_labels(summary)}


def _nominal_for(label: str, row: dict | None, summary_nominals: dict[str, float]) -> float:
    value = _nominal_from_meta(row)
    if math.isfinite(value):
        return value
    for key in (label, label.split("__", 1)[0]):
        value = summary_nominals.get(key)
        if value is not None and math.isfinite(value):
            return value
    return float("nan")


def _risk(delta: float, direction: str) -> str:
    if not math.isfinite(delta):
        return ""
    text = _clean(direction)
    if not text:
        return "未配置"
    # REPORT 方向列约定写 "大"/"小"（也兼容 "越大越好"/"越小越好"）
    if "大" in text:
        return "不利" if delta < 0 else "有利"
    if "小" in text:
        return "不利" if delta > 0 else "有利"
    return "需判断"


def _tol_range(row: dict) -> str:
    mn = row.get("Min")
    mx = row.get("Max")
    if _clean(mn) or _clean(mx):
        return f"{mn} ~ {mx}"
    return ""


def _surface_or_element(row: dict) -> str:
    op = _clean(row.get("操作数")).upper()
    p1 = _clean(row.get("Param1"))
    p2 = _clean(row.get("Param2"))
    if op in ("TTHI", "TEDX", "TEDY", "TETX", "TETY") and p1 and p2 and p2 not in ("0", "0.0"):
        return f"S{p1}-S{p2}"
    if p1 and p1 not in ("0", "0.0"):
        return f"S{p1}"
    return ""


def _tol_label(row: dict) -> str:
    op = _clean(row.get("操作数")).upper()
    comment = _clean(row.get("Comment"))
    surf = _surface_or_element(row)
    parts = [op]
    if surf:
        parts.append(surf)
    if comment:
        parts.append(comment)
    return " ".join(parts).strip() or f"TDE{row.get('行号', '')}"


def _build_tde_index(tde_rows: list[dict]) -> list[int]:
    """返回 SensitivityData 操作数索引 → TDE 行索引的映射（跳过 COMP）。"""
    mapping = []
    for i, row in enumerate(tde_rows):
        op = _clean(row.get("操作数")).upper()
        if op != "COMP":
            mapping.append(i)
    return mapping


def read_sensitivity(zos_system, ztd_path: str, report_meta=None,
                     report_labels=None, tde_meta=None,
                     top_n: int = _TOP_N) -> SensitivityResult:
    diagnostics: list[tuple[str, str]] = [("ZTD文件", ztd_path)]
    reports = _report_labels(report_meta, report_labels)
    tde_rows = [row for row in list(tde_meta or []) if _clean(row.get("操作数")).upper() != "BLNK"]
    diagnostics.append(("REPORT数量", str(len(reports))))
    diagnostics.append(("TDE元数据行数", str(len(tde_rows))))
    if not reports:
        return SensitivityResult(False, ztd_path, diagnostics=diagnostics,
                                 message="缺少 REPORT 标签，无法生成敏感度排序。")
    if not tde_rows:
        return SensitivityResult(False, ztd_path, diagnostics=diagnostics,
                                 message="缺少 TDE 元数据，无法匹配敏感度行。")

    tde_index = _build_tde_index(tde_rows)
    diagnostics.append(("TDE非COMP行数", str(len(tde_index))))

    dv = zos_system.Tools.OpenToleranceDataViewer()
    try:
        dv.FileName = ztd_path
        ok = bool(dv.RunAndWaitForCompletion())
        diagnostics.append(("DataViewer运行", str(ok)))
        diagnostics.append(("DataViewer成功", str(bool(getattr(dv, "Succeeded", False)))))
        err = _clean(getattr(dv, "ErrorMessage", ""))
        if err:
            diagnostics.append(("DataViewer消息", err))
        summary = ""
        try:
            summary = str(dv.Summary)
        except Exception:
            pass
        summary_nominals = _summary_nominals(summary)
        diagnostics.append(("Summary名义值数", str(len(summary_nominals))))
        try:
            sd = dv.SensitivityData
        except Exception as e:
            return SensitivityResult(False, ztd_path, diagnostics=diagnostics,
                                     message=f"读取 SensitivityData 失败：{type(e).__name__}: {e}")

        n_criteria = int(sd.NumberOfCriteria)
        n_operands = int(sd.NumberOfResultOperands)
        diagnostics.append(("SensitivityData.Criteria数", str(n_criteria)))
        diagnostics.append(("SensitivityData.Operand数", str(n_operands)))

        # Criterion 0 = 综合判据（UserScript），Criterion 1..N = REPORT 分项。
        # 此假设仅在 TSC 自定义脚本（CriterionIndex=15）模式下成立；
        # 若 ZTD 使用其他判据模式（如评价函数判据），则无 REPORT 分项，
        # n_criteria 不足时下方会记录诊断并跳过对应 REPORT。
        report_start = 1
        if n_criteria < len(reports) + 1:
            diagnostics.append(("Criteria匹配", f"不足：Criteria={n_criteria}, REPORT={len(reports)}"))
            # 尝试只用可用的 criteria
            pass
        else:
            diagnostics.append(("Criteria匹配", f"OK：Criteria={n_criteria}, REPORT={len(reports)}"))

        if n_operands != len(tde_index):
            diagnostics.append(("Operand匹配",
                f"差异：SensitivityData={n_operands}, TDE非COMP={len(tde_index)}（将按较小值截断）"))

        report_info = _report_info_by_label(report_meta)
        items: list[SensitivityItem] = []

        for j, label in enumerate(reports):
            crit_idx = report_start + j
            if crit_idx >= n_criteria:
                diagnostics.append((f"跳过REPORT[{j}]{label}", f"Criteria索引{crit_idx}越界"))
                continue
            try:
                criterion = sd.GetCriterion(crit_idx)
            except Exception as e:
                diagnostics.append((f"REPORT[{j}]{label}", f"GetCriterion({crit_idx})失败: {e}"))
                continue

            ranked = []
            for sd_op_idx in range(min(n_operands, len(tde_index))):
                tde_row_idx = tde_index[sd_op_idx]
                tde_row = tde_rows[tde_row_idx]
                try:
                    effect = criterion.GetEffectByOperand(sd_op_idx)
                    change_max = _as_float(effect.EstimatedChangeMaximum)
                    change_min = _as_float(effect.EstimatedChangeMinimum)
                except Exception:
                    continue
                if not math.isfinite(change_max) and not math.isfinite(change_min):
                    continue
                # 取最大/最小中绝对值更大的作为敏感度
                abs_max = abs(change_max) if math.isfinite(change_max) else 0.0
                abs_min = abs(change_min) if math.isfinite(change_min) else 0.0
                abs_delta = max(abs_max, abs_min)
                if abs_delta <= 0:
                    continue
                # 变化量取最大变化（正值=变差方向）
                delta = change_max if abs_max >= abs_min else change_min
                ranked.append((abs_delta, delta, tde_row_idx, tde_row))

            ranked.sort(key=lambda x: x[0], reverse=True)
            meta = report_info.get(label, {})
            nominal_value = _nominal_for(label, meta, summary_nominals)
            direction = _clean(meta.get("方向"))
            for rank, (abs_delta, delta, tde_row_idx, tde_row) in enumerate(
                    ranked[:max(1, int(top_n))], start=1):
                op = _clean(tde_row.get("操作数")).upper()
                items.append(SensitivityItem(
                    report_label=label,
                    rank=rank,
                    nominal_value=nominal_value,
                    operand=op,
                    tolerance_label=_tol_label(tde_row),
                    tolerance_type=_KIND_MAP.get(op, op),
                    surface_or_element=_surface_or_element(tde_row),
                    tolerance_range=_tol_range(tde_row),
                    delta=delta,
                    abs_delta=abs_delta,
                    risk=_risk(delta, direction),
                ))

        if not items:
            return SensitivityResult(False, ztd_path, diagnostics=diagnostics,
                                     message="SensitivityData 中未读取到有效数值。")
        diagnostics.append(("输出TopN", str(top_n)))
        diagnostics.append(("输出行数", str(len(items))))
        return SensitivityResult(True, ztd_path, items=items, diagnostics=diagnostics)
    finally:
        try:
            dv.Close()
        except Exception:
            pass


def append_to_workbook(wb: Workbook, result: SensitivityResult) -> None:
    if not result.succeeded:
        raise RuntimeError(result.message or "敏感度读取失败，无法写入 Excel")
    for name in ("敏感度Top20", "敏感度诊断"):
        if name in wb.sheetnames:
            del wb[name]

    data = wb.create_sheet("敏感度Top20")
    headers = [
        "REPORT指标", "排名", "名义值", "公差项", "公差类型", "表面/元件",
        "当前公差", "值", "绝对值", "风险方向", "操作数",
    ]
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    font = Font(bold=True)
    for c, title in enumerate(headers, start=1):
        cell = data.cell(1, c, title)
        cell.fill = header_fill
        cell.font = font
        cell.alignment = Alignment(horizontal="center")
    for r, item in enumerate(result.items, start=2):
        values = [
            item.report_label,
            item.rank,
            item.nominal_value,
            item.tolerance_label,
            item.tolerance_type,
            item.surface_or_element,
            item.tolerance_range,
            item.delta,
            item.abs_delta,
            item.risk,
            item.operand,
        ]
        for c, value in enumerate(values, start=1):
            data.cell(r, c, value)
    data.freeze_panes = "A2"
    data.auto_filter.ref = data.dimensions
    widths = [24, 8, 14, 36, 14, 14, 18, 14, 14, 12, 10]
    for c, width in enumerate(widths, start=1):
        data.column_dimensions[data.cell(1, c).column_letter].width = width

    diag = wb.create_sheet("敏感度诊断")
    diag.cell(1, 1, "项目").font = font
    diag.cell(1, 2, "值").font = font
    diag.cell(1, 1).fill = header_fill
    diag.cell(1, 2).fill = header_fill
    info = [
        ("ZTD文件", result.ztd_path),
        ("数据来源", "ToleranceDataViewer.SensitivityData"),
        ("排序方式", "每个 REPORT 指标单独按绝对值排序"),
        ("保留数量", f"Top {_TOP_N}"),
        ("是否综合排序", "否，不跨 MTF/SPT/指向等不同物理指标合并"),
    ]
    rows = info + list(result.diagnostics)
    for r, (key, value) in enumerate(rows, start=2):
        diag.cell(r, 1, key)
        diag.cell(r, 2, value)
    diag.column_dimensions["A"].width = 24
    diag.column_dimensions["B"].width = 96
    if result.message:
        row = len(rows) + 2
        diag.cell(row, 1, "消息")
        diag.cell(row, 2, result.message)


def append_to_excel(result: SensitivityResult, path: str) -> str:
    if not result.succeeded:
        raise RuntimeError(result.message or "敏感度读取失败，无法写入 Excel")
    wb = load_workbook(path)
    append_to_workbook(wb, result)
    try:
        wb.save(path)
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        fallback = f"{base}_{datetime.now().strftime('%H%M%S')}{ext or '.xlsx'}"
        wb.save(fallback)
        return fallback


def export_excel(result: SensitivityResult, path: str) -> str:
    if not result.succeeded:
        raise RuntimeError(result.message or "敏感度读取失败，无法导出 Excel")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb = Workbook()
    append_to_workbook(wb, result)
    if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
        del wb["Sheet"]
    try:
        wb.save(path)
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        fallback = f"{base}_{datetime.now().strftime('%H%M%S')}{ext or '.xlsx'}"
        wb.save(fallback)
        return fallback
