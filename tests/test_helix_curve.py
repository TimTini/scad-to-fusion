import math
import unittest

from scad2fusion.helix_curve import helical_curve_data, split_helical_sections


def evaluate(data, span, t):
    points = data['control_points'][span * 3:span * 3 + 4]
    u = 1 - t
    return [u**3 * points[0][axis] + 3*u*u*t * points[1][axis]
            + 3*u*t*t * points[2][axis] + t**3 * points[3][axis]
            for axis in range(3)]


def helix_sections(angles, radius_at, orbit_radius=12, phase=.37,
                   z0=-2, pitch=5):
    return [{'angle': angle,
             'center': [orbit_radius * math.cos(angle + phase),
                        orbit_radius * math.sin(angle + phase),
                        z0 + pitch * (angle - angles[0]) / (2 * math.pi)],
             'radius': radius_at(angle)} for angle in angles]


class HelixCurveTests(unittest.TestCase):
    def assert_curve_matches(self, sections, guide):
        data = helical_curve_data(sections, guide=guide)
        points = data['control_points']
        span_count = (len(points) - 1) // 3
        self.assertEqual(data['degree'], 3)
        self.assertEqual(len(data['knots']), len(points) + data['degree'] + 1)
        self.assertEqual(data['knots'][:4], [0.0] * 4)
        self.assertEqual(data['knots'][-4:], [float(span_count)] * 4)
        for span in range(span_count):
            for sample in range(21):
                t = sample / 20
                angle0 = sections[0]['angle']
                angle1 = sections[-1]['angle']
                parameter_angle = angle0 + (angle1 - angle0) * (span + t) / span_count
                # The helper parameterizes each source interval uniformly by angle.
                angle = parameter_angle
                phase = math.atan2(sections[0]['center'][1], sections[0]['center'][0]) - angle0
                orbit = math.hypot(*sections[0]['center'][:2])
                z_slope = ((sections[-1]['center'][2] - sections[0]['center'][2])
                           / (angle1 - angle0))
                z = sections[0]['center'][2] + (angle - angle0) * z_slope
                radius = sections[-1]['radius']
                for left, right in zip(sections, sections[1:]):
                    if min(left['angle'], right['angle']) <= angle <= max(left['angle'], right['angle']):
                        radius = left['radius'] + (right['radius'] - left['radius']) * (
                            (angle - left['angle']) / (right['angle'] - left['angle']))
                        break
                radial = orbit + radius if guide else orbit
                expected = [radial * math.cos(angle + phase),
                            radial * math.sin(angle + phase), z]
                actual = evaluate(data, span, t)
                self.assertLess(math.dist(actual, expected), .001)

    def test_centerline_and_guide_match_phase_pitch_and_linear_radius_corners(self):
        angles = [-.61, -.51, -.41, -.31, -.21, -.11, -.01, .09, .19]
        radius_at = lambda angle: .08 if angle <= -.21 else .08 + (angle + .21) * .7
        sections = helix_sections(angles, radius_at, orbit_radius=7.5, phase=1.13,
                                  z0=3.2, pitch=-4.7)
        for guide in (False, True):
            with self.subTest(guide=guide):
                self.assert_curve_matches(sections, guide)

    def test_subdivides_long_spans_and_preserves_endpoints(self):
        angles = [.8, 1.2]
        sections = helix_sections(angles, lambda _: .4, phase=-.75, pitch=3)
        data = helical_curve_data(sections)
        span_count = (len(data['control_points']) - 1) // 3
        self.assertGreater(span_count, 1)
        self.assertLessEqual(abs(angles[-1] - angles[0]) / span_count, math.radians(10) + 1e-12)
        first, last = data['control_points'][0], data['control_points'][-1]
        for actual, expected in ((first, sections[0]['center']), (last, sections[-1]['center'])):
            self.assertLess(math.dist(actual, expected), 1e-12)

    def test_reverse_angle_order_and_nonzero_guide_radius(self):
        angles = [.4, .2, 0, -.2]
        sections = helix_sections(angles, lambda _: .23, orbit_radius=4, phase=-.3,
                                  pitch=2.1)
        data = helical_curve_data(sections, guide=True)
        first, last = data['control_points'][0], data['control_points'][-1]
        self.assertAlmostEqual(math.hypot(first[0], first[1]), 4.23)
        self.assertAlmostEqual(math.hypot(last[0], last[1]), 4.23)
        self.assert_curve_matches(sections, True)

    def test_large_radius_gets_extra_spans_to_keep_guide_error_below_tolerance(self):
        angles = [0.0, .5]
        sections = helix_sections(angles, lambda angle: .2 + angle, orbit_radius=3500,
                                  phase=.2, pitch=2)
        data = helical_curve_data(sections, guide=True)
        span_count = (len(data['control_points']) - 1) // 3
        self.assertGreater(span_count, math.ceil(.5 / math.radians(10)))
        for span in range(span_count):
            for sample in range(21):
                t = sample / 20
                angle = angles[0] + .5 * (span + t) / span_count
                radius = .2 + angle
                expected = [(3500 + radius) * math.cos(angle + .2),
                            (3500 + radius) * math.sin(angle + .2),
                            sections[0]['center'][2] + angle * 2 / (2 * math.pi)]
                self.assertLess(math.dist(evaluate(data, span, t), expected), .001)

    def test_splits_up_to_five_piecewise_slope_phases_and_shares_boundaries(self):
        angles = [i * .1 for i in range(9)]
        slopes = [.2, .2, 0, 0, -.3, -.3, .1, .1]
        radii = [.4]
        for slope in slopes:
            radii.append(radii[-1] + slope * .1)
        sections = helix_sections(angles, lambda angle: radii[round(angle / .1)])
        original = [dict(section, center=section['center'][:]) for section in sections]

        regions = split_helical_sections(sections)

        self.assertEqual(len(regions), 4)
        self.assertEqual([len(region) for region in regions], [3, 3, 3, 3])
        self.assertIs(regions[0][-1], regions[1][0])
        self.assertIs(regions[1][-1], regions[2][0])
        self.assertIs(regions[2][-1], regions[3][0])
        self.assertEqual(sections, original)

    def test_rejects_more_than_five_phases_and_duplicate_or_reversing_angles(self):
        angles = [i * .1 for i in range(8)]
        slopes = [.1, .2, .3, .4, .5, .6, .7]
        radii = [.2]
        for slope in slopes:
            radii.append(radii[-1] + slope * .1)
        sections = helix_sections(angles, lambda angle: radii[round(angle / .1)])
        self.assertIsNone(split_helical_sections(sections))

        duplicate = [dict(section) for section in sections]
        duplicate[2]['angle'] = duplicate[1]['angle']
        with self.assertRaises(ValueError):
            split_helical_sections(duplicate)
        reversing = [dict(section) for section in sections]
        reversing[3]['angle'] = reversing[2]['angle'] - .1
        with self.assertRaises(ValueError):
            split_helical_sections(reversing)


if __name__ == '__main__':
    unittest.main()
