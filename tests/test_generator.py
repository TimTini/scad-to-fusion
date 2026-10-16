import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scad2fusion.generator import generate_package, expanded_rebuild_parameters


class GeneratorTests(unittest.TestCase):
    def test_dustpan_full_source_generates_bounded_analytic_plans(self):
        with tempfile.TemporaryDirectory() as directory:
            report=generate_package(Path(__file__).parent/'fixtures/dustpan.scad',Path(directory)/'Scoop')
            plans=report['capabilities']['representations']
            self.assertEqual(len(plans),7)
            self.assertEqual(sorted(p['native'] for p in plans),sorted(['bounded_layered_loft']+['layered_sector_revolve']*2+['offset_cove_fillet']*2+['translated_profile_sweep']*2))
            self.assertTrue(all(p['sections']<=5 for p in plans))
            self.assertEqual(report['parameters']['hr']['fusion_name'],'scad_hr')
            self.assertTrue(report['capabilities']['frozen_derived_parameters'])

    def test_embedded_planar_recovery_matches_package(self):
        import runpy, math
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'circle.scad'
            source.write_text('linear_extrude(1) polygon([for(i=[0:63]) [5*cos(i*360/64),5*sin(i*360/64)]]);')
            target=Path(directory)/'CircleCase'
            generate_package(source,target)
            ns=runpy.run_path(str(target/'CircleCase.py'))
            polygon=ns['PROGRAM']['geometry']['children'][0]['children'][0]
            region=ns['Region'](polygon)
            self.assertTrue(region.requires_rebuild)
            self.assertEqual([c['kind'] for c in region.curves],['circle'])

    def test_fusion_unit_name_is_escaped_without_changing_source_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'units.scad'
            source.write_text('hr=10;cube([hr,2,1]);')
            report=generate_package(source,Path(directory)/'UnitsCase')
            self.assertEqual(report['parameters']['hr']['fusion_name'],'scad_hr')
    def test_atan2_parameter_is_explicitly_frozen_with_source_formula(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'angle.scad'
            source.write_text('x=10;y=5;a=atan2(y,x);translate([x,y,0])rotate([0,0,a])cube(1);')
            report=generate_package(source,Path(directory)/'Angle')
            angle=report['parameters']['a']
            self.assertEqual(angle['update'],'rebuild')
            self.assertEqual(angle['source_expression'],'atan2(y, x)')
            self.assertNotIn('atan2',angle['expression'])

    def test_matrix_translation_units_and_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'matrix.scad'
            source.write_text('shift=10;factor=2;multmatrix([[factor,0,0,shift],[0,1,0,0],[0,0,1,0],[0,0,0,1]])cube(1);')
            report = generate_package(source,Path(directory)/'MatrixCase')
            self.assertEqual(report['parameters']['shift']['unit'],'mm')
            self.assertEqual(report['parameters']['factor']['unit'],'')
            self.assertEqual(report['parameters']['shift']['update'],'rebuild')

    def test_real_case_selects_native_fillets_and_compact_sweeps(self):
        with tempfile.TemporaryDirectory() as directory:
            report = generate_package(Path(__file__).parent / 'fixtures/electric-toothbrush-case.scad',
                                      Path(directory) / 'SmoothCase')
            representations = report['capabilities']['representations']
            rounds = [r for r in representations if r['native'] == 'revolve_with_fillets']
            helices = [r for r in representations if r['native'] == 'smooth_helical_sweep']
            self.assertEqual([r['fillets'] for r in rounds], [6, 4])
            self.assertEqual(len(helices), 2)
            self.assertEqual(report['parameters']['thread_radius']['update'], 'rebuild')
            code = (Path(directory) / 'SmoothCase' / 'SmoothCase.py').read_text(encoding='utf-8')
            self.assertNotIn('from .', code)
            self.assertIn('def recover_quarter_rounds', code)
            self.assertIn('def create_helical_sweep', code)
            self.assertNotIn('def create_helical_loft', code)

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
