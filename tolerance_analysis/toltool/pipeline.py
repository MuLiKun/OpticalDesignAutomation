"""pipeline.py —— 公差分析的可复用流程。

GUI 与命令行入口共享这里的核心流程：
连接 → 建 TDE → 建 MFE → 建 TSC → Save → 跑蒙卡。

职责单一的辅助函数已拆分到子模块：
  _nominals.py     MFE 名义值计算与行操作
  _trimming.py     标准模板镜头面范围裁剪
  _dynamic_metrics.py  运行期动态评价项生成
  _run_utils.py    目录/日志/JSON/视场映射报告
  _validate.py     配置校验
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass

from . import (zos_connect, excel_io, tde_builder, mfe_builder,
               tsc_builder, tol_runner, field_mapping, current_settings,
               sensitivity_reader)
from ._utils import _as_int, _yes, _num, _safe_name
from ._validate import (_check_zmx_fingerprint, _validate_inputs,
                        validate_config, validate_config_data)
from ._nominals import read_report_nominals
from ._trimming import (apply_standard_surface_scope_from_zmx,
                        fill_auto_standard_surfaces)
from ._dynamic_metrics import append_standard_dynamic_metrics
from ._run_utils import (make_run_dir, write_json, tee_logger, read_tde_meta,
                         write_field_mapping_report, log_field_mapping)


@dataclass
class Prepared:
    sess: object
    cfg: object
    rp: dict
    base: str
    outdir: str
    tsc_path: str
    mf_path: str
    n_tde: int
    n_mfe: int
    n_report: int
    lens_dir: str = ""
    parent_outdir: str = ""
    source_zmx: str = ""
    config_path: str = ""
    log_path: str = ""
    run_config_path: str = ""
    field_mapping_report_path: str = ""
    report_meta: list | None = None
    tde_meta: list | None = None


def prepare_session(zmx: str, config: str, outdir: str | None = None,
                    connect: str = "extension", log=print,
                    zos_dir: str | None = None,
                    use_current_settings: bool = False,
                    current_args: dict | None = None) -> Prepared:
    """连接 Zemax、打开工作副本并完成 TSC/Save 准备。

    默认按 Excel 重建 TDE/MFE；use_current_settings=True 时保留当前 TDE/MFE，
    只从工作副本当前 MFE 自动生成 REPORT/TSC。
    """
    if use_current_settings:
        if not os.path.isfile(zmx):
            raise ValueError(f"运行前校验失败：\n- ZMX 文件不存在：{zmx}")
        cfg = None
        rp = {}
    else:
        cfg = validate_config(zmx, config)
        rp = cfg.run_params

    parent_out, out = make_run_dir(zmx, outdir)
    log_path = os.path.join(out, "run.log")
    log = tee_logger(log, log_path)
    log(f"结果目录: {out}")
    log(f"日志文件: {log_path}")

    _check_zmx_fingerprint(zmx, rp, log=log)

    standard_mode = str(rp.get("分析模式") or "").strip() == "标准模板"
    center_wave = _as_int(rp.get("中心波长号"), 0)
    center_wave_auto = (standard_mode or _yes(rp.get("启用动态评价项", "N"))) \
        and center_wave <= 0
    comp_surface = _as_int(rp.get("后焦补偿面"), 0)
    comp_min = _num(rp.get("补偿Min"))
    comp_max = _num(rp.get("补偿Max"))
    comp_freq = _num(rp.get("补偿线对"), 34.0)
    comp_mode = str(rp.get("补偿器模式") or "无").strip()
    comp_off = str(comp_mode).replace(" ", "").lower() in ("无", "none", "")
    comp_on = not comp_off

    sess = zos_connect.ZosSession(zos_dir=zos_dir)
    log(f"ZOS 目录: {sess.zos_dir}")
    sess.connect(mode=connect)
    if connect == "standalone":
        log("已启动 Zemax 独立实例（即将载入下面的工作副本）")
    else:
        log(f"已连接交互扩展: {sess.sys.SystemFile}")

    src_base, src_ext = os.path.splitext(os.path.basename(zmx))
    safe_src_base = _safe_name(src_base)
    if safe_src_base != src_base:
        log(f"提示：镜头文件名包含空格或特殊字符，Zemax 输出前缀将使用安全名称: {safe_src_base}")
    copy_path = os.path.join(out, f"{safe_src_base}_tol{src_ext}")
    copy = sess.open_as_copy(zmx, copy_path=copy_path)
    log(f"工作副本: {copy}")

    if use_current_settings:
        current_args = current_args or {}
        cfg = current_settings.build_config_from_current_mfe(
            sess.sys,
            num_runs=_as_int(current_args.get("num_runs"), 20),
            num_to_save=_as_int(current_args.get("num_to_save"), 0),
            comp_mode=str(current_args.get("comp_mode") or "无"),
            save_worst_best=_yes(current_args.get("save_worst_best")),
            report_filter=current_args.get("report_filter"))
        rp = cfg.run_params
        _validate_inputs(cfg, rp)
        standard_mode = False
        center_wave = _as_int(rp.get("中心波长号"), 0)
        center_wave_auto = False
        comp_surface = _as_int(rp.get("后焦补偿面"), 0)
        comp_min = _num(rp.get("补偿Min"))
        comp_max = _num(rp.get("补偿Max"))
        comp_freq = _num(rp.get("补偿线对"), 34.0)
        comp_mode = str(rp.get("补偿器模式") or "无").strip()
        comp_off = str(comp_mode).replace(" ", "").lower() in ("无", "none", "")
        comp_on = not comp_off
        has_tde_comp = current_settings.tde_has_comp(sess.sys)
        if comp_on and not has_tde_comp:
            log("当前 TDE 无 COMP 操作数，强制关闭补偿器优化（TSC 不写 OPTIMIZE 行）。")
            comp_mode = "无"
            comp_off = True
            comp_on = False
            rp["补偿器模式"] = "无"
        elif comp_on and has_tde_comp:
            comp_freq = current_settings.detect_comp_freq_from_mfe(cfg)
            if comp_freq and comp_freq > 0:
                rp["补偿线对"] = comp_freq
                log(f"当前 TDE 含 COMP，补偿 MF 线对取自 MFE MTF 操作数: {comp_freq} lp/mm")
            else:
                log("当前 TDE 含 COMP，补偿 MF 线对将使用默认值")
        log("当前设置模式：已读取当前 MFE，保留当前 TDE。")
        for msg in current_settings.summarize_config(cfg):
            log(msg)

    lens_info = sess.read_lens_info()
    is_tx_standard = standard_mode and str(rp.get("产品类型") or "").strip().upper() == "TX"
    if is_tx_standard and comp_on:
        comp_mode = "无"
        comp_off = True
        comp_on = False
        comp_surface = 0
        rp["补偿器模式"] = "无"
        rp["后焦补偿面"] = ""
        log("TX 标准模板：不做后焦补偿，不写 TSC 优化。")
    if comp_on and comp_surface <= 0 and not use_current_settings:
        comp_surface = max(1, int(sess.sys.LDE.NumberOfSurfaces) - 2)
        rp["后焦补偿面"] = comp_surface
        log(f"未填后焦补偿面，已自动设置为像面前一面: {comp_surface}")
    add_comp_operand = comp_on and comp_surface > 0 and not use_current_settings

    if center_wave_auto and lens_info.primary_wave > 0:
        center_wave = lens_info.primary_wave
        rp["中心波长号"] = center_wave
        for row in cfg.mfe:
            op = str(row.get("操作数") or "").strip().upper()
            if op in ("RSCE", "GENC", "GMTT", "GMTS", "GMTA") \
                    and _as_int(row.get("Param2"), 0) <= 0:
                row["Param2"] = center_wave
        log(f"已自动使用主波长号: {center_wave}")

    fill_auto_standard_surfaces(sess.sys, cfg, rp, log=log)
    apply_standard_surface_scope_from_zmx(zmx, cfg, rp, log=log)

    cfg, field_mapping_result = field_mapping.process(sess.sys, cfg, rp, log=log)
    field_mapping_report_path = ""
    if field_mapping_result.enabled:
        log(f"已启用视场映射：目标 {len(field_mapping_result.targets)} 个，"
            f"阈值 {field_mapping_result.threshold:g}，插入策略={field_mapping_result.insert_strategy}")
        log_field_mapping(field_mapping_result, log)
        field_mapping_report_path = os.path.join(out, "field_mapping.txt")
        try:
            write_field_mapping_report(field_mapping_report_path, field_mapping_result)
            log(f"视场映射报告: {field_mapping_report_path}")
        except Exception as e:
            log(f"保存视场映射报告失败(忽略): {e}")
            field_mapping_report_path = ""
    else:
        log("视场映射：未启用")

    cfg = append_standard_dynamic_metrics(sess.sys, cfg, rp, center_wave, log=log)

    used_excel_path = os.path.join(out, "used_excel.xlsx")
    try:
        if use_current_settings:
            current_settings.write_config_excel(used_excel_path, cfg, overwrite=True)
        else:
            excel_io.write_config_snapshot(config, used_excel_path, cfg)
        log(f"Excel 配置快照: {used_excel_path}")
    except Exception as e:
        log(f"保存 Excel 配置快照失败(忽略): {e}")

    base = os.path.splitext(os.path.basename(copy))[0]
    lens_dir = os.path.dirname(os.path.abspath(copy))

    test_wl = 0.0
    if center_wave > 0:
        try:
            test_wl = float(sess.sys.SystemData.Wavelengths
                            .GetWavelength(center_wave).Wavelength)
        except Exception as e:
            log(f"读取测试波长失败(忽略): {e}")

    if use_current_settings:
        n_tde = 0
        log("当前设置模式：跳过 TDE 重建，保留镜头文件现有 TDE。")
        n_mfe = len(cfg.mfe)
        mf_path = mfe_builder.default_mf_path(sess.sys, base)
        mfe_builder.save_mf(sess.sys, mf_path)
        log(f"当前设置模式：已保存当前 MFE: {n_mfe} 行  → {mf_path}")
    else:
        comp_surface_eff = comp_surface if add_comp_operand else 0
        n_tde = tde_builder.build_and_write(
            sess.sys, cfg.tol_wizard, cfg.tol_detail,
            center_wave=center_wave, test_wavelength_um=test_wl,
            comp_surface=comp_surface_eff, comp_min=comp_min, comp_max=comp_max)
        if add_comp_operand:
            log(f"已写入 TDE 公差: {n_tde} 条（含后焦补偿面 {comp_surface}，测试波长 {test_wl}um）")
        elif comp_off and comp_surface > 0:
            log(f"已写入 TDE 公差: {n_tde} 条（补偿器模式=无，已忽略后焦补偿面 {comp_surface}，测试波长 {test_wl}um）")
        else:
            log(f"已写入 TDE 公差: {n_tde} 条（不加 COMP 操作数，测试波长 {test_wl}um）")
        n_mfe, mf_path = mfe_builder.build_and_save(sess.sys, cfg.mfe, base)
        log(f"已重建 MFE: {n_mfe} 行  → {mf_path}")

    report_meta = read_report_nominals(sess.sys, cfg.mfe, cfg.report)
    nominal_count = sum(1 for row in report_meta if row.get("名义值") not in (None, ""))
    if nominal_count:
        preview = ", ".join(
            f"{row.get('标签')}={row.get('名义值')}"
            for row in report_meta[:5]
            if row.get("名义值") not in (None, ""))
        suffix = f" 示例：{preview}" if preview else ""
        log(f"已读取 REPORT 名义值：{nominal_count}/{len(report_meta)} 项。{suffix}")
    else:
        log(f"警告：REPORT 名义值全部为空（0/{len(report_meta)}），"
            f"评价函数 Value 列可能未计算，Excel 名义值行将留空。")

    comp_mf_name = None
    if comp_on:
        wave_for_mf = center_wave if center_wave > 0 else (lens_info.primary_wave or 2)
        thick_min = thick_max = None
        if comp_surface > 0 and (comp_min is not None or comp_max is not None):
            try:
                t0 = float(sess.sys.LDE.GetSurfaceAt(int(comp_surface)).Thickness)
                thick_min = None if comp_min is None else t0 + float(comp_min)
                thick_max = None if comp_max is None else t0 + float(comp_max)
                log(f"补偿 MF 厚度软约束：面 {comp_surface} 名义厚度 {t0:g}，"
                    f"范围 [{'-' if thick_min is None else f'{thick_min:g}'}, "
                    f"{'-' if thick_max is None else f'{thick_max:g}'}]（CTGT/CTLT）")
            except Exception as e:
                log(f"补偿 MF 厚度软约束：读取面 {comp_surface} 名义厚度失败，"
                    f"已跳过约束。{type(e).__name__}: {e}")
                thick_min = thick_max = None
        _n_comp, comp_mf_path = mfe_builder.build_comp_mf(
            sess.sys, base, freq_lp=comp_freq, wave=wave_for_mf,
            comp_surface=comp_surface, thick_min=thick_min, thick_max=thick_max)
        comp_mf_name = os.path.basename(comp_mf_path)
        log(f"已生成补偿专用 MF（GMTA {comp_freq}lp/mm，共 {_n_comp} 行）→ {comp_mf_path}")

    mf_name = os.path.basename(mf_path)
    optimize_cycles = _as_int(rp.get("TSC优化周期"), 4)
    n_report, tsc_path = tsc_builder.build_and_write(
        sess.sys, cfg.report, mf_name, base, optimize_cycles=optimize_cycles,
        comp_mode=comp_mode, comp_mf_name=comp_mf_name, log=log)
    log(f"已生成 TSC: {n_report} 个 REPORT 分项  → {tsc_path}")

    tde_meta = read_tde_meta(sess.sys)
    comp_count = sum(1 for row in tde_meta if row.get("操作数") == "COMP")
    if comp_count:
        log(f"已记录 TDE 元数据：{len(tde_meta)} 个公差操作数，其中 COMP {comp_count} 个。")

    sess.sys.Save()

    run_config_path = os.path.join(out, "run_config.json")
    write_json(run_config_path, {
        "source_zmx": os.path.abspath(zmx),
        "config_excel": os.path.abspath(config) if config else "",
        "parent_outdir": parent_out,
        "result_outdir": out,
        "connect": connect,
        "working_copy": os.path.abspath(copy),
        "lens_dir": lens_dir,
        "tsc_path": tsc_path,
        "mf_path": mf_path,
        "counts": {
            "tde": n_tde,
            "mfe": n_mfe,
            "report": n_report,
        },
        "report_meta": report_meta,
        "tde_meta": tde_meta,
        "run_params": rp,
        "field_mapping": field_mapping_result.to_dict(),
        "field_mapping_report": field_mapping_report_path,
    })
    log(f"运行配置快照: {run_config_path}")

    return Prepared(sess=sess, cfg=cfg, rp=rp, base=base, outdir=out,
                    tsc_path=tsc_path, mf_path=mf_path,
                    n_tde=n_tde, n_mfe=n_mfe, n_report=n_report,
                    lens_dir=lens_dir, parent_outdir=parent_out,
                    source_zmx=os.path.abspath(zmx),
                    config_path=os.path.abspath(config) if config else "",
                    log_path=log_path, run_config_path=run_config_path,
                    field_mapping_report_path=field_mapping_report_path,
                    report_meta=report_meta, tde_meta=tde_meta)


def make_runspec(prep: Prepared) -> tol_runner.RunSpec:
    """按 Excel 运行参数与 Prepared 生成 RunSpec（ZTD/前缀落 outdir）。"""
    rp = prep.rp
    ztd_path = os.path.join(prep.outdir, f"{prep.base}.ZTD")
    save_worst = _yes(rp.get("保存WorstCase", "Y"))
    save_best = _yes(rp.get("保存BestCase", "Y"))
    return tol_runner.RunSpec(
        tsc_name=os.path.basename(prep.tsc_path),
        num_runs=_as_int(rp.get("蒙特卡洛次数"), 200),
        num_to_save=_as_int(rp.get("保存数量"), 10),
        comp_mode=str(rp.get("补偿器模式") or "无").strip(),
        distribution=str(rp.get("统计分布") or "正态").strip(),
        ztd_path=ztd_path,
        save_best_worst=save_worst or save_best,
        file_prefix=prep.base,
        lens_dir=prep.lens_dir,
    )


def log_run_plan(prep: Prepared, spec: tol_runner.RunSpec, log=print,
                 export_stats: bool | None = None) -> None:
    """打印本次运行的输出清单与保存策略。"""
    save_worst = _yes(prep.rp.get("保存WorstCase", "Y"))
    save_best = _yes(prep.rp.get("保存BestCase", "Y"))
    used_excel = os.path.join(prep.outdir, "used_excel.xlsx")
    stat_path = f"{os.path.splitext(spec.ztd_path)[0]}_统计.xlsx"
    log("本次运行输出清单：")
    log(f"  结果目录: {prep.outdir}")
    log(f"  工作副本目录: {prep.lens_dir}")
    log(f"  ZTD 目标文件: {spec.ztd_path}")
    if export_stats is None:
        log(f"  统计 Excel: {stat_path}（按运行参数决定是否生成）")
    elif export_stats:
        log(f"  统计 Excel: {stat_path}")
    else:
        log("  统计 Excel: 不生成")
    log(f"  运行日志: {prep.log_path}")
    log(f"  运行配置快照: {prep.run_config_path}")
    log(f"  Excel 配置快照: {used_excel}")
    if prep.field_mapping_report_path:
        log(f"  视场映射报告: {prep.field_mapping_report_path}")
    log("本次保存策略：")
    log(f"  蒙特卡洛次数: {spec.num_runs}")
    log(f"  保存数量: {spec.num_to_save}")
    log(f"  Worst/Best 保存: {'开启' if spec.save_best_worst else '关闭'}"
        f"（Worst={'Y' if save_worst else 'N'}, Best={'Y' if save_best else 'N'}；Zemax API 为同一开关）")


def run_montecarlo(prep: Prepared, log=print,
                   export_stats: bool | None = None):
    """通过 Zemax API 直接跑完蒙特卡洛。返回 RunResult。"""
    spec = make_runspec(prep)
    log_run_plan(prep, spec, log=log, export_stats=export_stats)
    log(f"开始公差分析：{spec.num_runs} 次蒙特卡洛（{spec.distribution}分布）…")

    def on_progress(progress: int, msg: str) -> None:
        log(f"  [{progress:>3}%] {msg}")

    return tol_runner.run(prep.sess.sys, spec, progress_cb=on_progress)


def _export_sensitivity_raw(zos_system, ztd_path: str, report_meta, report_labels,
                            tde_meta, stat_path: str = "", log=print) -> str:
    """敏感度排序的底层实现，仅依赖 ZOS 系统对象与元数据（不依赖 Prepared）。

    供 export_sensitivity() 和 GUI 的 _ZtdWorker（读取已有 ZTD，无 Prepared）共用。
    失败只记录日志并返回空字符串。
    """
    try:
        report_labels = report_labels or [
            str(r.get("标签")).strip() for r in (report_meta or []) if r.get("标签")
        ]
        if not report_labels:
            log("敏感度排序跳过：缺少 REPORT 标签。")
            return ""
        if not tde_meta:
            log("敏感度排序跳过：缺少 TDE 元数据。")
            return ""
        res = sensitivity_reader.read_sensitivity(
            zos_system, ztd_path,
            report_meta=report_meta or None,
            report_labels=report_labels or None,
            tde_meta=tde_meta or None)
        if not res.succeeded:
            log("敏感度排序未导出：" + (res.message or "未知原因"))
            for key, value in res.diagnostics:
                log(f"  敏感度诊断 {key}: {value}")
            return ""
        if stat_path:
            out = sensitivity_reader.append_to_excel(res, stat_path)
            log(f"敏感度排序已写入统计 Excel: {out}")
            return out
        path = ztd_path.rsplit(".", 1)[0] + "_敏感度排序.xlsx"
        out = sensitivity_reader.export_excel(res, path)
        log(f"敏感度排序 Excel: {out}")
        return out
    except Exception as e:
        log(f"敏感度排序导出失败（已忽略）：{type(e).__name__}: {e}")
        return ""


def export_sensitivity(prep: Prepared, ztd_path: str, stat_path: str = "", log=print) -> str:
    """从同一 ZTD 尝试把敏感度排序追加到统计 Excel；失败只记录日志并返回空字符串。"""
    report_meta = prep.report_meta or [
        r for r in prep.cfg.report if _yes(r.get("启用")) and r.get("标签")
    ]
    report_labels = [str(r.get("标签")).strip() for r in report_meta if r.get("标签")]
    return _export_sensitivity_raw(
        prep.sess.sys, ztd_path, report_meta, report_labels,
        prep.tde_meta, stat_path=stat_path, log=log)