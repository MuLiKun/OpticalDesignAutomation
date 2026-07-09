# zemax-skills

基于 Zemax OpticStudio ZOS-API 的光学自动化工作区，目前主要包含**公差分析自动化程序**和配套 Trae Skills。

---

## 1. 仓库结构

```text
zemax-skills-advance_TOL/
├── tolerance_analysis/                 公差分析自动化程序
│   ├── gui.py                          GUI 入口（推荐）
│   ├── gui_tol_wizard.py               GUI 公差填写向导（四页式，生成高级 Excel 配置）
│   ├── tol_run.py                      命令行入口
│   ├── check_stage1.py                 基础检查脚本
│   ├── check_field_mapping.py          视场映射检查脚本
│   ├── make_backup.py                  本地备份脚本
│   ├── build.ps1 / gui.spec            PyInstaller 打包脚本
│   ├── toltool/                        核心代码包
│   │   ├── pipeline.py                 主流程编排
│   │   ├── lens_scanner.py             zmx 只读扫描（镜片分组/指纹，主流程共用）
│   │   ├── excel_io.py                 Excel 配置读写
│   │   ├── standard_templates.py       标准模板与向导评价函数生成
│   │   ├── field_mapping.py            视场号/归一化视场映射
│   │   ├── tde_builder.py / mfe_builder.py / tsc_builder.py
│   │   ├── tol_runner.py / ztd_reader.py / sensitivity_reader.py
│   │   ├── current_settings.py / zos_connect.py
│   │   └── __init__.py
│   ├── tol_config_模板.xlsx            高级 Excel 配置模板
│   ├── zemax_config.ini.example        本机 Zemax 路径配置模板
│   ├── 公差分析程序_使用说明.md        用户手册
│   ├── 公差分析程序_需求文档.md        功能规格与后续规划
│   └── 公差分析工具_开发进度与测试记录.md
├── .trae/skills/
│   ├── zemax-zosapi-connector/         ZOS-API 连接 skill
│   ├── zemax-tolerance-analysis/       公差分析 skill
│   └── zemax-manual-kb/                Zemax 手册/示例全文检索知识库
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
6. 读取 ZTD 并导出统计 Excel（含敏感度 Top20 排序）。

当前支持三种主模式：

| 模式 | 说明 |
|---|---|
| 普通标准模板 | 不需要手写 Excel；支持 RX/TX、标准分析/完整视场分析、仅镜头面裁剪 |
| 使用 Zemax 当前设置 | 复用 zmx 中已有 TDE/MFE |
| 高级 Excel | 用 Excel 完全自定义公差、评价函数、REPORT、运行参数 |

其他能力：

- **GUI 公差填写向导**：扫描 zmx 自动分组镜片（含胶合组拆分/合并），逐镜片填写 14 项中文公差，按 5 类勾选评价函数（SPOT / GENC / MTF / 指向 / EFL·FOV），预览二次确认后生成全新高级 Excel 配置，不修改任何现有文件；支持 JSON 草稿断点续填；
- **面数指纹校验**：向导生成的配置记录镜头面结构指纹，运行前自动比对，防止镜头改动后误用旧配置；
- **后焦补偿器行程约束**：`补偿Min/Max` 一份参数同时写入 TDE COMP 硬限位与补偿评价函数 CTGT/CTLT 软约束，避免蒙卡优化把后焦推到极端位置；
- **运行期动态评价项**：中心指向偏移、多视场指向角、焦距偏移百分比、FOV，主波长自动替换；
- 标准模板"全部面=否"时按 TX/RX 与滤光片（AF32ECO / D263TECO）自动裁剪公差面范围；
- GUI 暗色界面（含 Win10 1809 暗色标题栏兼容）、实时日志、运行计时、两段式取消（温和取消 → 强制停止）、打开结果目录；
- 视场映射（自动插入缺失视场并改写 MFE/REPORT 视场号），输出 `field_mapping.txt`；
- 独立分析已有 `.ZTD`；
- 统计 Excel 包含名义值、Cpk1.33 上下限、均值、标准差、中位数、原始 MC 样本、REPORT 分项、COMP 项和按 REPORT 指标分列的敏感度 Top20。

---

## 3. 快速上手

### 3.1 启动 GUI（推荐）

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\gui.py
```

