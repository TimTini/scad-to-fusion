import copy
import math
from pathlib import Path
import unittest

from scad2fusion.helical import recognize_helical_sections
from scad2fusion.frontend import compile_source
from scad2fusion.generator import json_value


def tube(turns=1.5, phase=37, pitch=4.2, sides=24, steps=72):
    points, faces = [], []
    for i in range(steps + 1):
        t = turns * 2 * math.pi * i / steps
        angle = t + math.radians(phase)
        radius = max(.025, .9 * min(1, t / .8, (turns * 2 * math.pi - t) / .8))
        for j in range(sides):
            b = 2 * math.pi * j / sides
            points.append([(23 + radius * math.cos(b)) * math.cos(angle),
                           (23 + radius * math.cos(b)) * math.sin(angle),
                           7 + pitch * t / (2 * math.pi) + radius * math.sin(b)])
    for i in range(steps):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c, d = a + sides, b + sides
            faces.extend([[a, b, d], [a, d, c]])
    faces.extend([list(range(sides - 1, -1, -1)),
                  list(range(steps * sides, (steps + 1) * sides))])
    return points, faces


class HelicalRecognitionTests(unittest.TestCase):
    def test_recovers_pitch_phase_and_every_tapered_section(self):
        points, faces = tube()
        result = recognize_helical_sections(points, faces)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['pitch'], 4.2)
        self.assertAlmostEqual(result['center_radius'], 23)
        self.assertAlmostEqual(result['sections'][0]['angle'], math.radians(37))
        self.assertAlmostEqual(result['sections'][-1]['angle'] - result['sections'][0]['angle'], 3 * math.pi)
        self.assertAlmostEqual(result['sections'][0]['radius'], .025)
        self.assertAlmostEqual(result['sections'][36]['radius'], .9)
        self.assertLess(result['max_vertex_residual'], 1e-8)
        self.assertEqual(len(result['sections']), 73)
        self.assertEqual(result['sections'][0]['vertices'], points[:24])
        self.assertEqual(result['sections'][36]['vertices'], points[36 * 24:37 * 24])

    def test_negative_pitch_and_reversed_face_winding(self):
        points, faces = tube(pitch=-3)
        result = recognize_helical_sections(points, [f[::-1] for f in faces])
        self.assertAlmostEqual(result['pitch'], -3)

    def test_rejects_changed_shape_or_connectivity(self):
        points, faces = tube()
        for coordinate in range(3):
            changed = copy.deepcopy(points)
            changed[31][coordinate] += .01
            self.assertIsNone(recognize_helical_sections(changed, faces))
        self.assertIsNone(recognize_helical_sections(points, faces[:-1]))
        self.assertIsNone(recognize_helical_sections(points, faces + [faces[0]]))
        changed = copy.deepcopy(faces)
        changed[0][0] = 100
        self.assertIsNone(recognize_helical_sections(points, changed))

    def test_rejects_nonuniform_pitch_and_nonfinite_data(self):
        points, faces = tube()
        for p in points[24:48]:
            p[2] += .01
        self.assertIsNone(recognize_helical_sections(points, faces))
        points, faces = tube()
        points[0][0] = float('nan')
        self.assertIsNone(recognize_helical_sections(points, faces))

    def test_translation_does_not_hide_local_shape_error(self):
        points, faces = tube()
        for p in points:
            p[2] += 1e9
        self.assertIsNotNone(recognize_helical_sections(points, faces))
        points[31][2] += .5
        self.assertIsNone(recognize_helical_sections(points, faces))

    def test_invalid_input_types_return_none(self):
        for points, faces in ((None, []), ([None], []), ([[0, 0, 'x']], []),
                              ([[0, 0, 0]], [None])):
            self.assertIsNone(recognize_helical_sections(points, faces))

    def test_inconsistent_winding_is_rejected(self):
        points, faces = tube()
        faces[0].reverse()
        self.assertIsNone(recognize_helical_sections(points, faces))

    def test_rejects_section_vertex_order_twist(self):
        points, faces = tube()
        ring = points[24:48]
        points[24:48] = ring[1:] + ring[:1]
        self.assertTrue(recognize_helical_sections(points, faces) is None)

    def test_real_fixture_uses_geometry_without_module_names(self):
        source = Path(__file__).parent / 'fixtures' / 'electric-toothbrush-case.scad'
        program = json_value(compile_source(source.read_text(encoding='utf-8'), filename='renamed.scad'))
        def walk(node):
            yield node
            for child in node['children']:
                yield from walk(child)
        meshes = [n for n in walk(program['geometry']) if n['op'] == 'polyhedron']
        self.assertEqual(len(meshes), 2)
        for node, count in zip(meshes, (481, 601)):
            result = recognize_helical_sections(node['args']['points'], node['args']['faces'])
            self.assertIsNotNone(result)
            self.assertEqual(len(result['sections']), count)
            self.assertAlmostEqual(result['pitch'], 4.68)
            self.assertAlmostEqual(result['sections'][0]['radius'], .025)
            self.assertLess(result['profile_sagitta'], .008)


if __name__ == '__main__':
    unittest.main()
