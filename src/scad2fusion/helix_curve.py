"""Build bounded cubic NURBS data for a recognized radial/Z helix."""
import math


_MAX_ANGLE = math.radians(10)
_MAX_ERROR = 0.001


def split_helical_sections(sections):
    """Split sections into contiguous constant-radius-slope regions.

    Neighboring regions share their boundary section. Return ``None`` when
    more than five distinct slope phases are needed.
    """
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        raise ValueError('Expected at least two helical sections')
    angles, radii = [], []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError('Helical sections must be dictionaries')
        angle, radius = section.get('angle'), section.get('radius')
        if (isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle)
                or isinstance(radius, bool) or not isinstance(radius, (int, float))
                or not math.isfinite(radius)):
            raise ValueError('Helical section contains invalid angle or radius')
        angles.append(float(angle))
        radii.append(float(radius))

    direction = angles[1] - angles[0]
    if direction == 0 or any((b - a) * direction <= 0 for a, b in zip(angles, angles[1:])):
        raise ValueError('Helical section angles must be strictly monotonic in source order')

    slopes = [(r1 - r0) / (a1 - a0) for a0, a1, r0, r1 in zip(
        angles, angles[1:], radii, radii[1:])]
    regions, phase_start = [], 0
    for index in range(1, len(slopes)):
        if abs(slopes[index] - slopes[index - 1]) > 1e-7:
            regions.append(list(sections[phase_start:index + 1]))
            phase_start = index
    regions.append(list(sections[phase_start:]))
    return regions if len(regions) <= 5 else None


def helical_curve_data(sections, guide=False):
    """Return a cubic composite-Bezier NURBS approximation in millimeters.

    ``sections`` must be in source order and contain ``angle``, ``center`` and
    ``radius``. Every source section remains a span boundary, preserving the
    piecewise-linear radius law and its taper corners.
    """
    if not isinstance(sections, (list, tuple)) or len(sections) < 2:
        raise ValueError('Expected at least two helical sections')

    values = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError('Helical sections must be dictionaries')
        angle, center, radius = section.get('angle'), section.get('center'), section.get('radius')
        if (isinstance(angle, bool) or not isinstance(angle, (int, float)) or not math.isfinite(angle)
                or isinstance(radius, bool) or not isinstance(radius, (int, float))
                or not math.isfinite(radius) or radius < 0
                or not isinstance(center, (list, tuple)) or len(center) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in center)):
            raise ValueError('Helical section contains invalid numeric data')
        values.append((float(angle), tuple(float(v) for v in center), float(radius)))

    direction = values[1][0] - values[0][0]
    if direction == 0 or any((b[0] - a[0]) * direction <= 0 for a, b in zip(values, values[1:])):
        raise ValueError('Helical section angles must be strictly monotonic in source order')

    first_angle, first_center, _ = values[0]
    orbit_radius = math.hypot(first_center[0], first_center[1])
    if orbit_radius == 0:
        raise ValueError('Helical centerline must have a nonzero radial orbit')
    phase = math.atan2(first_center[1], first_center[0]) - first_angle
    total_angle = values[-1][0] - first_angle
    z_slope = (values[-1][1][2] - first_center[2]) / total_angle
    scale = max(1.0, orbit_radius, abs(first_center[2]), *(abs(v) for _, c, _ in values for v in c))
    tolerance = scale * 1e-9
    for angle, center, _ in values:
        expected = (orbit_radius * math.cos(angle + phase),
                    orbit_radius * math.sin(angle + phase),
                    first_center[2] + (angle - first_angle) * z_slope)
        if (math.hypot(center[0] - expected[0], center[1] - expected[1]) > tolerance
                or abs(center[2] - expected[2]) > tolerance):
            raise ValueError('Sections do not lie on one constant-radius, linear-pitch helix')

    control_points = []
    span_count = 0

    def point_and_derivative(angle, radius, radius_slope):
        radial = (math.cos(angle + phase), math.sin(angle + phase), 0.0)
        tangent = (-math.sin(angle + phase), math.cos(angle + phase), 0.0)
        radial_scale = orbit_radius + (radius if guide else 0.0)
        radial_rate = radius_slope if guide else 0.0
        point = (radial_scale * radial[0], radial_scale * radial[1],
                 first_center[2] + (angle - first_angle) * z_slope)
        derivative = (radial_rate * radial[0] + radial_scale * tangent[0],
                      radial_rate * radial[1] + radial_scale * tangent[1], z_slope)
        return point, derivative

    for left, right in zip(values, values[1:]):
        a0, _, r0 = left
        a1, _, r1 = right
        delta = a1 - a0
        radius_slope = (r1 - r0) / delta
        max_radius = max(r0, r1)
        fourth_derivative_bound = math.hypot(orbit_radius + (max_radius if guide else 0.0),
                                              4 * (abs(radius_slope) if guide else 0.0))
        error_angle = (_MAX_ERROR * 384 / max(fourth_derivative_bound, 1e-300)) ** .25
        max_step = min(_MAX_ANGLE, error_angle)
        divisions = max(1, math.ceil(abs(delta) / max_step))
        for index in range(divisions):
            start_angle = a0 + delta * index / divisions
            end_angle = a0 + delta * (index + 1) / divisions
            start_radius = r0 + (r1 - r0) * index / divisions
            end_radius = r0 + (r1 - r0) * (index + 1) / divisions
            start, start_derivative = point_and_derivative(start_angle, start_radius, radius_slope)
            end, end_derivative = point_and_derivative(end_angle, end_radius, radius_slope)
            width = end_angle - start_angle
            if not control_points:
                control_points.append(list(start))
            control_points.extend([
                [start[k] + width * start_derivative[k] / 3 for k in range(3)],
                [end[k] - width * end_derivative[k] / 3 for k in range(3)],
                list(end),
            ])
            span_count += 1

    knots = [0.0] * 4
    for knot in range(1, span_count):
        knots.extend([float(knot)] * 3)
    knots.extend([float(span_count)] * 4)
    return {'control_points': control_points, 'knots': knots, 'degree': 3}
