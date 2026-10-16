import unittest

from scad2fusion.units import infer_dimensions, fusion_expression


class DimensionTests(unittest.TestCase):
    def test_fusion_minmax_use_semicolon_and_binary_nesting(self):
        self.assertEqual(fusion_expression('max(2,3)',{},0),'max(2; 3)')
        self.assertEqual(fusion_expression('min(1,2,3)',{},0),'min(min(1; 2); 3)')

    def test_constant_trigonometric_coordinates_are_contextual_lengths(self):
        self.assertEqual(infer_dimensions({}, [('7*cos(0)',1),('cos(0)',1)]), {})
        self.assertIn('mm',fusion_expression('cos(0)',{},1))

    def test_derived_count_and_length_are_inferred_without_name_conventions(self):
        definitions = {'a': '100', 'b': '10', 'step': '12',
                       'n': 'floor((a - 2 * b) / step) + 1',
                       'start': '(a - (n - 1) * step) / 2'}
        dims = infer_dimensions(definitions, [('a', 1), ('b', 1), ('step', 1), ('start', 1)])
        self.assertEqual(dims, {'a': 1, 'b': 1, 'step': 1, 'n': 0, 'start': 1})
        self.assertEqual(fusion_expression('a - 5', dims, 1), '(a - (5 mm))')
        self.assertEqual(fusion_expression('floor(a / step) + 1', dims, 0), '(floor((a / step)) + 1)')

    def test_inconsistent_dimensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'dimension'):
            infer_dimensions({'a': '10'}, [('a', 1), ('a', 0)])

    def test_unused_branch_parameters_have_dimensionless_metadata(self):
        result = infer_dimensions({'a': '100', 'unused': '17', 'derived': 'unused / 2'}, [('a', 1)])
        self.assertEqual(result, {'a': 1, 'unused': 0, 'derived': 0})

    def test_literal_power_pi_and_boolean_constants(self):
        dims = infer_dimensions({'a': '(2 ^ 3)', 'b': 'PI', 'enabled': 'true'}, [('a', 1), ('b', 1)])
        self.assertEqual(dims, {'a': 1, 'b': 1, 'enabled': 0})
        self.assertIn('^', fusion_expression('2 ^ 3', dims, 1))
        self.assertIn('mm', fusion_expression('PI', dims, 1))
        self.assertEqual(fusion_expression('true', dims, 0), '1')
        self.assertEqual(fusion_expression('pi', dims, 1), fusion_expression('PI', dims, 1))


if __name__ == '__main__':
    unittest.main()
