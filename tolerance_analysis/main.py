r"""main.py —— 公差分析主入口（在代码里设置地址，直接运行）。

使用方法：
  1. 修改下面的 ZMX_FILE / CONFIG_FILE 两个地址；
  2. 直接运行本文件：
         .\.venv\Scripts\python.exe -u main.py
  3. 运行后按提示选择连接模式：
         1) Standalone —— 程序后台自起 Zemax 实例，跑完自动释放（推荐）
         2) GUI 模式   —— 先在 OpticStudio 进入「编程 → 交互扩展」等待，
                          程序连入该窗口，可在界面看实时进度

也可用命令行参数临时覆盖写死的地址 / 跳过选择菜单：
    .\.venv\Scripts\python.exe -u main.py --zmx "..." --config "..." --connect standalone

流程：连接 → 建 TDE/MFE/TSC → Save → API 直接跑完蒙特卡洛。
输出（ZTD / Worst / Best）落在 output 目录，跑完不读取 ZTD（在 OpticStudio 查看）。
"""

from __future__ import annotations

import argparse
import os
import sys

# ===== 在这里设置地址（命令行参数 > 环境变量 > 下方默认值）===================
# 环境变量优先级高于以下默认值，命令行参数优先于环境变量。
#   ZEMAX_TOL_ZMX     — 待分析的 zmx 文件
#   ZEMAX_TOL_CONFIG  — Excel 配置文件
#   ZEMAX_TOL_OUTDIR  — 输出目录
#   ZEMAX_TOL_CONNECT — 连接模式 (standalone/extension)
ZMX_FILE = os.environ.get("ZEMAX_TOL_ZMX",
                          r"F:\个人文件\P3111\05304_tol.zmx")
CONFIG_FILE = os.environ.get("ZEMAX_TOL_CONFIG",
                             r"F:\个人文件\P3111\tol_config_05304.xlsx")
OUTPUT_DIR = os.environ.get("ZEMAX_TOL_OUTDIR",
                            r"F:\个人文件\P3111")
CONNECT_MODE = os.environ.get("ZEMAX_TOL_CONNECT", "standalone")
# =========================================================================

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from toltool import pipeline


def _choose_mode(default: str) -> str:
    """运行时让用户选连接模式。直接回车用默认；非交互环境也回落默认。"""
    menu = (
        "\n请选择连接模式：\n"
        "  1) Standalone —— 程序后台自起 Zemax 实例，跑完自动释放（推荐）\n"
        "  2) GUI 模式   —— 先在 OpticStudio 进入交互扩展等待，连入该窗口\n"
        f"输入 1 或 2（直接回车=默认 {default}）: "
    )
    try:
        ans = input(menu).strip()
    except EOFError:
        return default
    if ans == "1":
        return "standalone"
    if ans == "2":
        return "extension"
    return default


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="公差分析主入口（地址写在文件顶部）")
    p.add_argument("--zmx", default=ZMX_FILE, help="待分析的 zmx 文件路径")
    p.add_argument("--config", default=CONFIG_FILE, help="Excel 配置文件路径")
    p.add_argument("--connect", choices=["extension", "standalone"],
                   default=None, help="连接方式；不传则运行时菜单选择")
    p.add_argument("--outdir", default=OUTPUT_DIR or None,
                   help="输出目录(ZTD/Worst/Best)；不传则用脚本下 output\\")
    args = p.parse_args(argv)

    mode = args.connect or _choose_mode(CONNECT_MODE)

    outdir = args.outdir or os.path.join(_HERE, "output")
    os.makedirs(outdir, exist_ok=True)

    print(f"连接模式  : {'Standalone' if mode == 'standalone' else 'GUI(交互扩展)'}")
    print(f"待分析镜头: {args.zmx}")
    print(f"配置 Excel: {args.config}")
    print(f"输出目录  : {outdir}")

    prep = pipeline.prepare_session(
        args.zmx, args.config, outdir=outdir, connect=mode)

    result = pipeline.run_montecarlo(prep)
    if not result.succeeded:
        print(f"公差分析失败: {result.message}", file=sys.stderr)
        return 1

    print(f"分析完成。ZTD: {result.ztd_path}")
    if result.bestworst_folder:
        print(f"Worst/Best 输出目录: {result.bestworst_folder}")
    print("（结果可在 OpticStudio 或上述 ZTD 中查看；本入口不读取 ZTD）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
