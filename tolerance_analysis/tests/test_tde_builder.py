"""tests/test_tde_builder.py —— tde_builder.py 核心逻辑单元测试。

测试 TolItem 数据类、操作数分类、非标准面替换等纯函数逻辑。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from toltool.tde_builder import (TolItem, PAIRED_OPS, _SURFACE_TO_ELEMENT_OPS,
                                 _cat_name)  # noqa: E402

import unittest


class TestTolItem(unittest.TestCase):
    def test_basic(self):
        item = TolItem(op="TFRN", surf1=1, surf2=1, vmin=-0.5, vmax=0.5, comment="半径")
        self.assertEqual(item.op, "TFRN")
        self.assertEqual(item.surf1, 1)
        self.assertEqual(item.surf2, 1)
        self.assertEqual(item.vmin, -0.5)
        self.assertEqual(item.vmax, 0.5)

    def test_key(self):
        item = TolItem(op="TTHI", surf1=2, surf2=3, vmin=-0.1, vmax=0.1)
        self.assertEqual(item.key(), ("TTHI", 2, 3))

    def test_default_comment(self):
        item = TolItem(op="TEDX", surf1=4, surf2=4, vmin=-0.05, vmax=0.05)
        self.assertEqual(item.comment, "")


class TestPairedOps(unittest.TestCase):
    def test_paired_ops(self):
        self.assertIn("TTHI", PAIRED_OPS)
        self.assertIn("TEDX", PAIRED_OPS)
        self.assertIn("TEDY", PAIRED_OPS)
        self.assertIn("TETX", PAIRED_OPS)
        self.assertIn("TETY", PAIRED_OPS)

    def test_non_paired_ops(self):
        self.assertNotIn("TFRN", PAIRED_OPS)
        self.assertNotIn("TIRR", PAIRED_OPS)
        self.assertNotIn("TSDX", PAIRED_OPS)


class TestSurfaceToElementOps(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(_SURFACE_TO_ELEMENT_OPS["TSDX"], "TEDX")
        self.assertEqual(_SURFACE_TO_ELEMENT_OPS["TSDY"], "TEDY")
        self.assertEqual(_SURFACE_TO_ELEMENT_OPS["TSTX"], "TETX")
        self.assertEqual(_SURFACE_TO_ELEMENT_OPS["TSTY"], "TETY")

    def test_completeness(self):
        self.assertEqual(len(_SURFACE_TO_ELEMENT_OPS), 4)


class TestCatName(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(_cat_name("半径"), "半径")
        self.assertEqual(_cat_name("厚度"), "厚度")

    def test_aliases(self):
        self.assertEqual(_cat_name("曲率半径"), "半径")
        self.assertEqual(_cat_name("曲率半径公差"), "半径")
        self.assertEqual(_cat_name("Zernike不规则度"), "Zernike不规则度")
        self.assertEqual(_cat_name("泽尼克不规则"), "Zernike不规则度")
        self.assertEqual(_cat_name("泽尼克不规则度"), "Zernike不规则度")

    def test_whitespace(self):
        self.assertEqual(_cat_name("  曲率半径  "), "半径")
        self.assertEqual(_cat_name(""), "")
        self.assertEqual(_cat_name(None), "")

    def test_unknown(self):
        self.assertEqual(_cat_name("XYZ"), "XYZ")
        self.assertEqual(_cat_name("X"), "X")