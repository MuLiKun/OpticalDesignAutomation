---
name: "zemax-manual-kb"
description: "Full-text searchable Zemax reference KB: user manual (zh+en), official ZOS-API code samples (matlab/python/csharp/cpp/vbnet), and Samples lens-model index. Invoke when unsure about any Zemax term, operand, menu, API usage, or to find an example lens/code."
---

# Zemax 参考知识库 (manual-kb)

本技能是 Zemax OpticStudio 的**全文检索参考知识库**，含三个数据集。处理任何 Zemax 相关任务时，遇到疑问**优先查本库**拿到带出处的权威答案，再作答。

| 数据集 | 内容 | 规模 | 何时查 |
|--------|------|------|--------|
| `manual` | 中英文用户手册全文 | zh 3945 + en 5101 块 | 术语/操作数/菜单/参数/功能含义，需页码出处 |
| `code` | 官方 ZOS-API 示例代码（matlab/python/csharp/cpp/vbnet/mathematica） | 109 文件全语言 | API 怎么调用、找可参考的示例代码（MATLAB 最全） |
| `lens` | Samples 镜头模型元数据索引 | 468 个 zmx | 找示例镜头（如 double gauss），返回本地文件路径 |

与 `zemax-zosapi-connector` / `zemax-tolerance-analysis` 互补：那两个负责"怎么连、怎么跑"，本技能负责"这是什么、在哪一页、有没有示例"。

## 何时调用

- 不确定操作数/术语含义（TWAV、REAX…）→ `--dataset manual`
- 需要某功能的 API 调用示例（公差、优化、点列图…）→ `--dataset code`
- 想找某类示例镜头（double gauss、cooke triplet…）→ `--dataset lens`
- 拿不准查哪个 → `--dataset all` 三库都查

## 如何调用

技能目录：`.trae/skills/zemax-manual-kb/`。用工作区 venv（如 `e:\zemax-skills-advance_TOL\.venv\Scripts\python.exe`）。

### 首次使用：从 jsonl 重建 DB（一次性）

仓库只入库纯文本 jsonl，二进制 `manual.db` 不入库。首次用前重建：

```powershell
python .trae/skills/zemax-manual-kb/load_from_jsonl.py
```

生成同目录 `manual.db`（约 17 MB，含三数据集）。

### 查询

```powershell
# 手册：中英文同查
python .trae/skills/zemax-manual-kb/query.py "MTF" --dataset manual --top 3

# 代码：指定语言（matlab/python/csharp/cpp/vbnet），或 all
python .trae/skills/zemax-manual-kb/query.py "tolerance montecarlo" --dataset code --lang matlab --top 3

# 镜头：返回元数据 + 本地绝对路径
python .trae/skills/zemax-manual-kb/query.py "double gauss" --dataset lens --top 5

# 三库全查 + JSON 输出
python .trae/skills/zemax-manual-kb/query.py "spot diagram" --dataset all --json
```

**回答用户时引用出处**：manual 给页码，code 给示例文件名，lens 给镜头名+路径。

## 可移植性（换电脑/其他用户）

两个环境变量，都可不设（用默认）：

| 变量 | 作用 | 默认 |
|------|------|------|
| `ZEMAX_KB_PATH` | 指定 `manual.db` 位置（跨项目共享） | 脚本同目录 `manual.db` |
| `ZEMAX_SAMPLES_DIR` | 镜头本地根目录（拼 lens 绝对路径用） | `~\Documents\Zemax\Samples` |

> lens 的 jsonl 只存**相对 Samples 根的相对路径**，可移植。Zemax 自带 Samples 目录结构在各机器相通，但**盘符可能不同**（如本机是 `D:\Users\...`），此时需设：
> ```powershell
> $env:ZEMAX_SAMPLES_DIR = "D:\Users\<user>\Documents\Zemax\Samples"
> ```

## 文件说明

| 文件 | 说明 | 入库 |
|------|------|------|
| `query.py` | 统一查询（CLI + 模块 `search_kb`），支持 `--dataset` | 是 |
| `load_from_jsonl.py` | 从所有 jsonl 还原 `manual.db`（多数据集） | 是 |
| `build_kb.py` | 从 PDF 重建手册 jsonl（需 PDF，一般用不到） | 是 |
| `build_code_kb.py` | 扫描 Sample Code 生成 `samples_code.jsonl` | 是 |
| `build_lens_kb.py` | 解析 Samples/*.zmx 生成 `samples_lens.jsonl` | 是 |
| `manual_zh.jsonl` / `manual_en.jsonl` | 手册全文（纯文本） | 是 |
| `samples_code.jsonl` | 示例代码全文（纯文本，~3MB） | 是 |
| `samples_lens.jsonl` | 镜头元数据索引（纯文本，~140KB） | 是 |
| `toc_zh.md` / `toc_en.md` | 手册章节目录 | 是 |
| `manual.db` | SQLite FTS5 索引（本地生成，二进制） | 否 |

## 重新构建各数据集（源数据变化时）

```powershell
# 代码库：--src 指向 ZOS-API Sample Code 目录
python build_code_kb.py --src "D:\Users\<user>\Documents\Zemax\ZOS-API Sample Code"
# 镜头库：--src 指向 Samples 目录
python build_lens_kb.py --src "D:\Users\<user>\Documents\Zemax\Samples"
# 然后重建 db
python load_from_jsonl.py
```

## 依赖

```
PyMuPDF>=1.28.0   # 仅 build_kb.py 从 PDF 重建手册时需要
jieba>=0.42.1     # 中文分词，查询/重建均需
```

## 已知局限

- 中文手册无内嵌书签，章节标签为启发式（部分为页码数字）；英文章节标签准确。
- lens 数据集只索引 `.zmx`（文本），未含 `.zos`（打包格式）；镜头 `name` 多用文件名兜底。
- lens 绝对路径依赖 `ZEMAX_SAMPLES_DIR`，本机盘符非默认时需设置。
