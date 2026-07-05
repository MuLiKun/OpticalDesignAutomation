# Zemax ZOS-API 自动化执行器设计文档

## 1. 文档目的

本文档定义激光雷达镜头自动设计中 Zemax 自动化执行器的设计目标、运行方式、核心接口、回读验证机制和异常检查清单。

执行器负责把 AI 或规则系统生成的设计计划，转化为真实、稳定、可验证的 Zemax 操作。

---

## 2. 设计目标

执行器必须具备以下能力：

1. 稳定连接 Zemax；
2. 加载和保存 Zemax 文件；
3. 新建激光雷达镜头系统；
4. 设置工作波长、视场、孔径、探测器面或像面；
5. 设置表面、材料、光阑、非球面；
6. 设置变量；
7. 自动构建激光雷达镜头 Merit Function；
8. 执行优化；
9. 自动读取光斑、能量、视场、照度等分析结果；
10. 导出图表、表格和日志；
11. 检查 Zemax 静默失败；
12. 支持失败回退和检查点恢复。

---

## 3. 推荐运行方式

第一阶段建议采用：

```text
Python + ZOS-API + Interactive Extension 模式
```

原因：

1. 方便调试；
2. 可直接观察 Zemax GUI；
3. 出错时容易定位；
4. 适合早期开发和验证；
5. 后续可迁移到 Standalone 模式。

---

## 4. 核心接口设计

## 4.1 Zemax 连接接口

```text
connect_zemax()
disconnect_zemax()
check_license()
get_zemax_version()
get_current_system()
```

必须验证：

1. 是否连接成功；
2. 是否获得系统对象；
3. 当前系统是否可编辑；
4. Zemax 版本是否符合要求；
5. 授权是否可用。

---

## 4.2 文件操作接口

```text
load_lens_file(file_path)
save_lens_file(file_path)
save_as_checkpoint(task_id, stage_name)
reload_lens_file(file_path)
```

必须验证：

1. 文件是否存在；
2. 加载是否成功；
3. 表面数量是否正确；
4. 保存后是否可重新加载；
5. 检查点文件是否完整。

---

## 4.3 系统设置接口

```text
set_aperture(aperture_type, value)
set_wavelengths(wavelengths_nm)
set_fields(fields)
set_detector_or_image_plane(position, size)
set_units(unit)
set_stop_surface(surface_id)
```

回读验证：

| 操作 | 验证 |
|---|---|
| 设置孔径 | 回读孔径类型和数值 |
| 设置波长 | 回读波长数量、值、权重 |
| 设置视场 | 回读视场数量、坐标、权重 |
| 设置探测器面/像面 | 回读像面位置、尺寸或对应约束 |
| 设置单位 | 回读系统单位 |
| 设置光阑 | 回读光阑面号 |

激光雷达项目中特别要确认：

1. 工作波长是否正确，第一阶段优先支持 905±15nm 和 940±15nm；
2. 用户输入的视场角按全角处理，写入 Zemax 前必须转换并回读验证；
3. 接收端以 SPAD 面阵探测器为主，其他镜头可支持 CMOS；
4. 接收端通常需要考虑 F-theta 特性和扫描线性；
5. 发射端后续扩展时，以远场发散角或准直光束为评价目标。

---

## 4.4 表面结构接口

```text
add_surface(index)
delete_surface(index)
set_radius(surface_id, value)
set_thickness(surface_id, value)
set_material(surface_id, glass_name)
set_semi_diameter(surface_id, value)
set_conic(surface_id, value)
set_asphere_coeff(surface_id, order, value)
set_surface_type(surface_id, surface_type)
```

每次构建或修改结构后，必须输出表面参数表：

| Surface | Radius | Thickness | Glass | Semi-Diameter | Type | Conic | Variable |
|---|---|---|---|---|---|---|---|

必须验证：

1. 表面数量是否符合预期；
2. Radius 是否正确；
3. Thickness 是否正确；
4. Glass 是否成功设置；
5. 材料是否适合 905±15nm 或 940±15nm；
6. 材料组合是否符合全玻璃、玻塑混合、玻璃+玻璃非球面要求；
7. 如包含塑料镜片，是否标记后续热分析；
8. 非球面类型是否正确；
9. 圆锥系数和多项式项是否写入；
10. 是否出现负厚度或异常空气间隔。

---

## 4.5 变量设置接口

```text
set_radius_variable(surface_id, enabled)
set_thickness_variable(surface_id, enabled)
set_conic_variable(surface_id, enabled)
set_asphere_coeff_variable(surface_id, order, enabled)
set_glass_variable(surface_id, enabled)
export_variable_table()
```

变量释放原则：

1. 先释放少量变量；
2. 系统稳定后再增加变量；
3. 优先控制焦距、视场、光斑和探测器匹配；
4. 非球面先释放圆锥系数；
5. 后续逐步释放低阶非球面项；
6. 每次释放变量后导出变量表。

---

## 4.6 Merit Function 接口

