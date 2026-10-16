import math
import unittest

from scad2fusion.planar import Region, Scalar


def expr(value, text=None):
    return {"value": value, "text": str(value) if text is None else text, "deps": []}


def node(op, args=None, children=None, line=1):
    return {
        "op": op,
        "args": {} if args is None else args,
        "children": [] if children is None else children,
        "line": line,
    }


def point(x, y):
    return [expr(x), expr(y)]


class ScalarTests(unittest.TestCase):
    def test_arithmetic_accepts_literals_and_preserves_symbolic_text(self):
        width = Scalar(20, "width")

        self.assertEqual((width + 0).text, "width")
        self.assertEqual((2 * width).value, 40.0)
        self.assertIn("width", (2 * width).text)
        self.assertEqual((width - width).value, 0.0)
        self.assertEqual((width - width).text, "0")
        self.assertEqual((width / 1).text, "width")

    def test_from_ir_accepts_serialized_expression_and_number(self):
        self.assertEqual(Scalar.from_ir(expr(12, "length / 2")).text, "length / 2")
        self.assertEqual(Scalar.from_ir(3).value, 3.0)


class PlanarRegionTests(unittest.TestCase):
    def test_square_has_four_lines_bounds_and_membership(self):
        region = Region(node("square", {"size": [expr(20), expr(10)], "center": expr(True)}))

        self.assertEqual(len(region.curves), 4)
        self.assertTrue(all(curve["kind"] == "line" for curve in region.curves))
        self.assertEqual(region.bounds, (-10.0, -5.0, 10.0, 5.0))
        self.assertTrue(region.contains(0, 0))
        self.assertFalse(region.contains(11, 0))

    def test_offset_square_expands_to_true_rounded_rectangle(self):
        region = Region(
            node(
                "offset",
                {"r": expr(2)},
                [node("square", {"size": [expr(20), expr(10)], "center": expr(True)})],
            )
        )

        self.assertEqual(region.bounds, (-12.0, -7.0, 12.0, 7.0))
        self.assertEqual([curve["kind"] for curve in region.curves].count("line"), 4)
        self.assertEqual([curve["kind"] for curve in region.curves].count("arc"), 4)
        self.assertTrue(region.contains(11, 0))
        self.assertFalse(region.contains(12, 7))
        self.assertFalse(region.contains(12, 6))

    def test_offset_preserves_symbolic_square_corners(self):
        radius = expr(4, "R")
        square = node(
            "square",
            {"size": [expr(92, "L - 2 * R"), expr(62, "W - 2 * R")], "center": expr(True)},
        )
        region = Region(
            node("translate", {"v": [radius, radius]}, [node("offset", {"r": radius}, [square])])
        )

        endpoint_text = " ".join(
            str(value.text)
            for curve in region.curves
            for point_value in curve.values()
            if isinstance(point_value, tuple)
            for value in point_value
        )
        self.assertIn("L", endpoint_text)
        self.assertIn("W", endpoint_text)
        self.assertNotIn("92", endpoint_text)
        self.assertNotIn("62", endpoint_text)

    def test_signed_scale_moves_difference_hole_with_recursive_membership(self):
        source = node(
            "difference",
            children=[
                node("square", {"size": [expr(20), expr(10)], "center": expr(True)}),
                node("translate", {"v": point(6, 0)}, [node("circle", {"r": expr(3)})]),
            ],
        )
        region = Region(node("scale", {"v": point(-1, 1)}, [source]))

        self.assertFalse(region.contains(-6, 0))
        self.assertTrue(region.contains(6, 0))
        self.assertEqual(region.bounds, (-10.0, -5.0, 10.0, 5.0))
        self.assertGreaterEqual(len(region.curves), 5)

    def test_three_dimensional_scale_ignores_z_for_local_xy_profile(self):
        region = Region(node("scale", {"v": [expr(-1), expr(1), expr(1)]}, [node("square", {"size": expr(2)})]))

        self.assertTrue(region.contains(-1, 1))
        self.assertFalse(region.contains(1.1, 1))

    def test_difference_of_circles_is_an_annulus(self):
        region = Region(
            node(
                "difference",
                children=[
                    node("circle", {"r": expr(10)}),
                    node("circle", {"r": expr(3)}),
                ],
            )
        )

        self.assertTrue(region.contains(8, 0))
        self.assertFalse(region.contains(0, 0))
        self.assertEqual(region.bounds, (-10.0, -10.0, 10.0, 10.0))
        self.assertEqual([curve["kind"] for curve in region.curves].count("circle"), 2)

    def test_low_fn_cylinder_uses_explicit_polygon(self):
        region = Region(
            node(
                "cylinder",
                {"h": expr(5), "r1": expr(5), "r2": expr(5), "center": expr(False), "fn": expr(8)},
            )
        )

        self.assertEqual(len(region.curves), 8)
        self.assertTrue(all(curve["kind"] == "line" for curve in region.curves))
        self.assertTrue(region.contains(0, 0))

    def test_polygon_and_for_union_are_supported(self):
        triangle = node("polygon", {"points": [point(0, 0), point(4, 0), point(0, 4)]})
        region = Region(node("for", children=[triangle, node("translate", {"v": point(10, 0)}, [triangle])]))

        self.assertTrue(region.contains(1, 1))
        self.assertTrue(region.contains(11, 1))
        self.assertFalse(region.contains(4, 4))

    def test_rotate_and_translate_preserve_numeric_membership(self):
        region = Region(
            node(
                "translate",
                {"v": point(10, 0)},
                [node("rotate", {"a": expr(90)}, [node("square", {"size": expr(2)})])],
            )
        )

        self.assertTrue(region.contains(9, 1))
        self.assertFalse(region.contains(11, -2))

    def test_nonuniform_scale_of_curved_primitive_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "uniform scale"):
            Region(node("scale", {"v": point(2, 1)}, [node("circle", {"r": expr(3)})]))

    def test_invalid_boolean_and_negative_offset_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported planar op"):
            Region(node("sphere", {"r": expr(2)}))
        with self.assertRaisesRegex(ValueError, "negative offset"):
            Region(
                node(
                    "offset",
                    {"r": expr(-1)},
                    [node("square", {"size": expr(4)})],
                )
            )


if __name__ == "__main__":
    unittest.main()
