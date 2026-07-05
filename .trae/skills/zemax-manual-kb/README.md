# Zemax 参考知识库 (zemax-manual-kb)

Zemax OpticStudio 的**全文检索参考知识库**，作为 Trae Skill 使用，也可被任意脚本/AI 调用。含三个数据集：手册、示例代码、镜头模型索引。

> 本文档面向**其他人**和 **AI** 两类读者，讲清楚：这是什么、怎么在新电脑上跑起来、怎么查询、路径怎么配。

---

## 1. 这是什么

| 数据集 | 内容 | 规模 | 用途 |
|--------|------|------|------|
| `manual` | 中英文用户手册全文 | zh 3945 + en 5101 块 | 查术语/操作数/菜单/参数含义，带页码 |
| `code` | 官方 ZOS-API 示例代码（matlab/python/csharp/cpp/vbnet/mathematica） | 109 文件 | 查 API 怎么调用（MATLAB 最全） |
| `lens` | Samples 镜头模型元数据索引 | 468 个 zmx | 找示例镜头（如 double gauss），返回本地路径 |

技术栈：SQLite **FTS5** 全文索引 + jieba 中文分词。纯 Python，无外部服务。

---

## 2. 文件清单

```
zemax-manual-kb/
├── SKILL.md              Trae skill 定义
├── README.md            ← 本文档
│
├── query.py             查询接口（CLI + Python 模块 search_kb）
├── load_from_jsonl.py   从 jsonl 重建 manual.db（多数据集）
├── build_kb.py          从 PDF 重建手册 jsonl（+ 自动探测 Zemax 安装目录）
├── build_code_kb.py     扫描 ZOS-API Sample Code 生成 samples_code.jsonl
├── build_lens_kb.py     解析 Samples/*.zmx 生成 samples_lens.jsonl
│
├── manual_zh.jsonl      中文手册数据（纯文本 3.3MB）
├── manual_en.jsonl      英文手册数据（纯文本 4.1MB）
├── samples_code.jsonl   示例代码数据（纯文本 3.0MB）
├── samples_lens.jsonl   镜头索引数据（纯文本 141KB）
├── toc_zh.md / toc_en.md 手册章节目录
│
└── manual.db            SQLite 索引（本地生成，17MB，不入库/由 jsonl 重建）
```

> `manual.db` 是二进制、可由 jsonl 秒级重建，故 `.gitignore` 已排除，不随仓库上传。

---

## 3. 在新电脑上使用（快速开始）

### 前提
- Python 3.10+
- 依赖：`pip install jieba`（若要从 PDF 重建手册还需 `PyMuPDF`）

### 最快路径（已带 jsonl，无需 Zemax）
```powershell
pip install jieba
python load_from_jsonl.py          # 从 jsonl 重建 manual.db
python query.py "MTF" --dataset manual --top 3
```
手册、代码两个数据集**开箱即用**（jsonl 已含数据）。

### 镜头查询需指定本机 Samples 目录
lens 的 jsonl 只存**相对路径**，查询时要拼出本机绝对路径：
```powershell
# 若本机 Samples 不在默认位置 ~\Documents\Zemax\Samples，先设环境变量
$env:ZEMAX_SAMPLES_DIR = "D:\Users\<你>\Documents\Zemax\Samples"
python query.py "double gauss" --dataset lens --top 5
```

---

## 4. 路径与可移植性（换电脑必读）

所有路径都**不硬编码**，靠参数或环境变量，默认值基于当前用户主目录 `~`。

| 用途 | 怎么配 | 默认值 |
|------|--------|--------|
| 索引 DB 位置 | 环境变量 `ZEMAX_KB_PATH` | 脚本同目录 `manual.db` |
| 镜头本机根目录 | 环境变量 `ZEMAX_SAMPLES_DIR` | `~\Documents\Zemax\Samples` |
| 建手册（PDF） | `build_kb.py --zemax-dir <安装目录>` | 自动探测 `C:\|D:\Program Files\Ansys\...` |
| 建代码 | `build_code_kb.py --src <Sample Code 目录>` | `~\Documents\Zemax\ZOS-API Sample Code` |
| 建镜头 | `build_lens_kb.py --src <Samples 目录>` | `~\Documents\Zemax\Samples` |

> ⚠️ 已知：`samples_code.jsonl` 中个别**官方示例代码原文**含作者本机路径（如 `DGfile = r"D:\..."`），这是 Zemax 自带示例的原始写法，保留以维持示例真实性，不影响本库功能。

---

## 5. 从零完全重建（其他人有 Zemax，想用自己机器的数据）

```powershell
pip install PyMuPDF jieba

# ① 手册（自动探测安装目录；探测失败则手动指定）
python build_kb.py
#   或： python build_kb.py --zemax-dir "C:\Program Files\Ansys Zemax OpticStudio 2023 R1.00"

# ② 示例代码
python build_code_kb.py --src "C:\Users\<你>\Documents\Zemax\ZOS-API Sample Code"

# ③ 镜头索引
python build_lens_kb.py --src "C:\Users\<你>\Documents\Zemax\Samples"

# ④ 建库
python load_from_jsonl.py
```

---

## 6. 查询用法速查

```powershell
# 手册：zh / en / both
python query.py "tolerance" --dataset manual --lang both --top 3

# 代码：指定语言 matlab/python/csharp/cpp/vbnet，或 all
python query.py "montecarlo" --dataset code --lang matlab --top 3

# 镜头：返回名称/模式/面数/本机绝对路径
python query.py "cooke triplet" --dataset lens --top 5

# 三库全查 + JSON（供程序/AI 解析）
python query.py "spot diagram" --dataset all --json
```

返回字段：
- manual：`page`（页码）/ `heading`（章节）/ `snippet` / `text`
- code：`lang` / `topic` / `rel_path` / `snippet` / `text`
- lens：`name` / `mode` / `num_surf` / `rel_path` / `abs_path`（本机绝对路径）

### Python 模块方式
```python
import sys; sys.path.insert(0, r"<本目录>")
from query import search_kb
for r in search_kb("MTF", dataset="manual", lang="both", top=5):
    print(r["page"], r["heading"], r["snippet"])
```

---

## 7. 给 AI 的调用约定

处理 Zemax 任务遇到疑问时，**优先查本库**再作答：
- 术语/操作数/菜单/参数 → `--dataset manual`，回答引用**页码**
- API 怎么写 → `--dataset code`，回答引用**示例文件名**
- 找示例镜头 → `--dataset lens`，回答给**镜头名 + 本机路径**
- 不确定 → `--dataset all`

首次使用若 `manual.db` 不存在，先运行 `load_from_jsonl.py` 重建。

---

## 8. 已知局限

- 中文手册无内嵌书签，章节标签为启发式（部分为页码数字）；英文章节标签准确（来自 1940 条书签）。
- lens 只索引 `.zmx`（文本），未含 `.zos`（打包格式）；镜头名多用文件名兜底。
- 不同 Zemax 版本 Samples 内容可能略有增减，自建索引会有差异（属正常）。
