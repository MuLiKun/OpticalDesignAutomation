"""_run_utils.py —— 运行目录、JSON 日志、视场映射报告等工具函数。

从 pipeline.py 拆出，负责输出目录创建、JSON 快照、日志多路输出、
视场映射报告生成等 IO 工具。
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from ._utils import _safe_name, _fmt_num, _yes, _enum_name


def _insert_strategy_label(value) -> str:
    text = str(value or "").strip()
    if _yes(text):
        return "自动插入"
    if not text:
        return "禁用"
    return text


def field_mapping_report_lines(result) -> list[str]:
    """生成视场映射报告/预览文本行。"""
    missing = [item for item in result.final_matches if item.need_insert]
    inserted_targets = {item.target_normalized for item in result.inserted_fields}
    matched_count = len(result.final_matches) - len(missing)
    title = "视场映射预览" if getattr(result, "is_preview", False) else "视场映射报告"
    if getattr(result, "is_preview", False) and result.inserted_fields:
        title += "（已模拟补齐）"
    if result.inserted_fields:
        conclusion = f"已匹配 {matched_count}/{len(result.targets)}，本次模拟补齐 {len(result.inserted_fields)}"
    else:
        conclusion = f"已匹配 {matched_count}/{len(result.targets)}，需补齐 {len(missing)}"
    field_by_no = {field.field_no: field for field in result.final_fields}
    lines = [
        title,
        f"结论: {conclusion}",
        f"阈值: {result.threshold:g}；插入策略: {_insert_strategy_label(result.insert_strategy)}",
        "",
        "目标      视场号        X        Y    归一化    偏差  来源/状态",
    ]
    for item in result.final_matches:
        if item.need_insert:
            status = "仍需补齐"
        elif item.target_normalized in inserted_targets:
            status = "已补齐"
        else:
            status = "已有"
        field = field_by_no.get(item.field_no)
        x = _fmt_num(field.x if field else None)
        y = _fmt_num(field.y if field else None)
        lines.append(
            f"{item.report_label:<8} {str(item.field_no or '-'):>5}  "
            f"{x:>7}  {y:>7}  {_fmt_num(item.actual_normalized):>7}  "
            f"{_fmt_num(item.delta):>6}  {status}")
    if not getattr(result, "is_preview", False):
        lines.extend([
            "",
            f"已插入缺失视场: {len(result.inserted_fields)}",
            f"已改写 MFE: {result.mfe_updates} 行",
            f"已改写 REPORT: {result.report_updates} 项",
        ])
    if missing:
        lines.append("")
        lines.append("需补齐目标: " + ", ".join(item.report_label for item in missing))
    elif result.messages and not getattr(result, "is_preview", False):
        lines.append("")
        lines.extend(str(msg) for msg in result.messages)
    return lines


def log_field_mapping(result, log) -> None:
    """将视场映射结果输出到日志。"""
    for line in field_mapping_report_lines(result):
        if line:
            log(line)


def write_field_mapping_report(path: str, result) -> None:
    """将视场映射报告写入文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(field_mapping_report_lines(result)) + "\n")


def log_to_file(path: str, message: str) -> None:
    """追加消息到日志文件。"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(str(message) + "\n")


def tee_logger(log, log_path: str):
    """创建同时写入文件和控制台的多路日志函数。"""
    def emit(message: str) -> None:
        log_to_file(log_path, message)
        log(message)
    return emit


def make_run_dir(zmx: str, outdir: str | None) -> tuple[str, str]:
    """创建运行结果目录，返回 (父目录, 结果目录)。"""
    src_base = os.path.splitext(os.path.basename(zmx))[0]
    parent = os.path.abspath(outdir) if outdir \
        else os.path.dirname(os.path.abspath(zmx))
    os.makedirs(parent, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(parent, f"公差分析_{_safe_name(src_base)}_{stamp}")
    suffix = 1
    unique_dir = run_dir
    while os.path.exists(unique_dir):
        suffix += 1
        unique_dir = f"{run_dir}_{suffix}"
    os.makedirs(unique_dir, exist_ok=False)
    return parent, unique_dir


def _json_default(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def write_json(path: str, data: dict) -> None:
    """写入 JSON 快照文件。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=_json_default)


def read_tde_meta(zos_system) -> list[dict]:
    """读取当前 TDE 的所有操作数元数据。"""
    tde = zos_system.TDE
    rows: list[dict] = []
    for i in range(1, int(tde.NumberOfOperands) + 1):
        r = tde.GetOperandAt(i)
        op = _enum_name(getattr(r, "Type", ""))
        if not op or op == "BLNK":
            continue
        row = {"行号": i, "操作数": op}
        for name in ("Param1", "Param2", "Min", "Max", "Comment"):
            try:
                row[name] = getattr(r, name)
            except Exception:
                row[name] = ""
        if op == "COMP":
            comment = str(row.get("Comment") or "").strip()
            surf = row.get("Param1")
            suffix = f"_S{surf}" if str(surf).strip() else ""
            row["标签"] = comment or f"COMP{suffix}"
            row["方向"] = ""
            row["单位"] = "mm"
        rows.append(row)
    return rows