不想手写 Excel 的用户：GUI →「配置检查…」→「公差填写向导…」，按四页向导逐镜片填公差、选评价函数，生成配置后直接「开始分析」。

### 3.2 命令行运行

普通标准模板模式：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\tol_run.py --standard --zmx "镜头.zmx" --outdir "输出目录" --connect standalone --product-type RX --standard-template 标准分析 --tolerance-level 标准 --num-runs 20 --num-to-save 0
```

普通标准模板模式，仅镜头面参与公差分析（按 TX/RX 与滤光片自动裁剪）：

```powershell
.\.venv\Scripts\python.exe -u tolerance_analysis\tol_run.py --standard --zmx "镜头.zmx" --outdir "输出目录" --connect standalone --product-type RX --standard-template 标准分析 --tolerance-level 标准 --num-runs 20 --num-to-save 0 --lens-only-surfaces
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

### 3.3 打包 EXE（可选）

```powershell
powershell -ExecutionPolicy Bypass -File tolerance_analysis\build.ps1
```

---

## 4. 常用维护命令

基础语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile tolerance_analysis\gui.py tolerance_analysis\gui_tol_wizard.py tolerance_analysis\tol_run.py
```

核心模块语法检查：

```powershell
.\.venv\Scripts\python.exe -m py_compile tolerance_analysis\toltool\pipeline.py tolerance_analysis\toltool\tde_builder.py tolerance_analysis\toltool\mfe_builder.py tolerance_analysis\toltool\tsc_builder.py tolerance_analysis\toltool\tol_runner.py tolerance_analysis\toltool\ztd_reader.py tolerance_analysis\toltool\zos_connect.py tolerance_analysis\toltool\lens_scanner.py tolerance_analysis\toltool\sensitivity_reader.py
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
| [公差分析程序_使用说明.md](tolerance_analysis/公差分析程序_使用说明.md) | 使用者入口：怎么运行、怎么填配置、公差填写向导步骤、怎么看输出 |
| [公差分析程序_需求文档.md](tolerance_analysis/公差分析程序_需求文档.md) | 维护者入口：当前功能规格、设计边界、后续规划 |
| [公差分析工具_开发进度与测试记录.md](tolerance_analysis/公差分析工具_开发进度与测试记录.md) | 开发记录：关键变更、已知问题、回归测试清单 |
| [.trae/skills/zemax-tolerance-analysis/SKILL.md](.trae/skills/zemax-tolerance-analysis/SKILL.md) | AI 执行公差分析任务时必须遵守的 ZOS-API 经验 |
| [.trae/skills/zemax-zosapi-connector/SKILL.md](.trae/skills/zemax-zosapi-connector/SKILL.md) | AI 连接本机 Zemax 时使用的约束和流程 |
| [.trae/skills/zemax-manual-kb/README.md](.trae/skills/zemax-manual-kb/README.md) | Zemax 手册/官方示例全文检索知识库的构建与查询 |

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

本机 Zemax 安装路径可通过复制 `tolerance_analysis/zemax_config.ini.example` 为 `zemax_config.ini` 指定（该文件不入库）。

---

## 7. 当前状态

当前版本已具备内部试用能力：

- 高级 Excel 模式主链路可用，公差填写向导端到端已通过真实镜头验证（1000 次 MC）；
- 普通标准模板模式已完成 GUI / CLI 可用闭环，支持仅镜头面裁剪；
- 使用 Zemax 当前设置模式已实现；
- ZTD 统计、敏感度排序和独立 ZTD 分析已实现；
- 标准模板参数仍需结合真实项目继续定稿。

详细进度和待验证项见：

- [公差分析工具_开发进度与测试记录.md](tolerance_analysis/公差分析工具_开发进度与测试记录.md)
