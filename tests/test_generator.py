import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scad2fusion.generator import generate_package, expanded_rebuild_parameters


class GeneratorTests(unittest.TestCase):
    def test_polyhedron_middle_vertex_parameters_are_lengths_and_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'mesh.scad'
            source.write_text('x=10;y=20;polyhedron(points=[[0,0,0],[x,0,0],[0,y,0],[0,0,1]],faces=[[0,1,2],[0,3,1],[0,2,3],[1,3,2]]);')
            report = generate_package(source,Path(directory)/'Mesh')
            for name in ('x','y'):
                self.assertEqual(report['parameters'][name]['unit'],'mm')
                self.assertEqual(report['parameters'][name]['update'],'rebuild')

    def test_rebuild_dependencies_include_upstream_inputs(self):
        parameters = {'width':{'deps':[]},'radius':{'deps':['width']},'crest':{'deps':['radius']}}
        self.assertEqual(expanded_rebuild_parameters(parameters,['crest','part']),['crest','part','radius','width'])

    def test_empty_difference_and_oversized_transform_vectors_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'invalid.scad'
            cases = ['difference() {}', 'translate([1,2,3,4]) cube(1);', 'scale([1,2,3,4]) cube(1);']
            for index, text in enumerate(cases):
                source.write_text(text)
                with self.subTest(text=text), self.assertRaisesRegex(ValueError, r'invalid.scad:1:'):
                    generate_package(source, Path(directory) / ('Invalid' + str(index)))

    def test_io_failure_leaves_no_partial_package(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'simple.scad'
            source.write_text('cube(2);')
            output = Path(directory) / 'Atomic'
            write_text = Path.write_text
            def fail_report(path, *args, **kwargs):
                if path.name == 'conversion-report.json':
                    raise OSError('simulated disk error')
                return write_text(path, *args, **kwargs)
            with patch.object(Path, 'write_text', fail_report):
                with self.assertRaisesRegex(OSError, 'disk error'):
                    generate_package(source, output)
            self.assertFalse(output.exists())

    def test_actual_tray_special_fn_and_dimensions_generate(self):
        with tempfile.TemporaryDirectory() as directory:
            result = generate_package(Path(__file__).parent / 'fixtures/tray.scad', Path(directory) / 'Tray')
            self.assertEqual(result['parameters']['drain_columns']['unit'], '')
            self.assertEqual(result['parameters']['length']['unit'], 'mm')
            self.assertEqual(result['parameters']['drain_columns']['value'], 7)

    def test_two_hooks_and_renamed_source_remain_source_driven(self):
        import re
        with tempfile.TemporaryDirectory() as directory:
            raw = (Path(__file__).parent / 'fixtures/tray.scad').read_text(encoding='utf-8-sig')
            raw = re.sub(r'\blength\b', 'span', raw)
            raw = raw.replace('rounded_rectangle', 'outline')
            source = Path(directory) / 'renamed.scad'
            source.write_text(raw, encoding='utf-8')
            result = generate_package(source, Path(directory) / 'Renamed', {'hook_count': 2, 'span': 150})
            self.assertEqual(result['parameters']['span']['value'], 150)
            self.assertEqual(result['parameters']['drain_columns']['value'], 11)
            self.assertIn('hook_count', result['rebuild_parameters'])
            self.assertNotIn('length', result['parameters'])

    def test_source_generates_standalone_package_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'other.scad'
            source.write_text('w=20; h=3; linear_extrude(h) square([w,10]);', encoding='utf-8')
            output = Path(directory) / 'OtherModel'
            result = generate_package(source, output)
            code = (output / 'OtherModel.py').read_text(encoding='utf-8')
            compile(code, 'OtherModel.py', 'exec')
            namespace = {'__name__': '__main__'}
            exec(compile(code, 'OtherModel.py', 'exec'), namespace)
            self.assertTrue(callable(namespace['run']))
            self.assertNotIn('from scad2fusion', code)
            self.assertEqual(result['validation']['fusion_runtime'], 'not_run')
            manifest = json.loads((output / 'OtherModel.manifest').read_text())
            self.assertEqual(manifest['type'], 'script')
            with self.assertRaises(FileExistsError):
                generate_package(source, output)


if __name__ == '__main__':
    unittest.main()
