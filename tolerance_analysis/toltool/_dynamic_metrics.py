"""_dynamic_metrics.py —— 运行期动态评价项生成。

从 pipeline.py 拆出，负责标准模板/高级 Excel 模式下动态追加
中心指向偏移、指向角、焦距偏移百分比、FOV 等评价函数项。
"""

from __future__ import annotations

import copy

from ._utils import _yes, _as_int, _field_label
from ._nominals import _operand_value, next_mfe_line, mfe_row, report_labels


def _pointing_angle_fields(template_name: str) -> tuple[float, ...]:
    """指向角评价的目标视场（归一化 Hy）。

    标准分析沿用标准视场 F0/F0.5/F0.9/F-0.9；
    完整视场分析只取正视场（含 0 视场）到最大 F1。
    """
    if str(template_name or "").strip() == "完整视场分析":
        return (0, 0.25, 0.5, 0.7, 0.9, 1)
    return (0, 0.5, 0.9, -0.9)


def append_standard_dynamic_metrics(zos_system, cfg, rp: dict, center_wave: int,
                                    log=print):
    """运行期动态追加中心指向偏移、指向角、焦距偏移、FOV 等评价函数项。

    标准模板默认启用；高级 Excel 模式可通过运行参数「启用动态评价项=Y」开启。
    """
    standard_dynamic = str(rp.get("分析模式") or "").strip() == "标准模板"
    if not standard_dynamic and not _yes(rp.get("启用动态评价项", "N")):
        return cfg
    if center_wave <= 0:
        log("标准模板动态评价项：中心波长号无效，已跳过中心指向偏移、焦距偏移百分比和 FOV。")
        return cfg

    new_cfg = copy.deepcopy(cfg)
    labels = report_labels(new_cfg)
    line = next_mfe_line(new_cfg)
    added: list[str] = []

    if _yes(rp.get("启用中心指向偏移", "N")) and not {
        "POINTING_DY_F0_mm", "POINTING_DX_F0_mm"}.issubset(labels):
        field_no = _as_int(rp.get("中心指向视场号"), 1)
        if field_no <= 0:
            field_no = 1
        ceny0 = _operand_value(zos_system, "CENY", 16, center_wave, field_no, 0, 5)
        cenx0 = _operand_value(zos_system, "CENX", 16, center_wave, field_no, 0, 5)

        new_cfg.mfe.append(mfe_row(line, "BLNK", comment="接收指向偏移 F0/mm")); line += 1
        ceny_line = line
        new_cfg.mfe.append(mfe_row(line, "CENY", comment="CENY_F0_current", field=0,
                                    Param1=16, Param2=center_wave, Param3=field_no,
                                    Param4=0, Param5=5)); line += 1
        cenx_line = line
        new_cfg.mfe.append(mfe_row(line, "CENX", comment="CENX_F0_current", field=0,
                                    Param1=16, Param2=center_wave, Param3=field_no,
                                    Param4=0, Param5=5)); line += 1
        cons_y_line = line
        new_cfg.mfe.append(mfe_row(line, "CONS", target=ceny0, comment="CENY_F0_nominal")); line += 1
        cons_x_line = line
        new_cfg.mfe.append(mfe_row(line, "CONS", target=cenx0, comment="CENX_F0_nominal")); line += 1
        diff_y_line = line
        new_cfg.mfe.append(mfe_row(line, "DIFF", comment="POINTING_DY_F0_mm",
                                    Param1=ceny_line, Param2=cons_y_line)); line += 1
        diff_x_line = line
        new_cfg.mfe.append(mfe_row(line, "DIFF", comment="POINTING_DX_F0_mm",
                                    Param1=cenx_line, Param2=cons_x_line)); line += 1
        new_cfg.report.extend([
            {"启用": "Y", "标签": "POINTING_DY_F0_mm", "MF行号": diff_y_line, "方向": "小", "单位": "mm"},
            {"启用": "Y", "标签": "POINTING_DX_F0_mm", "MF行号": diff_x_line, "方向": "小", "单位": "mm"},
        ])
        added.extend(["POINTING_DY_F0_mm", "POINTING_DX_F0_mm"])
        log(f"中心指向偏移 F0：视场号 {field_no}，CENY0={ceny0:.12g}，CENX0={cenx0:.12g}")

    template_name = str(rp.get("标准模板") or "").strip()
    pointing_angle_fields = _pointing_angle_fields(template_name)
    angle_labels = {f"POINTING_ANGLE_{_field_label(field)}_deg" for field in pointing_angle_fields}
    if _yes(rp.get("启用指向角", "Y")) and not angle_labels.issubset(report_labels(new_cfg)):
        image_surface = max(0, int(zos_system.LDE.NumberOfSurfaces) - 1)
        new_cfg.mfe.append(mfe_row(line, "BLNK", comment="POINTING_ANGLE_deg")); line += 1
        appended_labels: list[str] = []
        for field in pointing_angle_fields:
            label = f"POINTING_ANGLE_{_field_label(field)}_deg"
            if label in report_labels(new_cfg):
                continue
            raid_line = line
            nominal = _operand_value(zos_system, "RAID", image_surface, center_wave,
                                     0, field, 0, 0)
            new_cfg.mfe.append(mfe_row(line, "RAID", comment=f"{label}_current", field=field,
                                        Param1=image_surface, Param2=center_wave,
                                        Param3=0, Param4=field, Param5=0, Param6=0)); line += 1
            cons_line = line
            new_cfg.mfe.append(mfe_row(line, "CONS", target=nominal,
                                        comment=f"{label}_nominal", field=field)); line += 1
            diff_line = line
            new_cfg.mfe.append(mfe_row(line, "DIFF", comment=label, field=field,
                                        Param1=raid_line, Param2=cons_line)); line += 1
            new_cfg.report.append({
                "启用": "Y",
                "标签": label,
                "MF行号": diff_line,
                "方向": "",
                "单位": "deg",
            })
            appended_labels.append(label)
        if appended_labels:
            added.extend(appended_labels)
            log(f"指向角：使用像面 {image_surface} 面，已追加 {len(appended_labels)} 项。")

    if _yes(rp.get("启用焦距偏移百分比", "N")) and "EFL_DELTA_PCT" not in report_labels(new_cfg):
        efl0 = _operand_value(zos_system, "EFFL", center_wave)
        if abs(efl0) < 1e-15:
            log("焦距偏移百分比：名义 EFL 接近 0，已跳过 EFL_DELTA_PCT。")
        else:
            new_cfg.mfe.append(mfe_row(line, "BLNK", comment="EFL")); line += 1
            efl_line = line
            new_cfg.mfe.append(mfe_row(line, "EFFL", comment="EFFL_current",
                                        Param1=center_wave)); line += 1
            cons_line = line
            new_cfg.mfe.append(mfe_row(line, "CONS", target=efl0, comment="EFFL_nominal")); line += 1
            diff_line = line
            new_cfg.mfe.append(mfe_row(line, "DIFF", comment="EFL_delta",
                                        Param1=efl_line, Param2=cons_line)); line += 1
            divi_line = line
            new_cfg.mfe.append(mfe_row(line, "DIVI", comment="EFL_delta_ratio",
                                        Param1=diff_line, Param2=cons_line)); line += 1
            new_cfg.mfe.append(mfe_row(line, "BLNK", comment="DELTA EFL")); line += 1
            pct_line = line
            new_cfg.mfe.append(mfe_row(line, "PROB", comment="EFL_DELTA_PCT",
                                        Param1=divi_line, Param3=100)); line += 1
            new_cfg.report.append({
                "启用": "Y",
                "标签": "EFL_DELTA_PCT",
                "MF行号": pct_line,
                "方向": "小",
                "单位": "%",
            })
            added.append("EFL_DELTA_PCT")
            log(f"焦距偏移百分比：EFFL0={efl0:.12g}，已追加 EFL_DELTA_PCT。")

    if _yes(rp.get("启用FOV", "Y")) and "FOV_Y_deg" not in report_labels(new_cfg):
        product_type = str(rp.get("产品类型") or "").strip().upper()
        if product_type == "TX":
            surface = max(0, int(zos_system.LDE.NumberOfSurfaces) - 1)
            surface_desc = "像面"
        else:
            surface = 0
            surface_desc = "物面"
        new_cfg.mfe.append(mfe_row(line, "BLNK", comment=f"FOV_Y_{product_type or 'RX'}_deg")); line += 1
        reac_pos_line = line
        new_cfg.mfe.append(mfe_row(line, "REAC", comment="FOV_HY_POS_REAC",
                                    Param1=surface, Param2=center_wave,
                                    Param3=0, Param4=1, Param5=0, Param6=0)); line += 1
        reac_neg_line = line
        new_cfg.mfe.append(mfe_row(line, "REAC", comment="FOV_HY_NEG_REAC",
                                    Param1=surface, Param2=center_wave,
                                    Param3=0, Param4=-1, Param5=0, Param6=0)); line += 1
        acos_pos_line = line
        new_cfg.mfe.append(mfe_row(line, "ACOS", comment="FOV_HY_POS_deg",
                                    Param1=reac_pos_line, Param2=1)); line += 1
        acos_neg_line = line
        new_cfg.mfe.append(mfe_row(line, "ACOS", comment="FOV_HY_NEG_deg",
                                    Param1=reac_neg_line, Param2=1)); line += 1
        fov_line = line
        new_cfg.mfe.append(mfe_row(line, "SUMM", comment="FOV_Y_deg",
                                    Param1=acos_pos_line, Param2=acos_neg_line)); line += 1
        new_cfg.report.append({
            "启用": "Y",
            "标签": "FOV_Y_deg",
            "MF行号": fov_line,
            "方向": "小",
            "单位": "deg",
        })
        added.append("FOV_Y_deg")
        log(f"FOV_Y：{product_type or 'RX'} 使用{surface_desc} {surface} 面，已追加 FOV_Y_deg。")

    if added:
        log("标准模板动态评价项：已追加 " + ", ".join(added))
    return new_cfg