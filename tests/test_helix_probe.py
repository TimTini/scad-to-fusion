import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('prepare_helix_probe',
    Path(__file__).resolve().parents[1] / 'tools' / 'prepare_helix_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class SectionSelectionTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('trimesh'), 'mesh audit extras required')
    def test_prepares_standalone_probe_and_preserves_existing_evidence(self):
        import trimesh
        from test_helical import tube
        points, faces = tube(turns=.5, steps=12, sides=16)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / 'custom.scad', root / 'probe'
            source.write_text('polyhedron(points=' + json.dumps(points) + ',faces=' + json.dumps(faces) + ');')
            cases = probe.prepare(source, output)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0]['source_sections'], 13)
            self.assertEqual(len(cases[0]['sections'][0]['vertices']), 16)
            reference = trimesh.load_mesh(output / 'helix-1-reference.stl')
            self.assertTrue(reference.is_watertight)
            self.assertGreater(reference.volume, 0)
            script = (output / 'probe.py').read_text(encoding='utf-8')
            compile(script, 'probe.py', 'exec')
            self.assertNotIn('from scad2fusion', script)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            with self.assertRaises(FileExistsError):
                probe.prepare(source, output)
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_keeps_taper_corners_and_angular_spacing(self):
        sections = [{'angle': i * .1, 'radius': min(.8, .1 + i * .1, .1 + (30 - i) * .1)}
                    for i in range(31)]
        selected = probe.select_sections(sections, 15)
        self.assertEqual(selected[0], sections[0])
        self.assertEqual(selected[-1], sections[-1])
        self.assertIn(sections[7], selected)
        self.assertIn(sections[23], selected)
        self.assertTrue(all(b['angle'] - a['angle'] <= .2618 for a, b in zip(selected, selected[1:])))
        self.assertLess(len(selected), len(sections))

    def test_negative_angles_keep_source_order(self):
        sections = [{'angle': -i * .1, 'radius': .9} for i in range(21)]
        selected = probe.select_sections(sections, 15)
        self.assertEqual(selected[0], sections[0])
        self.assertEqual(selected[-1], sections[-1])
        self.assertTrue(all(0 < a['angle'] - b['angle'] <= .2618 for a, b in zip(selected, selected[1:])))


if __name__ == '__main__':
    unittest.main()
