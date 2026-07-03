r"""query.py —— Zemax 参考知识库查询接口（多数据集）。

三个数据集：
  - manual : 中英文用户手册全文
  - code   : ZOS-API 官方示例代码（matlab/python/csharp/cpp/vbnet/mathematica）
  - lens   : Samples 镜头模型元数据索引

DB 路径解析优先级：
  1. 环境变量 ZEMAX_KB_PATH
  2. 脚本同目录 manual.db

镜头本地路径解析（dataset=lens）：
  绝对路径 = ZEMAX_SAMPLES_DIR(默认 ~\Documents\Zemax\Samples) + rel_path

命令行：
  python query.py "tolerance" --dataset manual --lang zh --top 3
  python query.py "montecarlo" --dataset code --lang matlab --top 3
  python query.py "double gauss" --dataset lens --top 5
  python query.py "spot diagram" --dataset all --json

模块：
  from query import search_kb
  search_kb("MTF", dataset="manual", lang="both", top=5)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3

_HERE = os.path.dirname(os.path.abspath(__file__))


def get_db_path() -> str:
    return os.environ.get("ZEMAX_KB_PATH") or os.path.join(_HERE, "manual.db")


def get_samples_dir() -> str:
    """镜头 Samples 根目录：环境变量优先，否则标准位置。"""
    env = os.environ.get("ZEMAX_SAMPLES_DIR")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), "Documents", "Zemax", "Samples")


def _fts_query(term: str, chinese: bool) -> str:
    """构造 FTS5 MATCH 串。中文分词，其余按空白切；多词 AND。"""
    if chinese:
        import jieba
        toks = [t for t in jieba.cut(term) if t.strip()]
    else:
        toks = [t for t in re.split(r"\s+", term) if t.strip()]
    return " AND ".join(f'"{t}"' for t in toks) if toks else f'"{term}"'


def _make_snippet(text: str, term: str, width: int = 120) -> str:
    words = [w for w in re.split(r"\s+", term) if w.strip()]
    low = text.lower()
    pos = -1
    for w in words:
        pos = low.find(w.lower())
        if pos >= 0:
            break
    if pos < 0:
        return text[:width].replace("\n", " ")
    start = max(0, pos - width // 3)
    end = min(len(text), pos + width)
    snip = text[start:end].replace("\n", " ")
    return ("… " if start > 0 else "") + snip + (" …" if end < len(text) else "")


def _query_manual(conn, term, lang, top) -> list[dict]:
    """手册数据集：lang 可 zh/en/both。"""
    langs = ["zh", "en"] if lang == "both" else [lang]
    out = []
    for lg in langs:
        match = _fts_query(term, chinese=(lg == "zh"))
        rows = conn.execute(
            "SELECT c.ref, c.title, c.body_text FROM fts "
            "JOIN chunks c ON c.id = fts.rowid "
            "WHERE fts MATCH ? AND c.dataset='manual' AND c.lang=? "
            "ORDER BY rank LIMIT ?", (match, lg, top)).fetchall()
        for ref, title, body in rows:
            out.append({"dataset": "manual", "lang": lg, "page": ref,
                        "heading": title, "snippet": _make_snippet(body, term),
                        "text": body})
    return out


def _query_code(conn, term, lang, top) -> list[dict]:
    """代码数据集：lang 可指定语言(matlab/python/...)或 all/both。"""
    match = _fts_query(term, chinese=False)
    sql = ("SELECT c.lang, c.ref, c.title, c.body_text, c.meta_json FROM fts "
           "JOIN chunks c ON c.id = fts.rowid "
           "WHERE fts MATCH ? AND c.dataset='code' ")
    params: list = [match]
    if lang not in ("all", "both", None):
        sql += "AND c.lang=? "
        params.append(lang)
    sql += "ORDER BY rank LIMIT ?"
    params.append(top)
    rows = conn.execute(sql, params).fetchall()
    out = []
    for lg, ref, title, body, meta in rows:
        out.append({"dataset": "code", "lang": lg, "rel_path": ref,
                    "topic": title, "snippet": _make_snippet(body, term),
                    "meta": json.loads(meta or "{}"), "text": body})
    return out


def _query_lens(conn, term, top) -> list[dict]:
    """镜头数据集：拼出本地绝对路径。"""
    match = _fts_query(term, chinese=True)
    rows = conn.execute(
        "SELECT c.ref, c.title, c.body_text, c.meta_json FROM fts "
        "JOIN chunks c ON c.id = fts.rowid "
        "WHERE fts MATCH ? AND c.dataset='lens' "
        "ORDER BY rank LIMIT ?", (match, top)).fetchall()
    samples_dir = get_samples_dir()
    out = []
    for ref, title, body, meta in rows:
        m = json.loads(meta or "{}")
        out.append({"dataset": "lens", "name": title, "rel_path": ref,
                    "abs_path": os.path.join(samples_dir, ref),
                    "category": m.get("category", ""), "mode": m.get("mode", ""),
                    "num_surf": m.get("num_surf", 0)})
    return out


def search_kb(term: str, dataset: str = "manual", lang: str = "both",
              top: int = 5, db_path: str | None = None) -> list[dict]:
    """统一检索。dataset: manual|code|lens|all。"""
    db_path = db_path or get_db_path()
    if not os.path.isfile(db_path):
        raise FileNotFoundError(
            f"知识库 DB 不存在: {db_path}\n"
            f"请先运行 load_from_jsonl.py 从 jsonl 重建，"
            f"或设置环境变量 ZEMAX_KB_PATH。")
    conn = sqlite3.connect(db_path)
    try:
        res: list[dict] = []
        if dataset in ("manual", "all"):
            res += _query_manual(conn, term, lang, top)
        if dataset in ("code", "all"):
            res += _query_code(conn, term, lang, top)
        if dataset in ("lens", "all"):
            res += _query_lens(conn, term, top)
    finally:
        conn.close()
    return res


def _format_human(results: list[dict]) -> str:
    if not results:
        return "（无匹配结果）"
    lines = []
    for i, r in enumerate(results, 1):
        ds = r["dataset"]
        if ds == "manual":
            lines.append(f"[{i}] (manual/{r['lang']}) p.{r['page']} §{r['heading'] or '-'}")
            lines.append(f"    {r['snippet'].strip()}")
        elif ds == "code":
            lines.append(f"[{i}] (code/{r['lang']}) {r['topic']}  <{r['rel_path']}>")
            lines.append(f"    {r['snippet'].strip()}")
        else:  # lens
            lines.append(f"[{i}] (lens) {r['name']}  [{r['mode']}, {r['num_surf']}面]")
            lines.append(f"    {r['abs_path']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Zemax 参考知识库查询（手册/代码/镜头）")
    p.add_argument("term", help="检索词")
    p.add_argument("--dataset", choices=["manual", "code", "lens", "all"],
                   default="manual", help="检索数据集")
    p.add_argument("--lang", default="both",
                   help="manual: zh|en|both；code: matlab|python|csharp|cpp|vbnet|all")
    p.add_argument("--top", type=int, default=5, help="返回条数")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--db", default=None, help="指定 DB 路径")
    args = p.parse_args(argv)

    try:
        results = search_kb(args.term, args.dataset, args.lang, args.top, args.db)
    except FileNotFoundError as e:
        print(str(e))
        return 1

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(_format_human(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
