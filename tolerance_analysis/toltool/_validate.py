"""_validate.py —— 公差分析配置校验逻辑。

从 pipeline.py 拆出的校验函数，职责单一：只校验不执行。
"""

from __future__ import annotations

import os

from . import excel_io, lens_scanner
from ._utils import _as_int, _yes


def _validate_paths(zmx: str, config: str) -> None:
    errors: list[str] = []
    if not os.path.isfile(zmx):
        errors.append(f"ZMX 文件不存在：{zmx}")
    if not os.path.isfile(config):
        errors.append(f"Excel 配置不存在：{config}")
    if errors:
        raise ValueError("运行前校验失败：\n" + "\n".join(f"- {e}" for e in errors))


def _validate_inputs(cfg, rp: dict) -> None:
    errors: list[str] = []
    num_runs = _as_int(rp.get("蒙特卡洛次数"), 200)
    num_to_save = _as_int(rp.get("保存数量"), 10)
    if num_runs <= 0:
        errors.append("蒙特卡洛次数必须大于 0")
    if num_to_save < 0:
        errors.append("保存数量不能小于 0")
    if num_to_save > num_runs:
        errors.append("保存数量不能大于蒙特卡洛次数")
    comp_mode_key = str(rp.get("补偿器模式") or "无").strip().replace(" ", "").lower()
    if comp_mode_key not in ("无", "none", "全部优化dls", "全部优化(dls)", "dls",
                             "全部优化od", "全部优化(od)", "od"):
        errors.append("补偿器模式仅支持：无、全部优化DLS、全部优化OD")

    valid_mfe_lines: set[int] = set()
    for row in cfg.mfe:
        op = str(row.get("操作数") or "").strip()
        if not op:
            continue
        line = row.get("行号")
        if line in (None, ""):
            errors.append(f"评价函数操作数 {op} 缺少行号")
            continue
        try:
            line_no = int(float(line))
        except (TypeError, ValueError):
            errors.append(f"评价函数行号无效：{line!r}")
            continue
        if line_no <= 0:
            errors.append(f"评价函数行号必须大于 0：{line_no}")
            continue
        valid_mfe_lines.add(line_no)
    dynamic_only = _yes(rp.get("启用动态评价项", "N")) and not valid_mfe_lines
    if not valid_mfe_lines and not dynamic_only:
        errors.append("评价函数工作表至少需要 1 行带操作数的有效行")

    report_count = 0
    for row in cfg.report:
        if not _yes(row.get("启用")):
            continue
        label = str(row.get("标签") or "").strip()
        mf_line = row.get("MF行号")
        if not label:
            errors.append("启用的 REPORT 行缺少标签")
            continue
        if mf_line in (None, ""):
            errors.append(f"REPORT {label} 缺少 MF行号")
            continue
        try:
            mf_line_no = int(float(mf_line))
        except (TypeError, ValueError):
            errors.append(f"REPORT {label} 的 MF行号无效：{mf_line!r}")
            continue
        if mf_line_no not in valid_mfe_lines:
            errors.append(f"REPORT {label} 的 MF行号 {mf_line_no} 未在评价函数中找到")
        report_count += 1
    if report_count == 0 and not dynamic_only:
        errors.append("REPORT 至少需要启用 1 个带标签和 MF行号的分项")

    if errors:
        raise ValueError("运行前校验失败：\n" + "\n".join(f"- {e}" for e in errors))


def validate_config_data(cfg):
    """只校验已读取/生成的配置内容，不连接 Zemax。"""
    _validate_inputs(cfg, cfg.run_params)
    return cfg


def validate_config(zmx: str, config: str):
    """只校验文件路径和 Excel 配置，不连接 Zemax。"""
    _validate_paths(zmx, config)
    cfg = excel_io.read_config(config)
    return validate_config_data(cfg)


def _check_zmx_fingerprint(zmx: str, rp: dict, log=print) -> None:
    """比对配置中的面数指纹与当前 zmx（公差填写向导生成的配置带此字段）。

    指纹不一致说明 zmx 面结构在生成配置后被改动，面号可能错位，直接报错；
    配置无指纹字段时跳过；zmx 解析失败只告警不阻断（后续裁剪逻辑另有兜底）。
    """
    expected = str(rp.get("面数指纹") or "").strip()
    if not expected:
        return
    try:
        actual = lens_scanner.fingerprint(lens_scanner.parse_surfaces(zmx))
    except Exception as e:
        log(f"面数指纹校验：读取 ZMX 失败，跳过校验。{type(e).__name__}: {e}")
        return
    if actual != expected:
        raise ValueError(
            "运行前校验失败：\n"
            f"- 镜头文件面结构与配置生成时不一致（面号可能已错位）。\n"
            f"  配置指纹: {expected}\n"
            f"  当前指纹: {actual}\n"
            f"  请用公差填写向导重新生成配置，或确认选择了正确的 zmx。")
    log("面数指纹校验通过：zmx 面结构与配置生成时一致。")