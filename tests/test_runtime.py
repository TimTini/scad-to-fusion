from dataclasses import asdict
from pathlib import Path
import unittest

from scad2fusion.frontend import compile_source
from scad2fusion.generator import json_value
from scad2fusion.native_runtime import Frame, pattern_spec, ordered_loop, batch_cylinder_cuts, validate_program


class RuntimePlanningTests(unittest.TestCase):
    def test_layered_section_frame_increases_along_each_source_axis(self):
        from scad2fusion.native_layers import section_frame
        from scad2fusion.planar import Scalar
        for axis in range(3):
            frame=section_frame(Frame(),axis,10)
            start=frame.point([Scalar(0),Scalar(0),Scalar(0)])
            end=frame.point([Scalar(0),Scalar(0),Scalar(2)])
            self.assertEqual(start[axis].value,10)
            self.assertEqual(end[axis].value,12)

    def test_matrix_transform_composes_local_translation_and_basis(self):
        from scad2fusion.planar import Scalar
        frame = Frame(origin=[Scalar(10), Scalar(20), Scalar(30)])
        matrix = [[0,0,1,4],[1,0,0,5],[0,1,0,6],[0,0,0,1]]
        result = frame.transformed({'op':'multmatrix','args':{'m':matrix}})
        self.assertEqual([p.value for p in result.point([Scalar(1),Scalar(2),Scalar(3)])],[17,26,38])
        with self.assertRaisesRegex(ValueError,'affine'):
            frame.transformed({'op':'multmatrix','args':{'m':matrix[:3]+[[0,0,1,1]]}})
        with self.assertRaisesRegex(ValueError,'orthogonal'):
            frame.transformed({'op':'multmatrix','args':{'m':[[1,1,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}})

    def test_solid_intersection_is_validated_as_child_solids(self):
        program = json_value(compile_source('intersection(){cube(2);translate([1,0,0])cube(2);}'))
        self.assertIn('intersection', validate_program(program)['operations'])

    def test_timeline_repetition_counts_alternating_sketch_plane_blocks(self):
        from scad2fusion.native_runtime import timeline_repetition
        self.assertEqual(timeline_repetition(['Sketch','Plane']*8)['repetitions'],8)
        self.assertEqual(timeline_repetition(['Fillet']*6)['repetitions'],6)
        self.assertLessEqual(timeline_repetition(['Sketch','Revolve','Fillet','Sketch','Sweep'])['repetitions'],5)

    def test_native_report_rejects_more_than_five_repetitions(self):
        from types import SimpleNamespace as Obj
        from scad2fusion.native_runtime import native_report
        class Feature:
            pass
        timeline = Obj(count=6, item=lambda i:Obj(entity=Obj(objectType='Sketch')))
        design = Obj(computeAll=lambda:True, timeline=timeline)
        builder = Obj(fusion=Obj(Feature=Feature))
        with self.assertRaisesRegex(RuntimeError,'more than five'):
            native_report(design,builder)

    def test_expanded_loop_count_and_resolution_are_rebuild_inputs(self):
        for source,name in [('n=2;for(i=[0:n])translate([i*3,0,0])cube(1);','n'),
                            ('segments=24;cylinder(h=2,r=3,$fn=segments);','segments')]:
            report = validate_program(json_value(compile_source(source)))
            self.assertIn(name,report['generation_time_transform_parameters'])

    def test_coplanar_cylinder_cuts_share_one_extrusion(self):
        p = compile_source('for(x=[0,7,14])translate([x,0,-0.02])cylinder(h=2.64,r=1.5);')
        plan = batch_cylinder_cuts(json_value(p.geometry.children[0]),Frame())
        self.assertIsNotNone(plan)
        node,frame = plan
        self.assertEqual(node['op'],'linear_extrude')
        self.assertEqual(len(node['children']),3)
        self.assertAlmostEqual(frame.origin[2].value,-.02)
        p = compile_source('for(x=[0,7])translate([x,0,x])cylinder(h=2.64,r=1.5);')
        self.assertIsNone(batch_cylinder_cuts(json_value(p.geometry.children[0]),Frame()))

    def test_actual_tray_pattern_allows_special_fn_metadata(self):
        p = compile_source((Path(__file__).parent / 'fixtures/tray.scad').read_text(encoding='utf-8-sig'))
        loop = json_value(p.geometry.children[0].children[-2])
        self.assertIsNotNone(pattern_spec(loop, Frame()))

    def test_unordered_profile_curves_are_stitched_by_endpoints(self):
        segments = [[(0, 0), (0, 3)], [(3, 3), (0, 0)], [(0, 3), (3, 3)]]
        points = ordered_loop(segments)
        self.assertEqual(points, [(0, 0), (0, 3), (3, 3), (0, 0)])

    def test_one_by_one_grid_retains_symbolic_spacing_and_count(self):
        program = compile_source('n=1;m=1;pitch=12;for(x=[0:n-1],y=[0:m-1]) translate([5+x*pitch,6+y*pitch,0]) cylinder(h=3,r=1);')
        loop = json_value(program.geometry.children[0])
        spec = pattern_spec(loop, Frame())
        self.assertIsNotNone(spec)
        self.assertEqual([a['axis'] for a in spec['axes']], [0, 1])
        self.assertEqual([a['spacing'].value for a in spec['axes']], [12, 12])
        self.assertEqual([a['count'].value for a in spec['axes']], [1, 1])
        self.assertIn('n', spec['axes'][0]['count'].text)
        self.assertIn('pitch', spec['axes'][0]['spacing'].text)

    def test_non_translation_loop_cannot_be_claimed_as_pattern(self):
        p = compile_source('for(x=[0:2]) cylinder(h=x+1,r=1);')
        self.assertIsNone(pattern_spec(json_value(p.geometry.children[0]), Frame()))

    def test_nonlinear_translation_is_not_a_pattern_even_at_one_instance(self):
        p = compile_source('n=1; for(x=[0:n-1]) translate([x*x,0,0]) cylinder(h=3,r=1);')
        self.assertIsNone(pattern_spec(json_value(p.geometry.children[0]), Frame()))


if __name__ == '__main__':
    unittest.main()
