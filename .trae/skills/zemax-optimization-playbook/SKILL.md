---
name: "zemax-optimization-playbook"
description: "Battle-tested Zemax ZOS-API optimization playbook: stability rules, MFE operand templates (f-theta/TRAY/CONF), MCE multi-config, aperture/material strategy. Invoke before ANY background optimization, MFE construction, Hammer run, or when optimization stalls/crashes."
---

# Zemax 优化实战手册（063C 四片式全程实测沉淀）

来源：063C_B0_RX 四片式 F/1.27 激光雷达接收镜头 17 轮优化实测（2023 R1 standalone）。
完整复盘与指标演进见项目文档 `08_光学优化实战经验库_063C_RX.md`；本 skill 只保留**执行时必须遵守的操作规则与模板**。
可复用脚本在 `output/workdir/`：`_dls_once.py`、`_hammer_once.py`、`_probe_mf.py`、`_mtf_scan.py`、`_defocus_setup.py`、`_defocus_targeted.py`。

## 一、稳定性铁律（违反必静默崩溃：python exit 0 但结果丢失）

1. **每个 python 进程只开一次优化工具**（DLS 或 Hammer），跑完立即 `SaveMeritFunction` + `SaveAs` 再退出；多轮 = 多进程调度。
2. DLS 只用 `Fixed_10_Cycles` / `Fixed_50_Cycles`；**禁用 `Automatic`**（病态起点会长跑崩溃）。
3. **MFE 里不放 MTFT/MTFS 行**再进后台 DLS（必崩）。MTF 用点列图+TRAY 代理优化；验证阶段用 `GetOperandValue` 逐点读（安全）。
4. Hammer：`tool.Run()` → `time.sleep(秒)` → `Cancel()` → `WaitForCompletion()` → `Close()`。**运行中禁止轮询 `IsRunning`/`CurrentMeritFunction`**；`RunAndWaitWithTimeout` 同样会崩。
5. 崩溃后先用 `_probe_mf.py` 实测 MF——文件可能已被后台保存，勿盲目重跑。
6. 每个关键节点（约束建完、每轮优化后）立即 SaveAs。

## 二、MFE 编写规则

- **自定义行全部插在 DMFS 上方**：`mfe.InsertNewOperandAt(dmfs_row)`。append 到底部会被向导重建抹掉。
- `find_dmfs_row` 必须双回退：`GetOperandTypeName()` 失败再试 `.Type`。
- 单元格写入用 **Int/Double 自动回退**（先按预期类型，失败换另一种）；RSCE cell4 是 Double，CTGT cell2/3 是 Int。
- 约束生效与否**以 `GetOperandValue` 实测为准**，.mf 文件里的 cell 显示值可能是行引用不可信。

### f-theta 畸变链（每视场 5 行）

```
CENY(像面,主波长,field) → CONS(EFL×θrad) → DIFF → PROB(×1000, mm→μm) → ABLT(target=限值μm, w=3)
```

- **PROB 倍数必须 `GetCellAt(3).DoubleValue = 1000.0`**（IntegerValue 写入无效、值恒0）；写完自校验 `PROB == DIFF×1000`，不等换单元格重试。
- ABLT 限内零惩罚 → 优化器会把值**压满边界**；要余量就收紧 target。

### 逐面制造约束

```
每片镜:  CTGT/CTLT/ETGT (s1,s2)      w=2
每空气段: CTGT + ETGT (s1,s2)         w=5   ← 中心+边缘双控, min 才是真实间隔
```

判线卡线坑：DFA 判 ≥0.8 时约束 target 要给 0.85（曾收敛在 0.7999 判 fail）。

### 像差定向（MTF 塌陷/T-S 分离救星）

```
TRAY(wave, Hx=0, Hy=视场归一化, Px=0, Py=±1)  Target=0  瓶颈视场 w=2.0, 其他视场 w=0.5 守护
```

Hy/Px/Py 是 Double。实测一轮解决 F5/F6 子午像差 340×，勿先上 COMA/ASTI 抽象像差操作数。

### EFL/BFL 括号

```
EFFL(w=0) → OPGT/OPLT 引用行；TTHI(最后镜面,平板前)(w=0) → OPGT
```

BFL 要尽量大：直接把 OPGT target 推到期望值（如 2.05），比软目标快且稳。

## 三、多重结构（MCE）

**触发条件**：单结构 DLS+Hammer 均收敛且需求是多工况（通焦/多温/变焦）。

```python
mce.AddConfiguration(False)              # 补足 config 数
mc_op = mce.AddOperand()
mc_op.ChangeType(ZOSAPI.Editors.MCE.MultiConfigOperandType.THIC)
mc_op.Param1 = 面号
mc_op.GetOperandCell(cfg).DoubleValue = 值   # cfg = 1..N
```

MFE 端 `CONF` 是开关操作数（其后行都在该 config 评估）：

```
CONF 1 → 全部业务约束
CONF 2 → 该 config 的定向行(如离焦处最差视场 RSCE)
CONF 3 → ...
CONF 1 → ★必须复位，忘记则后续行全跑错结构
DMFS   → 向导 Configuration=0 时逐结构生成点列图
```

坑：单结构文件分支后重开向导会留下 CONF/BLNK 残骸行（无害但干扰公差 TSC 的 REPORT 行号计数）。
物理极限：多重结构能**平移**通焦包络、不能加宽；F/# 焦深 ≈ ±2λF²，超出即规格谈判或上非球面。

## 四、口径与材料

- 净口径统一（结构件需求）：**凸面**（前表面 R>0 / 后表面 R<0）`SemiDiameter=x` 固定；**凹面/平面**只 `MechanicalSemiDiameter=x`，光学口径保留自动。全部面强行统一 = 性能崩盘（实测 GEO 19→38μm）。
- 空气间隔真实最小值 = min(中心 TTHI, 边缘 ETLT)，两者都约束。
- Hammer 前锁料：`surf.MaterialCell.MakeSolveFixed()`；跑完**回读 `surf.Material` 校验**（Substitute 状态会被偷换成贵料）。
- 手工换料后按 `(n_new-1)/(n_old-1)` 缩放该镜两面半径再 DLS。
- 平板区固定间隔：`ThicknessCell.MakeSolveFixed()` 后赋值；留变量会被压成**负厚度**。每轮结束检查全部厚度非负。

## 五、优化路线决策树

```
基线评测 → 缺口
1. 约束体系(DMFS上方) + 短循环 DLS
2. 卡住 → 逐视场/逐面诊断找最差项 → TRAY/RSCE 定向 + 权重再平衡 + DLS
3. 仍卡 → 限时 Hammer(180s, 按需锁料) —— 强约束刚改变后最有效
4. 多工况需求 → MCE 多重结构
5. 物理极限 → 规格谈判 / 非球面 / 结构升级
```

- 每轮只改一类东西（约束/权重/材料/口径），否则无法归因。
- 视场权重：瓶颈视场加倍，边缘视场不低于 1.5。
- 正式指标以 `batch_validate_rx_lenses` 复测口径为准；脚本内 spot 仅用于同轮前后对比。