```text
clear_merit_function()
load_default_merit_function()
build_merit_with_optimization_wizard(goal_type)
build_manufacturing_merit_constraints()
switch_merit_goal(goal_type)
add_operand(operand_type, params)
add_efl_constraint(target, weight)
add_f_number_or_na_constraint(target, weight)
add_fov_constraint(target, weight)
add_spot_constraint(limit_um, weight)
add_encircled_energy_constraint(radius_um, target_ratio, weight)
add_relative_illumination_constraint(min_ratio, weight)
add_distortion_or_scan_linearity_constraint(limit, weight)
add_ttl_constraint(max_value, weight)
add_bfl_constraint(target_or_range, weight)
add_thickness_constraints(min_center, min_edge, min_air)
export_merit_function_table()
```

操作数表必须导出：

| Row | Operand | Target | Weight | Surf | Wave | Field | Value | Comment |
|---|---|---|---|---|---|---|---|---|

关键要求：

1. 第一阶段优先调用 Zemax 优化向导生成基础 Merit Function，而不是一开始手工堆像差操作数；
2. 初始优化目标优先为 Spot Diagram / 点列图，必要时切换或补充 MTF、Wavefront；
3. 默认 Merit Function 需要叠加制造约束，以及焦距或 F/# 约束；
4. 操作数引用的面号必须正确；
5. 操作数引用的视场必须正确；
6. 操作数单位必须明确；
7. 光斑和能量指标需与探测器尺寸对应；
8. FOV、畸变、扫描线性度需先确认业务定义；
9. 用户明确提供或确认操作数前，系统生成的操作数只能作为草案；
10. 每次修改 Merit Function 后必须导出快照。

---

## 4.7 优化接口

```text
run_local_optimization(cycles)
run_hammer_optimization(duration)
run_optimization_stage(stage_config)
stop_optimization()
rollback_to_checkpoint(checkpoint_path)
```

建议流程：

```text
保存检查点
→ 测量优化前指标
→ 执行优化
→ 测量优化后指标
→ 判断是否改善
→ 保存结果或回退
```

每轮记录：

1. 当前阶段名称；
2. 当前工作波长；
3. 当前 F/# 或 NA；
4. 当前视场；
5. 当前变量数量；
6. 当前 Merit Function 快照；
7. 优化前指标；
8. 优化后指标；
9. 是否成功；
10. 是否需要回退。

---

## 4.8 分析结果接口

```text
get_efl()
get_f_number_or_na()
get_fov()
get_bfl()
get_ttl()
get_spot_rms()
get_spot_max()
get_encircled_energy(radius_um)
get_relative_illumination()
get_distortion_or_scan_linearity()
check_ray_trace_all_fields()
export_analysis_plots()
```

单位要求：

| 指标 | 单位 |
|---|---|
| Wavelength | nm |
| EFL | mm |
| F/# | 无量纲 |
| NA | 无量纲 |
| FOV | degree |
| BFL | mm |
| TTL | mm |
| Spot RMS | μm |
| Spot Max | μm |
| Encircled Energy | ratio 或 % |
| Relative Illumination | ratio 或 % |
| Distortion | % |
| Scan Linearity Error | % 或 mm |
| Thickness | mm |

---

## 5. Zemax 静默失败检查清单

| 风险 | 检查方法 |
|---|---|
| 添加表面失败 | 回读表面数量 |
| 删除表面失败 | 回读表面数量和相邻厚度 |
| 设置视场失败 | 回读视场数量、坐标、权重 |
| 设置波长失败 | 回读波长数量、值、权重 |
| 设置材料失败 | 回读 Glass 名称，并检查波段适用性 |
| 设置变量失败 | 导出变量表 |
| 非球面设置失败 | 回读 Surface Type、Conic、系数 |
| 操作数引用错误 | 导出 Merit Function 表 |
| 单位错误 | 与 Zemax GUI 文本报告对照 |
| 光线不可追迹 | 全视场、全波长 Ray Trace 检查 |
| 保存失败 | 重新加载保存文件验证 |
| 长时间运行断连 | 分阶段保存检查点并重连 |

---

## 6. 检查点机制

建议每个阶段保存检查点：

```text
checkpoint_baseline.zos
checkpoint_fov_setup.zos
checkpoint_spot_control.zos
checkpoint_energy_control.zos
checkpoint_package_control.zos
checkpoint_final.zos
```

---

## 7. 已确认执行器方向与后续确认项

当前已确认：

1. 第一阶段先以顺序模式为主；
2. 评价重点优先为 Spot、Encircled Energy、探测器匹配和 F-theta 扫描线性；
3. 材料近红外透过率需要作为自动检查项；
4. 工作波段优先支持 905±15nm 和 940±15nm；
5. 使用塑料镜片时需要标记热分析需求。

当前决策：

1. 第一阶段不涉及非序列模式；
2. 热分析第一阶段先做风险标记，可预留后续接入口，但塑料非球面目前不是重点。

---

## 8. 总结

Zemax 自动化执行器的核心价值不是“能调用 API”，而是“能可靠调用 API”。

最重要原则：

```text
每次写入都要回读；
每轮优化都要保存；
每个指标都要带单位；
每个失败都要可复盘。
```
