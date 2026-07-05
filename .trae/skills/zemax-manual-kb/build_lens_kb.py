r"""build_lens_kb.py —— 扫描 Zemax Samples 目录下的 .zmx，提取元数据索引。

.zmx 是文本格式，头部含结构化字段。只提取元数据(不复制镜头文件本身)：
  VERS(版本) / MODE(SEQ|NSC) / NAME(标题) / AUTH(作者) / NOTE(说明) / 面数

可移植性：
  - 只存相对 Samples 根的相对路径(rel_path)，不存盘符绝对路径。
  - 查询时由 query.py 用环境变量 ZEMAX_SAMPLES_DIR(默认 ~\Documents\Zemax\Samples)
    拼出本地绝对路径。换电脑只要 Samples 在标准位置即可用。

产物(同目录)：samples_lens.jsonl(纯文本，可上传 GitHub)

运行：
  python build_lens_kb.py
  python build_lens_kb.py --src "D:\Users\<user>\Documents\Zemax\Samples"
"""

from __future__ import annotations

import argparse
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# 默认指向标准位置 ~\Documents\Zemax\Samples；不同机器可用 --src 覆盖
DEFAULT_SRC = os.path.join(os.path.expanduser("~"), "Documents", "Zemax", "Samples")


def read_zmx_head(path: str, max_lines: int = 400) -> dict:
    """读取 .zmx 头部，解析元数据。.zmx 常见为 UTF-16(Unicode) 编码。"""
    meta = {"name": "", "mode": "", "author": "", "version": "",
            "note": "", "num_surf": 0}
    notes: list[str] = []
    n_surf = 0
    text = None
    for enc in ("utf-16", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                text = [next(f, "") for _ in range(max_lines)]
            # 简单校验：应含 VERS 或 MODE
            if any(ln.startswith(("VERS", "MODE")) for ln in text):
                break
        except (OSError, UnicodeError, StopIteration):
            text = None
    if not text:
        return meta

    for ln in text:
        ln = ln.rstrip("\n")
        if ln.startswith("VERS"):
            meta["version"] = ln[5:].strip()
        elif ln.startswith("MODE"):
            meta["mode"] = ln[5:].strip()
        elif ln.startswith("NAME"):
            meta["name"] = ln[5:].strip()
        elif ln.startswith("AUTH"):
            meta["author"] = ln[5:].strip()
        elif ln.startswith("NOTE"):
            # 格式：NOTE <n> <text>；只收有正文的
            body = ln[5:].strip()
            parts = body.split(None, 1)
            if len(parts) == 2 and parts[1].strip():
                notes.append(parts[1].strip())
        elif ln.startswith("SURF"):
            try:
                n_surf = max(n_surf, int(ln[5:].strip()))
            except ValueError:
                pass
    meta["note"] = " ".join(notes)[:800]
    meta["num_surf"] = n_surf
    return meta


def build(src: str, out: str) -> int:
    n = 0
    with open(out, "w", encoding="utf-8") as jf:
        for root, _dirs, files in os.walk(src):
            for fn in sorted(files):
                if not fn.lower().endswith(".zmx"):
                    continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, src)
                category = rel.split(os.sep)[0] if os.sep in rel else ""
                meta = read_zmx_head(path)
                # name 为空时用文件名(去扩展名)兜底，作为可检索标题
                name = meta["name"] or os.path.splitext(fn)[0]
                jf.write(json.dumps({
                    "dataset": "lens",
                    "rel_path": rel,
                    "category": category,
                    "filename": fn,
                    "name": name,
                    "mode": meta["mode"],
                    "author": meta["author"],
                    "num_surf": meta["num_surf"],
                    "note": meta["note"],
                }, ensure_ascii=False) + "\n")
                n += 1
                if n % 100 == 0:
                    print(f"  已解析 {n} 个 zmx ...")
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="构建 Samples 镜头元数据索引")
    p.add_argument("--src", default=DEFAULT_SRC, help="Samples 根目录")
    p.add_argument("--out", default=os.path.join(_HERE, "samples_lens.jsonl"))
    args = p.parse_args(argv)

    if not os.path.isdir(args.src):
        print(f"[错误] 找不到目录: {args.src}")
        return 1
    n = build(args.src, args.out)
    size_kb = os.path.getsize(args.out) / 1024
    print(f"完成：{n} 个镜头 → {os.path.basename(args.out)} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
