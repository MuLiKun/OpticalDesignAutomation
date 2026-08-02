"""_utils.py —— 公差分析工具包的公共工具函数。

所有模块共享的辅助函数集中在此，避免重复定义。
"""

from __future__ import annotations

import re


# 用于 _enum_name 的正则（匹配 3-4 个大写字母）
_OP_RE = re.compile(r"[A-Z]{3,4}")


def _yes(v) -> bool:
    """判断 Y/YES/1/TRUE/是 等肯定值。"""
    return str(v).strip().upper() in ("Y", "YES", "1", "TRUE", "是")


def _num(v, default=None):
    """安全转浮点；None / 空字符串 / 非法字符串 返回 default。"""
    if v is None or (isinstance(v, str) and str(v).strip() == ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v, default: int) -> int:
    """安全转整数。先转 float 再 int 以兼容 '3.0' 这类字符串。"""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _enum_name(value) -> str:
    """从 Zemax 枚举值（如 'ToleranceOperandType.TFRN'）中提取操作数名（如 'TFRN'）。"""
    text = str(value or "").strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    text = text.upper()
    match = _OP_RE.search(text)
    return match.group(0) if match else text


def _field_label(value: float) -> str:
    """归一化视场数值 → 标签（0 → 'F0', 0.5 → 'F0.5'）。"""
    if abs(float(value)) < 1e-12:
        return "F0"
    return f"F{float(value):g}"


def _safe_name(name: str) -> str:
    """文件名安全化：特殊字符/空格 → '_'，去除首尾 '._'，空则回退 'lens'。"""
    text = re.sub(r'[<>:"/\\|?*\s]+', "_", str(name).strip())
    text = text.strip("._")
    return text or "lens"


def _fmt_num(value) -> str:
    """格式化数字为 4 位小数；None 返回 '-'；非数字原样返回。"""
    if value is None:
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)