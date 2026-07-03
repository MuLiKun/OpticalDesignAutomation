r"""build_code_kb.py —— 扫描 Zemax ZOS-API 官方示例代码，生成 samples_code.jsonl。

覆盖全部语言：MATLAB(.m) / Python(.py) / C#(.cs) / C++(.cpp) / VB.NET(.vb)
/ Mathematica(.nb)。每个示例文件整体入库，供全文检索 API 用法。

命名规律：<Lang>Standalone_<NN>_<topic>.<ext>，同一 NN 跨语言对应同一功能。

产物（同目录）：samples_code.jsonl（纯文本，可上传 GitHub）

运行：
  python build_code_kb.py
  python build_code_kb.py --src "D:\...\ZOS-API Sample Code"
"""

from __future__ import annotations

import argparse
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

# 默认指向标准位置 ~\Documents\Zemax\ZOS-API Sample Code；不同机器可用 --src 覆盖
DEFAULT_SRC = os.path.join(os.path.expanduser("~"), "Documents", "Zemax",
                           "ZOS-API Sample Code")

# 扩展名 -> 语言标签
EXT_LANG = {
    ".m": "matlab", ".py": "python", ".cs": "csharp",
    ".cpp": "cpp", ".vb": "vbnet", ".nb": "mathematica",
}

# 从文件名解析编号与主题：如 MATLABStandalone_14_Seq_Tolerance.m
_NAME_RE = re.compile(r"_(\d{2})_(.+)$")


def parse_name(stem: str) -> tuple[str, str]:
    """返回 (编号, 主题)。无编号则 ('', 原名)。"""
    m = _NAME_RE.search(stem)
    if m:
        return m.group(1), m.group(2).replace("_", " ")
    return "", stem


def build(src: str, out: str) -> int:
    n = 0
    with open(out, "w", encoding="utf-8") as jf:
        for root, _dirs, files in os.walk(src):
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                lang = EXT_LANG.get(ext)
                if not lang:
                    continue
                path = os.path.join(root, fn)
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        code = f.read()
                except OSError:
                    continue
                stem = os.path.splitext(fn)[0]
                sample_no, topic = parse_name(stem)
                rel = os.path.relpath(path, src)
                jf.write(json.dumps({
                    "dataset": "code",
                    "lang": lang,
                    "sample_no": sample_no,
                    "topic": topic,
                    "filename": fn,
                    "rel_path": rel,
                    "code": code,
                }, ensure_ascii=False) + "\n")
                n += 1
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="构建 ZOS-API 示例代码库")
    p.add_argument("--src", default=DEFAULT_SRC, help="Sample Code 根目录")
    p.add_argument("--out", default=os.path.join(_HERE, "samples_code.jsonl"))
    args = p.parse_args(argv)

    if not os.path.isdir(args.src):
        print(f"[错误] 找不到目录: {args.src}")
        return 1
    n = build(args.src, args.out)
    size_kb = os.path.getsize(args.out) / 1024
    print(f"完成：{n} 个示例 → {os.path.basename(args.out)} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
