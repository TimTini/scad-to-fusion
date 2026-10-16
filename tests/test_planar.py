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
    def test_tangent_path_preserves_bridge_outside_normal_tolerance(self):
        from scad2fusion.planar_recovery import join_tangent_path_curves
        def p(angle):
            return (Scalar(100*math.cos(math.radians(angle))),Scalar(100*math.sin(math.radians(angle))))
        arc={'kind':'arc','center':(Scalar(0),Scalar(0)),'radius':Scalar(100),'start':p(120),'mid':p(110),'end':p(100)}
        q=(Scalar(0.001),Scalar(100))
        curves=[arc,{'kind':'line','start':arc['end'],'end':q},{'kind':'line','start':q,'end':(Scalar(10),Scalar(100))}]
        self.assertEqual(join_tangent_path_curves(curves),curves)

    def test_tangent_path_preserves_opposite_arc_direction(self):
        from scad2fusion.planar_recovery import join_tangent_path_curves
        def p(angle):
            return (Scalar(100*math.cos(math.radians(angle))),Scalar(100*math.sin(math.radians(angle))))
        arc={'kind':'arc','center':(Scalar(0),Scalar(0)),'radius':Scalar(100),'start':p(60),'mid':p(75),'end':p(91)}
        q=(Scalar(2),Scalar(100))
        curves=[arc,{'kind':'line','start':arc['end'],'end':q},{'kind':'line','start':q,'end':(Scalar(10),Scalar(100))}]
        self.assertEqual(join_tangent_path_curves(curves),curves)

    def test_tangent_path_gap_closes_on_shared_circle_tangent(self):
        from scad2fusion.planar_recovery import join_tangent_path_curves
        end=(Scalar(-100*math.sin(math.pi/180)),Scalar(100*math.cos(math.pi/180)))
        arc={'kind':'arc','center':(Scalar(0),Scalar(0)),'radius':Scalar(100),'start':(Scalar(-50),Scalar(100*math.sqrt(.75))),'mid':(Scalar(-25),Scalar(100*math.sqrt(.9375))),'end':end}
        curves=[arc,{'kind':'line','start':end,'end':(Scalar(2),Scalar(100))},{'kind':'line','start':(Scalar(2),Scalar(100)),'end':(Scalar(10),Scalar(100))}]
        result=join_tangent_path_curves(curves)
        self.assertEqual(len(result),2)
        self.assertAlmostEqual(result[0]['end'][0].value,0)
        self.assertAlmostEqual(result[0]['end'][1].value,100)
        self.assertEqual(result[0]['end'],result[1]['start'])
    def test_tangent_sampled_arcs_share_endpoint_without_tiny_line(self):
        points=[point(2*math.cos(i*math.pi/24),2*math.sin(i*math.pi/24)) for i in range(13)]
        points += [point(math.cos(math.pi/2+i*math.pi/24),1+math.sin(math.pi/2+i*math.pi/24)) for i in range(1,13)]
        points += [point(-1,-1),point(2,-1)]
        region=Region(node('polygon',{'points':points}))
        self.assertEqual([c['kind'] for c in region.curves],['arc','arc','line','line','line'])
    def test_uniform_planar_scale_updates_circle_radius(self):
        for factor in (2,-2):
            region=Region(node('scale',{'v':[Scalar(factor),Scalar(factor)]},[node('circle',{'r':Scalar(5)})]))
            self.assertEqual(region.curves[0]['radius'].value,10)

    def test_polygon_recovers_sampled_circular_run_as_arc_and_keeps_line_endpoints(self):
        points = [point(0, 0), point(4, 0)]
        for index in range(13):
            angle = -90 + 7.5 * index
            theta = math.radians(angle)
            points.append(point(4 + 4 * math.cos(theta), 4 + 4 * math.sin(theta)))
        points.extend([point(8, 8), point(0, 8)])

        region = Region(node("polygon", {"points": points}))

        self.assertEqual([curve["kind"] for curve in region.curves], ["line", "arc", "line", "line", "line"])
        self.assertEqual(region.curves[0]["start"][0].value, 0)
        self.assertEqual(region.curves[1]["start"][0].value, 4)
        self.assertEqual(region.curves[1]["end"][0].value, 8)
        self.assertAlmostEqual(region.curves[1]["radius"].value, 4)
        self.assertTrue(region.requires_rebuild)
        for first,second in zip(region.curves,region.curves[1:]+region.curves[:1]):
            self.assertLess(math.dist([v.value for v in first['end']],[v.value for v in second['start']]),1e-8)

    def test_polygon_recovers_full_sampled_circle_as_one_circle(self):
        points = [point(3 + 5 * math.cos(math.radians(angle)), 2 + 5 * math.sin(math.radians(angle)))
                  for angle in range(0, 360, 5)]

        region = Region(node("polygon", {"points": points}))

        self.assertEqual(len(region.curves), 1)
        self.assertEqual(region.curves[0]["kind"], "circle")
        self.assertAlmostEqual(region.curves[0]["center"][0].value, 3)
        self.assertAlmostEqual(region.curves[0]["center"][1].value, 2)
        self.assertAlmostEqual(region.curves[0]["radius"].value, 5)

    def test_polygon_keeps_coarse_circle_samples_as_lines_when_sagitta_is_too_large(self):
        points = [point(0, 0), point(2, 0)]
        for angle in (-90, -60, -30, 0):
            theta = math.radians(angle)
            points.append(point(2 + 2 * math.cos(theta), 2 + 2 * math.sin(theta)))
        points.extend([point(4, 4), point(0, 4)])

        region = Region(node("polygon", {"points": points}))

        self.assertTrue(all(curve["kind"] == "line" for curve in region.curves))

    def test_hull_of_translated_equal_radius_circles_is_exact_capsule(self):
        circle = node("circle", {"r": expr(2)})
        region = Region(node("hull", children=[
            node("translate", {"v": point(0, 0)}, [circle]),
            node("translate", {"v": point(10, 0)}, [circle]),
        ]))

        self.assertEqual([curve["kind"] for curve in region.curves].count("line"), 2)
        self.assertEqual([curve["kind"] for curve in region.curves].count("arc"), 2)
        self.assertTrue(region.requires_rebuild)
        self.assertEqual(region.bounds, (-2.0, -2.0, 12.0, 2.0))
        self.assertTrue(region.contains(5, 1.9))
        self.assertFalse(region.contains(5, 2.1))

    def test_hull_rejects_nonuniform_circle_radii(self):
        with self.assertRaisesRegex(ValueError, "equal-radius circles"):
            Region(node("hull", children=[
                node("translate", {"v": point(0, 0)}, [node("circle", {"r": expr(2)})]),
                node("translate", {"v": point(10, 0)}, [node("circle", {"r": expr(3)})]),
            ]))

    def test_hull_of_three_circles_has_tangent_lines_and_vertex_arcs(self):
        circle = node("circle", {"r": expr(1)})
        region = Region(node("hull", children=[
            node("translate", {"v": point(0, 0)}, [circle]),
            node("translate", {"v": point(10, 0)}, [circle]),
            node("translate", {"v": point(3, 5)}, [circle]),
        ]))

        self.assertEqual([curve["kind"] for curve in region.curves].count("line"), 3)
        self.assertEqual([curve["kind"] for curve in region.curves].count("arc"), 3)
        for current, following in zip(region.curves, region.curves[1:] + region.curves[:1]):
            self.assertEqual(current["end"], following["start"])

    def test_negative_delta_offsets_a_simple_concave_polygon(self):
        polygon = node("polygon", {"points": [
            point(0, 0), point(10, 0), point(10, 10), point(6, 10),
            point(6, 4), point(4, 4), point(4, 10), point(0, 10),
        ]})

        region = Region(node("offset", {"delta": expr(-1)}, [polygon]))

        self.assertEqual(region.bounds, (1.0, 1.0, 9.0, 9.0))
        self.assertTrue(region.requires_rebuild)
        self.assertTrue(region.contains(2, 2))
        self.assertFalse(region.contains(5, 5))

    def test_square_has_four_lines_bounds_and_membership(self):
        region = Region(node("square", {"size": [expr(20), expr(10)], "center": expr(True)}))

        self.assertFalse(region.requires_rebuild)
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

    def test_low_fn_circle_remains_polygon_even_when_sagitta_is_small(self):
        region = Region(node("circle", {"r": expr(0.1), "fn": expr(8)}))

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
