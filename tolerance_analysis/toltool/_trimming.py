"""_trimming.py —— 标准模板镜头面范围裁剪逻辑。

从 pipeline.py 拆出，负责 TX/RX 模式下按滤光片位置自动裁剪公差面范围。
"""

from __future__ import annotations

from . import lens_scanner
from ._utils import _as_int, _yes


def rx_start_after_front_plate(surfaces: list[lens_scanner.SurfaceInfo],
                               start: int, stop: int) -> int:
    """RX：跳过物面后到镜头之间连续的双面平板玻璃（不限材料）。"""
    by_no = {s.surface: s for s in surfaces}
    cur = int(start)
    while cur + 1 <= stop:
        s0 = by_no.get(cur)
        s1 = by_no.get(cur + 1)
        if s0 is None or s1 is None or not (s0.is_plane and s1.is_plane):
            break
        if not s0.has_glass:
            break
        cur += 2
    return cur


def wizard_current_range(cfg) -> tuple[int, int]:
    """从配置的 tol_wizard 中读取公差面起止范围。"""
    starts, stops = [], []
    for row in cfg.tol_wizard:
        if not _yes(row.get("启用")):
            continue
        s0 = _as_int(row.get("起始面"), 0)
        s1 = _as_int(row.get("结束面"), 0)
        if s0 > 0:
            starts.append(s0)
        if s1 > 0:
            stops.append(s1)
    return (min(starts) if starts else 1, max(stops) if stops else 0)


def set_wizard_range(cfg, start: int, stop: int) -> None:
    """将公差面起止范围写入配置的 tol_wizard 各行。"""
    for row in cfg.tol_wizard:
        if _yes(row.get("启用")):
            row["起始面"] = int(start)
            row["结束面"] = int(stop)


def apply_standard_surface_scope_from_zmx(zmx: str, cfg, rp: dict, log=print) -> None:
    """标准模板全部面=否时，按 TX/RX 及滤光片位置自动裁剪公差面范围。"""
    if str(rp.get("分析模式") or "").strip() != "标准模板":
        return
    if _yes(rp.get("全部面公差分析", "Y")):
        return
    if str(rp.get("标准模板") or "").strip() != "标准分析":
        log("标准模板镜头面裁剪：全部面=否 仅支持『标准分析』模板，当前模板已按全部面生成。")
        return
    product_type = str(rp.get("产品类型") or "RX").strip().upper()
    if product_type not in ("TX", "RX"):
        log(f"标准模板镜头面裁剪：产品类型 {product_type!r} 无效（仅支持 TX/RX），已按全部面生成。")
        return
    try:
        surfaces = lens_scanner.parse_surfaces(zmx)
    except Exception as e:
        log(f"标准模板镜头面裁剪：读取 ZMX 失败，已按全部面生成。{type(e).__name__}: {e}")
        return
    if not surfaces:
        log("标准模板镜头面裁剪：未从镜头文件读取到面数据（可能为 .zos 二进制或非标准格式），已按全部面生成。")
        return
    filters = [s.surface for s in surfaces if s.is_filter]
    if not filters:
        log("标准模板镜头面裁剪：未找到 AF32ECO/D263TECO 滤光片，已按全部面生成。")
        return
    base_start, base_stop = wizard_current_range(cfg)
    if base_stop <= 0:
        log("标准模板镜头面裁剪：当前公差范围无效，已按全部面生成。")
        return
    if product_type == "TX":
        boundary = max(filters)
        start, stop = boundary + 2, base_stop
        reason = f"TX 取最后一个滤光片 {boundary} 面之后"
    else:
        boundary = min(filters)
        start = rx_start_after_front_plate(surfaces, base_start, boundary - 1)
        stop = boundary - 1
        reason = f"RX 取第一个滤光片 {boundary} 面之前"
    start = max(base_start, start)
    stop = min(base_stop, stop)
    if start > stop:
        log(f"标准模板镜头面裁剪：{reason} 后范围无效({start}-{stop})，已按全部面生成。")
        return
    set_wizard_range(cfg, start, stop)
    log(f"标准模板镜头面裁剪：全部面=否，{reason}，最终公差范围 {start}-{stop}。")


def fill_auto_standard_surfaces(zos_system, cfg, rp: dict, log=print) -> None:
    """标准模板模式下，自动填充未设置结束面的公差行为像面前一面。"""
    if str(rp.get("分析模式") or "").strip() != "标准模板":
        return
    try:
        end_surface = max(1, int(zos_system.LDE.NumberOfSurfaces) - 2)
    except (AttributeError, TypeError, ValueError) as e:
        log(f"自动读取镜头面数失败，保留 Excel 中的公差范围: {e}")
        return
    changed = False
    for row in cfg.tol_wizard:
        if _as_int(row.get("结束面"), 0) <= 0:
            row["结束面"] = end_surface
            changed = True
    if changed:
        log(f"标准模板自动公差范围: 1-{end_surface}")