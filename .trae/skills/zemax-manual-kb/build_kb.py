r"""build_kb.py —— 从 Zemax 中英文 PDF 手册构建可检索知识库。

产物（同目录 kb/ 下）：
  - manual.db           SQLite FTS5 全文索引（本地查询用，二进制）
  - manual_zh.jsonl     中文文本块（纯文本，可上传 GitHub）
  - manual_en.jsonl     英文文本块（纯文本，可上传 GitHub）
  - toc_en.md           英文章节目录（来自 PDF 内嵌书签）
  - toc_zh.md           中文章节目录（正文启发式提取）

运行：
  .\.venv\Scripts\python.exe -u kb\build_kb.py

设计要点：
  - 逐页抽取文本，剔除页眉噪声行。
  - 按段落分块，单块约 500 字，记录 页码 / 章节标题 / 语言。
  - 英文用 PDF 内嵌 TOC(1940 条) 给每块打章节标签；中文无书签，用启发式。
  - 中文入库前用 jieba 分词（FTS5 原生不分中文词）。
"""

from __future__ import annotations

import bisect
import json
import os
import re
import sqlite3
import sys

import fitz  # PyMuPDF
import jieba

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_manual_pdf(lang: str) -> str:
    """在常见 Zemax 安装目录探测 OpticStudio_UserManual_{lang}.pdf。找不到返回空串。"""
    fname = f"OpticStudio_UserManual_{lang}.pdf"
    candidates = []
    for base in (r"C:\Program Files", r"D:\Program Files",
                 r"C:\Program Files (x86)"):
        ansys = os.path.join(base, "Ansys")
        if os.path.isdir(ansys):
            for name in sorted(os.listdir(ansys), reverse=True):
                candidates.append(os.path.join(ansys, name, fname))
        # 旧版直接在 base 下 Zemax OpticStudio
        candidates.append(os.path.join(base, "Zemax OpticStudio", fname))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return ""


# 默认自动探测；探测不到则为空，需用 --zh/--en/--zemax-dir 指定
PDFS = {"zh": _find_manual_pdf("zh"), "en": _find_manual_pdf("en")}

DB_PATH = os.path.join(_HERE, "manual.db")
CHUNK_CHARS = 500  # 单块目标字符数

# 页眉噪声：形如 "110  Zemax OpticStudio 19.4 帮助手册" / "... Help Manual"
_HEADER_RE = re.compile(
    r"^\s*\d*\s*Zemax OpticStudio[^\n]*(?:帮助手册|Help)[^\n]*$",
    re.IGNORECASE,
)


def clean_page_text(raw: str) -> str:
    """剔除页眉噪声行，返回清理后的正文。"""
    lines = []
    for ln in raw.splitlines():
        if _HEADER_RE.match(ln):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def split_into_chunks(text: str, target: int = CHUNK_CHARS) -> list[str]:
    """按段落聚合成 ~target 字符的块，尽量不切断段落。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
        elif len(buf) + len(p) + 1 <= target:
            buf = f"{buf}\n{p}"
        else:
            chunks.append(buf)
            buf = p
        # 单段本身超长则直接成块
        while len(buf) > target * 2:
            chunks.append(buf[: target * 2])
            buf = buf[target * 2:]
    if buf:
        chunks.append(buf)
    return chunks


def build_toc_index(doc) -> tuple[list[int], list[str], str]:
    """从 PDF 内嵌书签构建 (页码升序列表, 对应标题列表, markdown目录)。

    返回的两个列表用于按页码二分查找该页所属章节标题。
    """
    toc = doc.get_toc()  # [[level, title, page], ...]  page 从 1 起
    pages: list[int] = []
    titles: list[str] = []
    md_lines: list[str] = []
    for level, title, page in toc:
        title = title.strip()
        pages.append(page)
        # 用层级拼出面包屑式标题（简单用当前标题，层级用缩进体现在 md）
        titles.append(title)
        md_lines.append(f"{'  ' * (level - 1)}- p.{page} {title}")
    return pages, titles, "\n".join(md_lines)


def heading_for_page(pages: list[int], titles: list[str], page: int) -> str:
    """给定页码，用二分查找返回其所属（最近的前一个书签）章节标题。"""
    if not pages:
        return ""
    idx = bisect.bisect_right(pages, page) - 1
    if idx < 0:
        idx = 0
    return titles[idx]


# 中文标题启发式：短行、以中文/数字开头、不含句末标点、长度适中
_ZH_HEADING_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9（(][^\n]{1,28}$")
_ZH_STOP_PUNCT = "。，；：、！？.,;"


def zh_heading_guess(chunk: str, last_heading: str) -> str:
    """中文无书签，取块首行若像标题则用作章节，否则沿用上一个。"""
    first = chunk.splitlines()[0].strip() if chunk else ""
    if (
        first
        and len(first) <= 28
        and _ZH_HEADING_RE.match(first)
        and first[-1] not in _ZH_STOP_PUNCT
    ):
        return first
    return last_heading


def jieba_tokenize(text: str) -> str:
    """中文分词后用空格连接，供 FTS5 建立可命中的索引。"""
    return " ".join(jieba.cut(text, cut_all=False))


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS fts;

        -- 原始数据表：存可读的原文与元信息
        CREATE TABLE chunks (
            id       INTEGER PRIMARY KEY,
            lang     TEXT NOT NULL,
            page     INTEGER NOT NULL,   -- PDF 物理页(从1起)
            heading  TEXT,               -- 所属章节标题
            text     TEXT NOT NULL       -- 原文(未分词, 供阅读/返回)
        );

        -- FTS5 全文索引：body 存可检索文本(中文已分词)，与 chunks 用 rowid 对应
        CREATE VIRTUAL TABLE fts USING fts5(
            body,
            content=''
        );
        """
    )


