import math
import ast
import unittest
from pathlib import Path

from scad2fusion.frontend import compile_source
from scad2fusion.planar import Scalar
from scad2fusion.round_recovery import _evaluate_number, _simplify, recover_quarter_rounds


FIXTURE = Path(__file__).parent / "fixtures" / "electric-toothbrush-case.scad"


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def scalar(value, text):
    return Scalar(value, text)


def fixture_values(program):
    return {name: entry.value for name, entry in program.parameters.items()}


def rounded_corner_polygon(radius=2.0, start_angle=0.0, end_angle=90.0):
    center = (8.0, 8.0)
    points = [
        (scalar(0, "0"), scalar(0, "0")),
        (scalar(10, "10"), scalar(0, "0")),
    ]
    for i in range(9):
        angle = start_angle + (end_angle - start_angle) * i / 8
        radians = math.radians(angle)
        angle_text = format(angle, ".15g")
        points.append((
            scalar(center[0] + radius * math.cos(radians), f"cx + fillet_r * cos({angle_text})"),
            scalar(center[1] + radius * math.sin(radians), f"cy + fillet_r * sin({angle_text})"),
        ))
    points.extend([
        (scalar(0, "0"), scalar(10, "10")),
    ])
    return points


class QuarterRoundRecoveryTests(unittest.TestCase):
    def test_simplifying_negative_addend_keeps_both_radius_terms(self):
        expression = ast.parse("(w - r) + (-r)", mode="eval").body
        simplified = _simplify(expression)

        self.assertEqual(_evaluate_number(simplified, {"w": 10, "r": 2}), 6)

    def test_recovers_source_fixture_body_and_cap_arcs_when_filename_changes(self):
        program = compile_source(FIXTURE.read_text(encoding="utf-8"), filename="renamed-fixture.scad")
        polygons = [node.args["points"] for node in walk(program.geometry) if node.op == "polygon"]
        values = fixture_values(program)

        body, cap = [
            recover_quarter_rounds([
                (Scalar.from_ir({"value": x.value, "text": x.text}),
                 Scalar.from_ir({"value": y.value, "text": y.text}))
                for x, y in points
            ], values)
            for points in polygons
        ]

        self.assertEqual((len(body["fillets"]), len(cap["fillets"])), (6, 4))
        self.assertEqual((len(body["points"]), len(cap["points"])), (8, 6))
        self.assertTrue(all(fillet["source_segments"] == 16 for fillet in body["fillets"] + cap["fillets"]))

    def test_preserves_symbolic_radius_and_tangent_corner_coordinates(self):
        result = recover_quarter_rounds(rounded_corner_polygon(), {"cx": 8, "cy": 8, "fillet_r": 2})

        self.assertEqual(len(result["fillets"]), 1)
        fillet = result["fillets"][0]
        self.assertEqual(fillet["radius"], {"value": 2.0, "text": "abs(fillet_r)"})
        self.assertEqual((fillet["position"][0].value, fillet["position"][1].value), (10, 10))
        self.assertEqual(fillet["source_segments"], 8)
        self.assertAlmostEqual(fillet["sagitta_mm"], 2 * (1 - math.cos(math.pi / 32)))
        sharp = result["points"][2]
        self.assertEqual((sharp[0].value, sharp[1].value), (10, 10))
        self.assertEqual(sharp[0].text, "cx + fillet_r")
        self.assertEqual(sharp[1].text, "cy + fillet_r")

    def test_fixture_fillet_positions_point_to_original_sharp_corners(self):
        program = compile_source(FIXTURE.read_text(encoding="utf-8"), filename="other-name.scad")
        body_points = next(node.args["points"] for node in walk(program.geometry) if node.op == "polygon")
        result = recover_quarter_rounds([
            (Scalar.from_ir({"value": x.value, "text": x.text}),
             Scalar.from_ir({"value": y.value, "text": y.text}))
            for x, y in body_points
        ], fixture_values(program))

        outer_bottom, inside_bottom = result["fillets"][0], result["fillets"][-1]
        self.assertAlmostEqual(outer_bottom["position"][0].value, program.parameters["outer_r"].value)
        self.assertAlmostEqual(outer_bottom["position"][1].value, 0)
        self.assertAlmostEqual(inside_bottom["position"][0].value, program.parameters["body_inner_r"].value)
        self.assertAlmostEqual(inside_bottom["position"][1].value, program.parameters["bottom_thickness"].value)
        self.assertIn(outer_bottom["position"], result["points"])
        self.assertIn(inside_bottom["position"], result["points"])

    def test_fixture_recovered_corners_have_canonical_symbolic_dimensions(self):
        program = compile_source(FIXTURE.read_text(encoding="utf-8"), filename="renamed-again.scad")
        body_points = next(node.args["points"] for node in walk(program.geometry) if node.op == "polygon")
        result = recover_quarter_rounds([
            (Scalar.from_ir({"value": x.value, "text": x.text}),
             Scalar.from_ir({"value": y.value, "text": y.text}))
            for x, y in body_points
        ], fixture_values(program))

        self.assertEqual(result["fillets"][0]["position"][0].text, "outer_r")
        self.assertEqual(result["fillets"][1]["position"][0].text, "outer_r")
        self.assertEqual(result["fillets"][3]["position"][1].text, "body_height")
        self.assertEqual(result["fillets"][4]["position"][1].text, "body_height")

    def test_nonconstant_trig_and_nonlinear_center_terms_remain_symbolic(self):
        points = rounded_corner_polygon()
        for index in range(2, 11):
            x, y = points[index]
            points[index] = (
                Scalar(x.value, x.text.replace("cx", "base + sin(phi)")),
                Scalar(y.value, y.text.replace("cy", "height / scale")),
            )

        result = recover_quarter_rounds(points, {"fillet_r": 2})
        sharp = result["fillets"][0]["position"]

        self.assertIn("sin(phi)", sharp[0].text)
        self.assertIn("height / scale", sharp[1].text)

    def test_negative_named_radius_keeps_source_dependency_and_positive_fillet(self):
        center_x, center_y, radius = 8.0, 8.0, -2.0
        points = [(scalar(0, "0"), scalar(0, "0")), (scalar(6, "6"), scalar(0, "0"))]
        for angle in range(0, 91, 11):
            radians = math.radians(angle)
            points.append((
                scalar(center_x + radius * math.cos(radians), f"cx + negative_r * cos({angle})"),
                scalar(center_y + radius * math.sin(radians), f"cy + negative_r * sin({angle})"),
            ))
        # Include the exact 90 degree endpoint after the eleven-degree samples.
        radians = math.pi / 2
        points.append((
            scalar(center_x + radius * math.cos(radians), "cx + negative_r * cos(90)"),
            scalar(center_y + radius * math.sin(radians), "cy + negative_r * sin(90)"),
        ))
        points.append((scalar(0, "0"), scalar(6, "6")))

        result = recover_quarter_rounds(points, {"cx": center_x, "cy": center_y, "negative_r": radius})
        fillet = result["fillets"][0]

        self.assertEqual(fillet["radius"], {"value": 2.0, "text": "abs(negative_r)"})
        self.assertEqual((fillet["position"][0].value, fillet["position"][1].value), (6, 6))
        self.assertEqual((fillet["position"][0].text, fillet["position"][1].text),
                         ("cx + negative_r", "cy + negative_r"))
        self.assertIsNone(recover_quarter_rounds(points))

    def test_numeric_polygon_is_unchanged(self):
        points = [(Scalar(x), Scalar(y)) for x, y in [(0, 0), (4, 0), (4, 3), (0, 3)]]

        self.assertIsNone(recover_quarter_rounds(points))

    def test_checks_tangent_line_across_polygon_closing_boundary(self):
        points = rounded_corner_polygon()[2:11]
        points.extend([
            (scalar(0, "0"), scalar(10, "10")),
            (scalar(0, "0"), scalar(0, "0")),
            (scalar(10, "10"), scalar(0, "0")),
        ])

        result = recover_quarter_rounds(points, {"cx": 8, "cy": 8, "fillet_r": 2})

        self.assertEqual(len(result["fillets"]), 1)
        self.assertEqual((result["points"][0][0].value, result["points"][0][1].value), (10, 10))

    def test_rejects_non_circle_or_edited_sample(self):
        points = rounded_corner_polygon()
        points[6] = (Scalar(points[6][0].value + 0.08, points[6][0].text), points[6][1])

        self.assertIsNone(recover_quarter_rounds(points, {"cx": 8, "cy": 8, "fillet_r": 2}))

    def test_rejects_mismatched_sine_and_cosine_angles(self):
        points = rounded_corner_polygon()
        point = points[6]
        points[6] = (point[0], Scalar(point[1].value, point[1].text.replace("sin(45)", "sin(46)")))

        self.assertIsNone(recover_quarter_rounds(points, {"cx": 8, "cy": 8, "fillet_r": 2}))

    def test_rejects_arc_sampling_above_sagitta_limit(self):
        points = rounded_corner_polygon()
        # Keep the same semantic quarter circle while reducing it to four segments.
        center_x, center_y, radius = 8.0, 8.0, 2.0
        arc = []
        for angle in (0, 22.5, 45, 67.5, 90):
            theta = math.radians(angle)
            arc.append((
                scalar(center_x + radius * math.cos(theta), f"cx + fillet_r * cos({angle})"),
                scalar(center_y + radius * math.sin(theta), f"cy + fillet_r * sin({angle})"),
            ))
        points = points[:2] + [points[2]] + arc + [points[-1]]

        self.assertIsNone(recover_quarter_rounds(points, {"cx": 8, "cy": 8, "fillet_r": 2}))


if __name__ == "__main__":
    unittest.main()
