"""tests/test_utils.py —— _utils.py 核心工具函数单元测试。"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from toltool._utils import _yes, _num, _as_int, _enum_name, _field_label, _safe_name, _fmt_num  # noqa: E402


import unittest


class TestYes(unittest.TestCase):
    def test_y_values(self):
        for v in ("Y", "y", "YES", "yes", "Yes", "1", "TRUE", "true", "是"):
            self.assertTrue(_yes(v), f"expected True for {v!r}")

    def test_n_values(self):
        for v in ("N", "n", "NO", "no", "0", "FALSE", "false", "否", "", None, "abc"):
            self.assertFalse(_yes(v), f"expected False for {v!r}")

    def test_whitespace(self):
        self.assertTrue(_yes(" Y "))
        self.assertFalse(_yes(" n "))


class TestNum(unittest.TestCase):
    def test_valid_numbers(self):
        self.assertEqual(_num("3.14"), 3.14)
        self.assertEqual(_num("0"), 0.0)
        self.assertEqual(_num("-1.5"), -1.5)
        self.assertEqual(_num(42), 42.0)
        self.assertEqual(_num(3.14), 3.14)

    def test_none_empty(self):
        self.assertIsNone(_num(None))
        self.assertIsNone(_num(""))
        self.assertIsNone(_num("  "))

    def test_invalid(self):
        self.assertIsNone(_num("abc"))
        self.assertIsNone(_num("1,2"))

    def test_default(self):
        self.assertEqual(_num("abc", 0), 0)
        self.assertEqual(_num(None, -1), -1)
        self.assertEqual(_num("", 42), 42)


class TestAsInt(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(_as_int("42", 0), 42)
        self.assertEqual(_as_int("3.0", 0), 3)
        self.assertEqual(_as_int("-1", 0), -1)
        self.assertEqual(_as_int(7, 0), 7)

    def test_default(self):
        self.assertEqual(_as_int("abc", 99), 99)
        self.assertEqual(_as_int("", 10), 10)
        self.assertEqual(_as_int(None, 5), 5)


class TestEnumName(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(_enum_name("ToleranceOperandType.TFRN"), "TFRN")
        self.assertEqual(_enum_name("ToleranceOperandType.TTHI"), "TTHI")
        self.assertEqual(_enum_name("ToleranceOperandType.TEDX"), "TEDX")

    def test_already_short(self):
        self.assertEqual(_enum_name("TFRN"), "TFRN")
        self.assertEqual(_enum_name("BLNK"), "BLNK")

    def test_empty(self):
        self.assertEqual(_enum_name(""), "")
        self.assertEqual(_enum_name(None), "")


class TestFieldLabel(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_field_label(0), "F0")
        self.assertEqual(_field_label(0.0), "F0")
        self.assertEqual(_field_label(1e-15), "F0")

    def test_positive(self):
        self.assertEqual(_field_label(0.5), "F0.5")
        self.assertEqual(_field_label(1.0), "F1")
        self.assertEqual(_field_label(0.25), "F0.25")

    def test_negative(self):
        self.assertEqual(_field_label(-0.9), "F-0.9")
        self.assertEqual(_field_label(-1.0), "F-1")


class TestSafeName(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_safe_name("lens"), "lens")
        self.assertEqual(_safe_name("My Lens"), "My_Lens")
        self.assertEqual(_safe_name("test.zmx"), "test.zmx")

    def test_special_chars(self):
        self.assertEqual(_safe_name('file<>:"/\\|?*'), "file")
        self.assertEqual(_safe_name("a:b:c"), "a_b_c")

    def test_trim_dots(self):
        self.assertEqual(_safe_name("._lens"), "lens")
        self.assertEqual(_safe_name("lens._"), "lens")

    def test_empty(self):
        self.assertEqual(_safe_name(""), "lens")
        self.assertEqual(_safe_name("._"), "lens")
        self.assertEqual(_safe_name("  "), "lens")


class TestFmtNum(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(_fmt_num(3.14159), "3.1416")
        self.assertEqual(_fmt_num(0.0), "0.0000")
        self.assertEqual(_fmt_num(-1.5), "-1.5000")

    def test_none(self):
        self.assertEqual(_fmt_num(None), "-")

    def test_other(self):
        self.assertEqual(_fmt_num("abc"), "abc")
        self.assertEqual(_fmt_num(""), "")