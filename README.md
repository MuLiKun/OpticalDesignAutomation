# zemax-skills

基于 Zemax OpticStudio ZOS-API 的光学自动化工作区，目前主要包含**公差分析自动化程序**和配套 Trae Skills。

---

## 1. 仓库结构

```text
zemax-skills-advance_TOL/
├── tolerance_analysis/                 公差分析自动化程序
│   ├── gui.py                          GUI 入口（推荐）
│   ├── tol_run.py                      命令行入口
│   ├── check_stage1.py                 基础检查脚本
│   ├── check_field_mapping.py          视场映射检查脚本
│   ├── make_backup.py                  本地备份脚本
│   ├── toltool/                        核心代码包
│   ├── tol_config_模板.xlsx            高级 Excel 配置模板
│   ├── 公差分析程序_使用说明.md        用户手册
│   ├── 公差分析程序_需求文档.md        功能规格与后续规划
│   └── 公差分析工具_开发进度与测试记录.md
├── .trae/skills/
│   ├── zemax-zosapi-connector/         ZOS-API 连接 skill
│   └── zemax-tolerance-analysis/       公差分析 skill
└── README.md
```

> `.venv/` 不入库。当前工作区约定使用 `e:\zemax-skills-advance_TOL\.venv\Scripts\python.exe`。

---

## 2. 公差分析程序能做什么

程序可以把 Zemax 公差分析流程自动化：

1. 连接 OpticStudio（Standalone 或 Interactive Extension）；
2. 另存工作副本，不修改原始 `zmx`；
3. 生成或复用 TDE / MFE / TSC；
4. 运行脚本式 Monte Carlo；
5. 保存 ZTD、日志、配置快照、Worst/Best Case；
6. 读取 ZTD 并导出统计 Excel。

当前支持三种主模式：

| 模式 | 说明 |
|---|---|
| 普通标准模板 | 不需要手写 Excel；支持 RX/TX、标准分析/完整视场分析 |
| 使用 Zemax 当前设置 | 复用 zmx 中已有 TDE/MFE |
| 高级 Excel | 用 Excel 完全自定义公差、评价函数、REPORT、运行参数 |

其他能力：

- GUI 暗色界面、实时日志、运行计时、取消、打开结果目录；
- 视场映射，输出 `field_mapping.txt`；
- 独立分析已有 `.ZTD`；
- 统计 Excel 包含名义值、Cpk1.33 上下限、均值、标准差、原始 MC 样本、REPORT 分项和 COMP 项。

---

## 3. 快速上手

### 3.1 启动 GUI（推荐）

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\gui.py
```

### 3.2 命令行运行

普通标准模板模式：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\tol_run.py --standard --zmx "镜头.zmx" --outdir "输出目录" --connect standalone --product-type RX --standard-template 标准分析 --tolerance-level 标准 --num-runs 20 --num-to-save 0
```

使用 Zemax 当前设置模式：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\tol_run.py --current-settings --zmx "镜头.zmx" --outdir "输出目录" --connect standalone --num-runs 20
```

高级 Excel 模式：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\tol_run.py --zmx "镜头.zmx" --config "配置.xlsx" --outdir "输出目录" --connect standalone
```

生成高级 Excel 模板：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\tol_run.py --init-template --config tolerance_analysis\tol_config_模板.xlsx
```

---

## 4. 常用维护命令

基础语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile tolerance_analysis\gui.py tolerance_analysis\tol_run.py
```

核心模块语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile tolerance_analysis\toltool\pipeline.py tolerance_analysis\toltool\tde_builder.py tolerance_analysis\toltool\mfe_builder.py tolerance_analysis\toltool\tsc_builder.py tolerance_analysis\toltool\tol_runner.py tolerance_analysis\toltool\ztd_reader.py tolerance_analysis\toltool\zos_connect.py
```

基础检查脚本：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\check_stage1.py --python .\.venv\Scripts\python.exe
```

本地备份快照：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\make_backup.py
```

---

## 5. 文档分工

| 文档 | 用途 |
|---|---|
| [公差分析程序_使用说明.md](tolerance_analysis/公差分析程序_使用说明.md) | 使用者入口：怎么运行、怎么填配置、怎么看输出 |
| [公差分析程序_需求文档.md](tolerance_analysis/公差分析程序_需求文档.md) | 维护者入口：当前功能规格、设计边界、后续规划 |
| [公差分析工具_开发进度与测试记录.md](tolerance_analysis/公差分析工具_开发进度与测试记录.md) | 开发记录：关键变更、已知问题、回归测试清单 |
| [.trae/skills/zemax-tolerance-analysis/SKILL.md](.trae/skills/zemax-tolerance-analysis/SKILL.md) | AI 执行公差分析任务时必须遵守的 ZOS-API 经验 |
| [.trae/skills/zemax-zosapi-connector/SKILL.md](.trae/skills/zemax-zosapi-connector/SKILL.md) | AI 连接本机 Zemax 时使用的约束和流程 |

---

## 6. 环境要求

- Windows；
- Zemax OpticStudio 2023 R1 或兼容版本；
- Python；
- `pythonnet`；
- `openpyxl`；
- `numpy`；
- `PySide6`。

Zemax 连接和 DLL 查找细节见 skill：

- [.trae/skills/zemax-zosapi-connector/SKILL.md](.trae/skills/zemax-zosapi-connector/SKILL.md)

---

## 7. 当前状态

当前版本已具备内部试用能力：

- 高级 Excel 模式主链路可用；
- 普通标准模板模式已完成 GUI / CLI 可用闭环；
- 使用 Zemax 当前设置模式已实现；
- ZTD 统计和独立 ZTD 分析已实现；
- 标准模板参数仍需结合真实项目继续定稿。

详细进度和待验证项见：

- [公差分析工具_开发进度与测试记录.md](tolerance_analysis/公差分析工具_开发进度与测试记录.md)
