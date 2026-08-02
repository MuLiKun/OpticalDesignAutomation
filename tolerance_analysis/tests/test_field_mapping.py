"""tests/test_field_mapping.py —— field_mapping.py 核心逻辑单元测试。

测试视场匹配、目标解析、标签生成等纯函数逻辑。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from toltool.field_mapping import (FieldItem, FieldMatch, FieldMappingResult,
                                   parse_targets, sort_key, report_label,
                                   build_field_items, _target_value,
                                   _nearest)  # noqa: E402

import unittest


class TestParseTargets(unittest.TestCase):
    def test_default(self):
        result = parse_targets(None)
        self.assertEqual(result, [0, -0.25, 0.25, -0.5, 0.5, -0.7, 0.7, -0.9, 0.9, -1, 1])

    def test_custom(self):
        result = parse_targets("0,0.5,1")
        self.assertEqual(result, [0, 0.5, 1])

    def test_empty(self):
        self.assertEqual(parse_targets(""), [0, -0.25, 0.25, -0.5, 0.5, -0.7, 0.7, -0.9, 0.9, -1, 1])


class TestSortKey(unittest.TestCase):
    def test_zero(self):
        k = sort_key(0)
        self.assertEqual(k, (0.0, 0, 0.0))

    def test_positive(self):
        k = sort_key(0.5)
        self.assertEqual(k, (0.5, 1, 0.5))

    def test_negative(self):
        k = sort_key(-0.9)
        self.assertEqual(k, (0.9, 0, -0.9))


class TestReportLabel(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(report_label(0), "F0")

    def test_positive(self):
        self.assertEqual(report_label(0.5), "F0.5")

    def test_negative(self):
        self.assertEqual(report_label(-0.9), "F-0.9")

    def test_one(self):
        self.assertEqual(report_label(1), "F1")
        self.assertEqual(report_label(-1), "F-1")


class TestFieldItem(unittest.TestCase):
    def test_create(self):
        item = FieldItem(field_no=1, x=0, y=0, field_abs=0, normalized=0)
        self.assertEqual(item.field_no, 1)
        self.assertEqual(item.normalized, 0)
        self.assertEqual(item.x, 0)
        self.assertEqual(item.y, 0)

    def test_with_coords(self):
        item = FieldItem(field_no=2, x=0, y=0.5, field_abs=0.5, normalized=0.5)
        self.assertEqual(item.normalized, 0.5)


class TestBuildFieldItems(unittest.TestCase):
    def test_from_xy(self):
        items = build_field_items([(0, 0), (0, 0.5), (0, 1)])
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].field_no, 1)
        self.assertEqual(items[1].field_no, 2)
        self.assertEqual(items[2].field_no, 3)

    def test_empty(self):
        self.assertEqual(build_field_items([]), [])


class TestNearest(unittest.TestCase):
    def test_exact(self):
        items = [
            FieldItem(field_no=1, x=0, y=0, field_abs=0, normalized=0),
            FieldItem(field_no=2, x=0, y=0.5, field_abs=0.5, normalized=0.5),
        ]
        result = _nearest(items, 0.5)
        self.assertIsNotNone(result)
        self.assertEqual(result.field_no, 2)

    def test_approximate(self):
        items = [
            FieldItem(field_no=1, x=0, y=0, field_abs=0, normalized=0),
            FieldItem(field_no=2, x=0, y=0.5, field_abs=0.5, normalized=0.5),
        ]
        result = _nearest(items, 0.51)
        self.assertIsNotNone(result)
        self.assertEqual(result.field_no, 2)


class TestTargetValue(unittest.TestCase):
    def test_exact_match(self):
        """_target_value 返回匹配目标的归一化视场值（float）。"""
        targets = [0.0, 0.5]
        fields = [
            FieldItem(field_no=1, x=0, y=0, field_abs=0, normalized=0),
            FieldItem(field_no=2, x=0, y=0.5, field_abs=0.5, normalized=0.5),
        ]
        # 提供 final_matches 为空时，返回 explicit 值本身
        result = _target_value({"目标归一化视场": 0.5}, fields, [])
        self.assertEqual(result, 0.5)

        result = _target_value({"目标归一化视场": 0.0}, fields, [])
        self.assertEqual(result, 0.0)


class TestFieldMappingResult(unittest.TestCase):
    def test_to_dict(self):
        result = FieldMappingResult(
            enabled=True,
            targets=[0, 0.5],
            threshold=0.05,
            insert_strategy="自动插入",
            original_fields=[],
            final_fields=[],
            final_matches=[],
            inserted_fields=[],
            mfe_updates=0,
            report_updates=0,
            messages=[],
        )
        data = result.to_dict()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["targets"], [0, 0.5])
        self.assertEqual(data["threshold"], 0.05)