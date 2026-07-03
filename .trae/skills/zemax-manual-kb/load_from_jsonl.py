r"""load_from_jsonl.py —— 从 jsonl 纯文本还原 manual.db（多数据集）。

支持三个数据集，统一进一个 SQLite FTS5 库：
  - manual : manual_zh.jsonl / manual_en.jsonl   手册全文
  - code   : samples_code.jsonl                  ZOS-API 示例代码
  - lens   : samples_lens.jsonl                  Samples 镜头元数据

统一表结构：chunks(id, dataset, lang, ref, title, body_text, meta_json)
  - ref     : 手册=页码；code/lens=相对路径
  - title   : 手册=章节；code=主题；lens=镜头名
  - body_text: 用于阅读/返回的正文
  - meta_json: 各数据集特有字段(JSON 字符串)
FTS5 索引 body（中文分词），rowid 对应 chunks.id。

用法：
  python load_from_jsonl.py                 # 用同目录所有 jsonl 建 manual.db
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3

import jieba

_HERE = os.path.dirname(os.path.abspath(__file__))

# (文件名, dataset) —— 存在才加载
SOURCES = [
    ("manual_zh.jsonl", "manual"),
    ("manual_en.jsonl", "manual"),
    ("samples_code.jsonl", "code"),
    ("samples_lens.jsonl", "lens"),
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS fts;
        CREATE TABLE chunks (
            id        INTEGER PRIMARY KEY,
            dataset   TEXT NOT NULL,
            lang      TEXT,
            ref       TEXT,
            title     TEXT,
            body_text TEXT NOT NULL,
            meta_json TEXT
        );
        CREATE VIRTUAL TABLE fts USING fts5(body, content='');
        """
    )


def _row_from_record(rec: dict, dataset: str) -> tuple:
    """把不同数据集的记录规范成统一列。返回 (lang, ref, title, body_text, meta, fts_body)。"""
    if dataset == "manual":
        lang = rec["lang"]
        ref = str(rec["page"])
        title = rec.get("heading", "")
        body = rec["text"]
        meta = {"page": rec["page"], "heading": rec.get("heading", "")}
        fts = " ".join(jieba.cut(body)) if lang == "zh" else body
    elif dataset == "code":
        lang = rec["lang"]
        ref = rec["rel_path"]
        title = f"{rec.get('sample_no','')} {rec.get('topic','')}".strip()
        body = rec["code"]
        meta = {"sample_no": rec.get("sample_no", ""),
                "topic": rec.get("topic", ""),
                "filename": rec.get("filename", "")}
        fts = body  # 代码按原文(含英文 API 名)
    else:  # lens
        lang = ""
        ref = rec["rel_path"]
        title = rec.get("name", "")
        # 可检索正文 = 名称 + 类别 + 说明(便于语义命中)
        body = " ".join(filter(None, [
            rec.get("name", ""), rec.get("category", ""),
            rec.get("filename", ""), rec.get("note", "")]))
        meta = {"category": rec.get("category", ""),
                "mode": rec.get("mode", ""),
                "num_surf": rec.get("num_surf", 0),
                "filename": rec.get("filename", "")}
        fts = " ".join(jieba.cut(body))  # 含中文说明可能，分词更稳
    return lang, ref, title, body, json.dumps(meta, ensure_ascii=False), fts


def load(out_db: str) -> dict:
    conn = sqlite3.connect(out_db)
    init_db(conn)
    counts: dict[str, int] = {}
    for fname, dataset in SOURCES:
        path = os.path.join(_HERE, fname)
        if not os.path.isfile(path):
            print(f"[跳过] 不存在: {fname}")
            continue
        cnt = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                lang, ref, title, body, meta, fts_body = \
                    _row_from_record(rec, dataset)
                cur = conn.execute(
                    "INSERT INTO chunks(dataset, lang, ref, title, body_text, meta_json) "
                    "VALUES(?,?,?,?,?,?)",
                    (dataset, lang, ref, title, body, meta),
                )
                conn.execute("INSERT INTO fts(rowid, body) VALUES(?, ?)",
                             (cur.lastrowid, fts_body))
                cnt += 1
        counts[fname] = cnt
    conn.commit()
    conn.close()
    return counts


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="从 jsonl 还原 manual.db（多数据集）")
    p.add_argument("--out", default=os.path.join(_HERE, "manual.db"))
    args = p.parse_args(argv)

    counts = load(args.out)
    total = sum(counts.values())
    size_mb = os.path.getsize(args.out) / 1024 / 1024
    for k, v in counts.items():
        print(f"  {k}: {v} 条")
    print(f"完成：共 {total} 条 → {args.out} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
