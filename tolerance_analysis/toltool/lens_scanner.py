"""lens_scanner.py —— 只读扫描 .zmx 文本，识别镜片分组与指纹。

服务「公差填写向导」与 pipeline 的标准模板镜头面裁剪：
- 纯文本解析，不打开 Zemax，不依赖 GUI；
- 解析每面：面号、曲率、厚度、材料、注释、类型（COORDBRK/MIRROR/光阑）；
- 自动分组：连续带玻璃材料的面归为一个（胶合）镜片组件；
- 计算面数指纹，供生成的配置 Excel 在运行前校验 zmx 未被改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._utils import _num

# 滤光片材料（精确匹配，大写）
FILTER_MATERIALS = {"AF32ECO", "D263TECO"}

# 视为"非玻璃材料"的 GLAS 取值（反射镜等）
_NON_GLASS = {"MIRROR"}


@dataclass
class SurfaceInfo:
    surface: int                 # 面号
    curv: float | None = None    # 曲率（0=平面）
    thickness: float | None = None   # DISZ 厚度（INFINITY → None）
    glass: str = ""              # GLAS 材料名（原样保留大小写）
    comment: str = ""            # COMM 注释
    surf_type: str = "STANDARD"  # TYPE 行（如 COORDBRK）
    is_stop: bool = False        # STOP 行

    @property
    def is_plane(self) -> bool:
        return self.curv is not None and abs(self.curv) <= 1e-12

    @property
    def is_coordbrk(self) -> bool:
        return self.surf_type.upper() == "COORDBRK"

    @property
    def is_mirror(self) -> bool:
        return self.glass.strip().upper() in _NON_GLASS

    @property
    def has_glass(self) -> bool:
        """是否带真实玻璃材料（排除 MIRROR 等非玻璃）。"""
        name = self.glass.strip().upper()
        return bool(name) and name not in _NON_GLASS

    @property
    def is_filter(self) -> bool:
        return self.glass.strip().upper() in FILTER_MATERIALS


@dataclass
class LensGroup:
    """一个镜片组件：单片=2 面；双胶合=3 面；三胶合=4 面。"""
    index: int                   # 镜片序号（从 1 开始，按光路顺序）
    start_surface: int           # 第一面面号
    end_surface: int             # 最后一面面号（出射面，不带玻璃）
    materials: list[str] = field(default_factory=list)   # 各玻璃段材料
    is_filter: bool = False      # 是否滤光片（材料精确匹配）
    is_plate: bool = False       # 是否双面平板玻璃（所有面曲率为 0）

    @property
    def is_cemented(self) -> bool:
        return len(self.materials) >= 2

    @property
    def kind(self) -> str:
        if self.is_filter:
            return "滤光片"
        if self.is_plate:
            return "平板玻璃"
        if len(self.materials) == 3:
            return "三胶合"
        if len(self.materials) == 2:
            return "双胶合"
        return "单片"

    @property
    def label(self) -> str:
        """GUI 展示用标签，如：镜片2（双胶合）S5-S7 H-ZF4+H-K51"""
        return (f"镜片{self.index}（{self.kind}）"
                f"S{self.start_surface}-S{self.end_surface} "
                f"{'+'.join(self.materials)}")


@dataclass
class ScanResult:
    zmx_path: str
    surfaces: list[SurfaceInfo] = field(default_factory=list)
    groups: list[LensGroup] = field(default_factory=list)
    fingerprint: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return bool(self.surfaces)

    @property
    def surf_type_map(self) -> dict[int, str]:
        """面号 → TYPE（大写，如 STANDARD/EVENASPH/COORDBRK）。

        供公差生成按面型分发操作数：TSDX/TSDY/TSTX/TSTY 仅支持
        Standard/Irregular 面，其余面型需改用单面元件操作数。
        """
        return {s.surface: s.surf_type.strip().upper() for s in self.surfaces}


def read_zmx_text(path: str) -> str:
    """按常见编码依次尝试解码 zmx 文本。"""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-16", "utf-8-sig", "mbcs", "latin1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("latin1", errors="ignore")


def parse_surfaces(path: str) -> list[SurfaceInfo]:
    """解析 zmx 文本为 SurfaceInfo 列表（含厚度/注释/类型/光阑标记）。"""
    surfaces: list[SurfaceInfo] = []
    current: SurfaceInfo | None = None
    for raw in read_zmx_text(path).splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0].upper()
        if key == "SURF" and len(parts) >= 2:
            try:
                idx = int(float(parts[1]))
            except ValueError:
                current = None
                continue
            current = SurfaceInfo(surface=idx)
            surfaces.append(current)
            continue
        if current is None:
            continue
        if key == "CURV" and len(parts) >= 2:
            current.curv = _num(parts[1])
        elif key == "DISZ" and len(parts) >= 2:
            if parts[1].upper() == "INFINITY":
                current.thickness = None
            else:
                current.thickness = _num(parts[1])
        elif key == "GLAS" and len(parts) >= 2:
            current.glass = parts[1].strip()
        elif key == "COMM":
            current.comment = line[4:].strip()
        elif key == "TYPE" and len(parts) >= 2:
            current.surf_type = parts[1].strip()
        elif key == "STOP":
            current.is_stop = True
    return surfaces


def group_lenses(surfaces: list[SurfaceInfo]) -> tuple[list[LensGroup], list[str]]:
    """把面序列分组为镜片组件。

    规则：
    - 跳过坐标断点（COORDBRK）与反射镜（GLAS MIRROR）面，并记录警告；
    - 连续带玻璃的面构成一个胶合组：起始面=第一个玻璃面，
      结束面=最后一个玻璃面的下一面（出射面）；
    - 无玻璃的面（物面/光阑/空气间隔/像面）不单独成组。
    """
    groups: list[LensGroup] = []
    warnings: list[str] = []
    i = 0
    n = len(surfaces)
    while i < n:
        s = surfaces[i]
        if s.is_coordbrk:
            warnings.append(f"S{s.surface} 为坐标断点，已跳过。")
            i += 1
            continue
        if s.is_mirror:
            warnings.append(f"S{s.surface} 为反射镜，已跳过（本工具不支持反射镜公差）。")
            i += 1
            continue
        if not s.has_glass:
            i += 1
            continue
        # 一个玻璃段的开始：收集连续玻璃面
        start = i
        materials = []
        j = i
        while j < n and surfaces[j].has_glass and not surfaces[j].is_coordbrk:
            materials.append(surfaces[j].glass)
            j += 1
        if j >= n:
            warnings.append(
                f"S{surfaces[start].surface} 开始的玻璃段缺少出射面（文件可能不完整）。")
            break
        end_surf = surfaces[j]  # 第一个不带玻璃的面 = 出射面
        seg = surfaces[start:j + 1]
        all_plane = all(x.is_plane for x in seg if x.curv is not None) and \
            all(x.curv is not None for x in seg)
        group = LensGroup(
            index=len(groups) + 1,
            start_surface=surfaces[start].surface,
            end_surface=end_surf.surface,
            materials=materials,
            is_filter=any(x.is_filter for x in seg),
            is_plate=(len(materials) == 1 and all_plane),
        )
        groups.append(group)
        i = j + 1
    return groups, warnings


def fingerprint(surfaces: list[SurfaceInfo]) -> str:
    """面数指纹：面总数 + 各玻璃面『面号:材料』摘要。

    用于生成的配置 Excel 在运行前校验 zmx 结构未被改动。
    """
    glass_part = ",".join(
        f"{s.surface}:{s.glass.strip().upper()}" for s in surfaces if s.has_glass)
    return f"N{len(surfaces)}|{glass_part}"


def scan(zmx_path: str) -> ScanResult:
    """扫描入口：解析 → 分组 → 指纹。解析失败返回 succeeded=False 的结果。"""
    result = ScanResult(zmx_path=zmx_path)
    try:
        result.surfaces = parse_surfaces(zmx_path)
    except OSError as e:
        result.warnings.append(f"读取镜头文件失败：{type(e).__name__}: {e}")
        return result
    if not result.surfaces:
        result.warnings.append(
            "未从镜头文件读取到面数据（可能为 .zos 二进制或非标准格式）。")
        return result
    result.groups, group_warnings = group_lenses(result.surfaces)
    result.warnings.extend(group_warnings)
    result.fingerprint = fingerprint(result.surfaces)
    if not result.groups:
        result.warnings.append("未识别到任何镜片组件（无带玻璃材料的面）。")
    return result