def process_pdf(lang: str, path: str, conn: sqlite3.Connection):
    """抽取单份 PDF → 写入 db 与 jsonl，返回 (jsonl路径, 块数, toc_md)。"""
    doc = fitz.open(path)
    pages, titles, toc_md = build_toc_index(doc)
    has_toc = bool(pages)

    jsonl_path = os.path.join(_HERE, f"manual_{lang}.jsonl")
    n_chunks = 0
    last_zh_heading = ""

    with open(jsonl_path, "w", encoding="utf-8") as jf:
        for pno in range(doc.page_count):
            raw = doc[pno].get_text()
            text = clean_page_text(raw)
            if not text:
                continue
            for chunk in split_into_chunks(text):
                page1 = pno + 1  # 人类习惯从 1 起
                if has_toc:
                    heading = heading_for_page(pages, titles, page1)
                else:
                    heading = zh_heading_guess(chunk, last_zh_heading)
                    last_zh_heading = heading

                # 写 chunks 原始表
                cur = conn.execute(
                    "INSERT INTO chunks(lang, page, heading, text) VALUES(?,?,?,?)",
                    (lang, page1, heading, chunk),
                )
                rowid = cur.lastrowid

                # 写 FTS：中文分词，英文原样
                body = jieba_tokenize(chunk) if lang == "zh" else chunk
                conn.execute(
                    "INSERT INTO fts(rowid, body) VALUES(?, ?)", (rowid, body)
                )

                # 写 jsonl（纯文本，可上传）
                jf.write(
                    json.dumps(
                        {"lang": lang, "page": page1,
                         "heading": heading, "text": chunk},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                n_chunks += 1

            if (pno + 1) % 200 == 0:
                print(f"  [{lang}] 已处理 {pno + 1}/{doc.page_count} 页 ...")
                conn.commit()

    doc.close()
    return jsonl_path, n_chunks, toc_md


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="从 Zemax PDF 手册构建 manual_{zh,en}.jsonl / toc / db")
    p.add_argument("--zh", default=PDFS["zh"], help="中文手册 PDF 路径")
    p.add_argument("--en", default=PDFS["en"], help="英文手册 PDF 路径")
    p.add_argument("--zemax-dir", default=None,
                   help="Zemax 安装目录；给出则自动拼手册路径，覆盖 --zh/--en")
    args = p.parse_args(argv)

    pdfs = {"zh": args.zh, "en": args.en}
    if args.zemax_dir:
        pdfs = {
            "zh": os.path.join(args.zemax_dir, "OpticStudio_UserManual_zh.pdf"),
            "en": os.path.join(args.zemax_dir, "OpticStudio_UserManual_en.pdf"),
        }

    for lang, p_ in pdfs.items():
        if not os.path.isfile(p_):
            print(f"[错误] 找不到 PDF: {p_}\n"
                  f"用 --zh/--en 指定路径，或 --zemax-dir 指定安装目录。",
                  file=sys.stderr)
            return 1

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    for lang, path in pdfs.items():
        print(f"===== 处理 [{lang}] {os.path.basename(path)} =====")
        jsonl_path, n_chunks, toc_md = process_pdf(lang, path, conn)
        conn.commit()
        # 写目录 md
        toc_file = os.path.join(_HERE, f"toc_{lang}.md")
        with open(toc_file, "w", encoding="utf-8") as f:
            f.write(f"# Zemax OpticStudio 手册目录 ({lang})\n\n")
            f.write(toc_md if toc_md else "（该 PDF 无内嵌书签，目录从略）\n")
        print(f"  [{lang}] 完成：{n_chunks} 块 → {os.path.basename(jsonl_path)}, "
              f"{os.path.basename(toc_file)}")

    conn.commit()
    conn.close()

    size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
    print(f"\n完成。manual.db 大小 {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
