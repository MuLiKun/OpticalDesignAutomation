"""_nominals.py —— 评价函数名义值读取与 MFE 辅助函数。

从 pipeline.py 拆出，负责 MFE 行操作数的递归计算、编辑器值读取、
REPORT 名义值行生成、以及通用 MFE 行构造工具。
"""

from __future__ import annotations

import math

from ._utils import _yes, _fmt_num


def mfe_row_map(mfe_rows: list[dict]) -> dict[int, dict]:
    """MFE 行列表 → {行号: 行} 映射。"""
    out: dict[int, dict] = {}
    for row in mfe_rows:
        try:
            line_no = int(float(row.get("行号")))
        except (TypeError, ValueError):
            continue
        out[line_no] = row
    return out


def _row_param(row: dict, name: str, default: float = 0) -> float:
    """从 MFE 行中安全读取 param 值。"""
    value = row.get(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_mfe_row_nominal(zos_system, rows: dict[int, dict], line_no: int,
                         cache: dict[int, float]) -> float:
    """递归计算 MFE 行在指定操作数下的名义值。"""
    if line_no in cache:
        return cache[line_no]
    row = rows.get(line_no)
    if not row:
        return float("nan")
    op = str(row.get("操作数") or "").strip().upper()
    try:
        if op == "CONS":
            value = float(row.get("目标") or 0)
        elif op == "DIFF":
            value = (calc_mfe_row_nominal(zos_system, rows, int(_row_param(row, "Param1")), cache)
                     - calc_mfe_row_nominal(zos_system, rows, int(_row_param(row, "Param2")), cache))
        elif op == "DIVI":
            denominator = calc_mfe_row_nominal(zos_system, rows, int(_row_param(row, "Param2")), cache)
            value = (calc_mfe_row_nominal(zos_system, rows, int(_row_param(row, "Param1")), cache)
                     / denominator) if denominator else float("nan")
        elif op == "PROB":
            value = calc_mfe_row_nominal(zos_system, rows, int(_row_param(row, "Param1")), cache)
            factor = _row_param(row, "Param3", 1)
            value *= factor
        elif op == "BLNK":
            value = 0.0
        else:
            value = _operand_value(
                zos_system, op,
                _row_param(row, "Param1"), _row_param(row, "Param2"),
                _row_param(row, "Param3"), _row_param(row, "Param4"),
                _row_param(row, "Param5"), _row_param(row, "Param6"),
                _row_param(row, "Param7"), _row_param(row, "Param8"))
    except Exception:
        value = float("nan")
    cache[line_no] = value
    return value


def mfe_editor_value(zos_system, line_no: int) -> float:
    """读取 MFE 编辑器指定行「Value」列的当前计算值（评价函数名义值）。"""
    import ZOSAPI

    mfe = zos_system.MFE
    row = mfe.GetOperandAt(line_no)
    merit_column = ZOSAPI.Editors.MFE.MeritColumn
    for name in ("Value", "CurrentValue"):
        col = getattr(merit_column, name, None)
        if col is None:
            continue
        try:
            return float(row.GetOperandCell(col).Value)
        except Exception:
            continue
    return float(getattr(row, "Value"))


def read_report_nominals(zos_system, mfe_rows: list[dict], report_rows: list[dict]) -> list[dict]:
    """读取 REPORT 各分项的名义值（评价函数值）。"""
    out: list[dict] = []
    rows = mfe_row_map(mfe_rows)
    cache: dict[int, float] = {}
    # 触发一次评价函数计算，确保 Value 列已刷新。
    for method in ("CalculateMeritFunction", "CalculateMeritFunctionAndUpdateOperands"):
        fn = getattr(zos_system.MFE, method, None)
        if callable(fn):
            try:
                fn()
                break
            except Exception:
                continue
    for row in report_rows:
        if not _yes(row.get("启用")) or not row.get("标签"):
            continue
        new_row = dict(row)
        value = float("nan")
        try:
            line_no = int(float(row.get("MF行号")))
        except (TypeError, ValueError):
            line_no = None
        if line_no is not None:
            try:
                value = mfe_editor_value(zos_system, line_no)
            except Exception:
                value = float("nan")
            if not math.isfinite(value):
                try:
                    value = calc_mfe_row_nominal(zos_system, rows, line_no, cache)
                except Exception:
                    value = float("nan")
        if math.isfinite(value):
            new_row["名义值"] = value
            new_row["名义值来源"] = "MFE_OPERAND"
        else:
            new_row["名义值"] = ""
        out.append(new_row)
    return out


def _operand_value(zos_system, op: str, *params: float) -> float:
    """通过 Zemax API 计算 MFE 操作数的值。"""
    import ZOSAPI

    values = list(params[:8])
    while len(values) < 8:
        values.append(0)
    op_enum = getattr(ZOSAPI.Editors.MFE.MeritOperandType, op)
    return float(zos_system.MFE.GetOperandValue(op_enum, *values))


def next_mfe_line(cfg) -> int:
    """从配置中获取下一个可用的 MFE 行号。"""
    lines: list[int] = []
    for row in cfg.mfe:
        try:
            lines.append(int(float(row.get("行号"))))
        except (TypeError, ValueError):
            pass
    return (max(lines) + 1) if lines else 2


def mfe_row(line_no: int, op: str, *, target=0, weight=0,
            comment: str = "", field=None, **params) -> dict:
    """构造一条 MFE 行数据字典。"""
    row = {
        "行号": line_no,
        "操作数": op,
        "目标": target,
        "权重": weight,
        "注释": comment,
        "目标归一化视场": "" if field is None else field,
        "视场映射说明": "标准模板动态生成",
        "归一化视场": "" if field is None else field,
    }
    for i in range(1, 9):
        row[f"Param{i}"] = params.get(f"Param{i}", "")
    return row


def report_labels(cfg) -> set[str]:
    """从配置中读取所有 REPORT 标签。"""
    return {str(row.get("标签") or "").strip() for row in cfg.report}