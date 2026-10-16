import math
import unittest

from scad2fusion.layered import layered_plan, recognize_layered_sections


def layered_mesh(axis, profiles, planes, *, bad_faces=False):
    """Make a ring-major closed mesh with triangulated side quads."""
    if axis == 0:
        axes = (1, 2)
    elif axis == 1:
        axes = (0, 2)
    else:
        axes = (0, 1)
    points = []
    for plane, profile in zip(planes, profiles):
        for first, second in profile:
            point = [0.0, 0.0, 0.0]
            point[axis] = float(plane)
            point[axes[0]], point[axes[1]] = first, second
            points.append(point)
    sides = len(profiles[0])
    faces = [list(reversed(range(sides)))]
    for layer in range(len(profiles) - 1):
        for side in range(sides):
            nxt = (side + 1) % sides
            a, b = layer * sides + side, layer * sides + nxt
            c, d = a + sides, b + sides
            faces.extend(((a, b, d), (a, d, c)))
    faces.append(list(range((len(profiles) - 1) * sides, len(profiles) * sides)))
    if bad_faces:
        faces.pop()
    return points, faces


def square(scale=1.0):
    return [(-scale, -scale), (scale, -scale), (scale, scale), (-scale, scale)]


def rectangle(scale=1.0):
    return [(-scale, -1.0), (scale, -1.0), (scale, 1.0),
            (0.0, 1.4), (-scale, 1.0)]


class LayeredRecognitionTests(unittest.TestCase):
    def test_distinct_final_profiles_do_not_create_zero_length_tail(self):
        points,faces=layered_mesh(2,[square(),square(1.2),square(1.4)],[0,1,2])
        self.assertIsNone(layered_plan({'points':points,'faces':faces})['tail_extrusion'])

    def test_recovers_renamed_axis_and_ordered_profiles(self):
        points, faces = layered_mesh(1, [square(), square()], [10, 30])

        result = recognize_layered_sections(points, faces, max_sections=9)

        self.assertIsNotNone(result)
        self.assertEqual(result["axis"], "y")
        self.assertEqual(result["axis_index"], 1)
        self.assertEqual(result["profile_axes"], ("x", "z"))
        self.assertEqual(result["mode"], "extrude")
        self.assertEqual(result["sections"][0]["profile"], square())
        self.assertEqual(result["sections"][-1]["plane"], 30.0)

    def test_adaptive_plan_is_bounded_and_reports_profile_error(self):
        profiles = [rectangle(1 + i * i / 100) for i in range(9)]
        points, faces = layered_mesh(2, profiles, range(9))

        result = recognize_layered_sections(points, faces, max_sections=9)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "loft")
        self.assertEqual(len(result["sections"]), 5)
        self.assertGreater(result["max_profile_interpolation_error"], 0.0)
        self.assertIn("does not bound loft surface error", result["error_scope"])

    def test_circular_radius_law_is_distinguished(self):
        profiles = []
        for radius in (1.0, 1.5, 2.0, 3.0, 4.0):
            profiles.append([(radius * math.cos(i * math.pi / 4),
                              radius * math.sin(i * math.pi / 4)) for i in range(8)])
        points, faces = layered_mesh(0, profiles, [0, 1, 2, 3, 4])

        result = recognize_layered_sections(points, faces)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "circular_radius_law")
        self.assertAlmostEqual(result["circle"]["center"][0], 0.0)
        self.assertAlmostEqual(result["circle"]["center"][1], 0.0)
        self.assertEqual(result["circle"]["radii"], [1.0, 1.5, 2.0, 3.0, 4.0])
        self.assertLessEqual(len(result["sections"]), 5)

    def test_constant_suffix_is_reported_as_exact_prismatic_tail(self):
        profiles = [square(1), square(1.2), square(1.4), square(1.4), square(1.4)]
        points, faces = layered_mesh(2, profiles, [0, 1, 2, 3, 4])

        result = recognize_layered_sections(points, faces)

        self.assertIsNotNone(result)
        self.assertEqual(result["tail_extrusion"]["start_index"], 2)
        self.assertEqual(result["tail_extrusion"]["end_index"], 4)
        self.assertEqual(result["tail_extrusion"]["profile"], square(1.4))

    def test_rejects_open_or_invalid_side_connectivity(self):
        points, faces = layered_mesh(2, [square(), square()], [0, 1], bad_faces=True)
        self.assertIsNone(recognize_layered_sections(points, faces))

        points, faces = layered_mesh(2, [square(), square()], [0, 1])
        faces[1] = [0, 2, 5]
        self.assertIsNone(recognize_layered_sections(points, faces))

    def test_layered_plan_exposes_numeric_axis_and_all_rings(self):
        points, faces = layered_mesh(0, [square(), square(1.2)], [5, 15])

        result = layered_plan({"points": points, "faces": faces})

        self.assertEqual(result["axis"], 0)
        self.assertEqual(result["source_sections"], 2)
        self.assertEqual(result["sections"][0]["position"], 5.0)
        self.assertEqual(result["sections"][0]["points"], [[-1.0, -1.0], [1.0, -1.0],
                                                             [1.0, 1.0], [-1.0, 1.0]])
        self.assertEqual(len(result["all_rings"]), 2)

    def test_keeps_structural_ring_with_collapsed_profile_vertices(self):
        collapsed = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (0.0, 0.0)]
        points, faces = layered_mesh(2, [collapsed, square()], [0, 1])

        result = layered_plan({"points": points, "faces": faces})

        self.assertIsNotNone(result)
        self.assertEqual(result["degenerate_profiles"], [0])
        self.assertEqual(result["all_rings"][0]["points"], [list(point) for point in collapsed])


if __name__ == "__main__":
    unittest.main()
