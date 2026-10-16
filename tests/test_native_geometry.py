import unittest
from scad2fusion.native_geometry import polyhedron_mesh, revolve_profile_frame, revolve_placement
from scad2fusion.native_runtime import Frame

class SolidGeometryTests(unittest.TestCase):
    def test_revolve_placement_separates_scale_rotation_and_reflection(self):
        frame = Frame().transformed({'op':'rotate','args':{'a':[0,0,90]}})
        scales,axes,sense = revolve_placement(frame)
        self.assertEqual(scales,[1,1,1])
        self.assertEqual(axes,[[0,1,0],[-1,0,0],[0,0,1]])
        self.assertEqual(sense,1)
        scales,axes,sense = revolve_placement(Frame([[-2,0,0],[0,2,0],[0,0,3]]))
        self.assertEqual(scales,[2,2,3])
        self.assertEqual(sense,-1)

    def test_disconnected_shells_are_rejected_before_fusion(self):
        points = [[0,0,0],[1,0,0],[0,1,0],[0,0,1]]
        faces = [[0,1,2],[0,3,1],[0,2,3],[1,3,2]]
        with self.assertRaisesRegex(ValueError,'connected'):
            polyhedron_mesh({'points':points+[[x+3,y,z] for x,y,z in points],
                             'faces':faces+[[i+4 for i in face] for face in faces]},Frame())

    def test_closed_mesh_has_consistent_outward_faces(self):
        points = [[0,0,0],[1,0,0],[0,1,0],[0,0,1]]
        faces = [[0,1,2],[0,3,1],[0,2,3],[1,3,2]]
        result, oriented = polyhedron_mesh({'points': points, 'faces': faces}, Frame())
        self.assertEqual(len(result), 4)
        self.assertEqual(oriented[0], [2,1,0])

    def test_open_mesh_and_invalid_index_rejected(self):
        points = [[0,0,0],[1,0,0],[0,1,0]]
        for faces in ([[0,1,2]], [[0,1,7]]):
            with self.assertRaises(ValueError):
                polyhedron_mesh({'points': points, 'faces': faces}, Frame())

    def test_revolve_profile_is_radial_x_axial_z(self):
        frame = revolve_profile_frame(Frame())
        self.assertEqual([v.value for v in frame.point([2,7,0])], [2,0,7])
        self.assertEqual(frame.matrix, [[1.,0.,0.],[0.,0.,-1.],[0.,1.,0.]])

if __name__ == '__main__': unittest.main()

class SolidValidationTests(unittest.TestCase):
    def test_fixed_revolve_axis_translation_requires_regeneration(self):
        from scad2fusion.native_runtime import validate_program
        p = {'source_name':'case.scad','parameters':{'offset':{}},'geometry':{'op':'translate',
             'args':{'v':[{'value':10,'text':'offset'},0,0]},'children':[{'op':'rotate_extrude','args':{},'children':[
             {'op':'polygon','args':{'points':[[0,0],[2,0],[2,5],[0,5]]},'children':[]}]}]}}
        self.assertIn('offset',validate_program(p)['generation_time_transform_parameters'])

    def test_full_revolve_angle_crossing_requires_regeneration(self):
        from scad2fusion.native_runtime import validate_program
        p = {'source_name':'phase.scad','geometry':{'op':'rotate_extrude','args':{
             'angle':{'value':360,'text':'turn','deps':['turn']}},'children':[
             {'op':'polygon','args':{'points':[[0,0],[2,0],[2,5],[0,5]]},'children':[]}]}}
        self.assertIn('turn',validate_program(p)['generation_time_transform_parameters'])

    def test_new_solid_cutter_uses_combine_instead_of_extrusion(self):
        from unittest.mock import Mock
        from scad2fusion.native_runtime import NativeBuilder
        for operation in ('rotate_extrude','polyhedron'):
            builder = object.__new__(NativeBuilder)
            builder.build = Mock(return_value=['tool'])
            builder.collection = lambda x:x
            builder.comp = Mock()
            builder.fusion = Mock()
            builder.comp.features.combineFeatures.add.return_value.bodies = ['result']
            builder.extrude = Mock(side_effect=AssertionError('extrude fallback'))
            node = {'op':operation,'args':{},'children':[]}
            targets = ['target']
            builder.cut(node,Frame(),targets)
            self.assertEqual(targets,['result'])
            builder.build.assert_called_once()

    def test_rotated_profile_and_polyhedron_capabilities(self):
        from scad2fusion.native_runtime import validate_program
        program = {'source_name':'solid.scad', 'geometry':{'op':'rotate_extrude','args':{'angle':360},'children':[
            {'op':'polygon','args':{'points':[[0,0],[4,0],[4,8],[0,8]]},'children':[]} ]}}
        report = validate_program(program)
        self.assertIn('rotate_extrude', report['operations'])
        self.assertTrue(any('revolve' in v for v in report['approximations']))
