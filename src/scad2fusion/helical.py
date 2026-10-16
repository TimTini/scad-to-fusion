"""Conservative, offline recognition of radial/Z circular helical sections.

Coordinates are in the source frame: the supported helix axis is Z through the
origin. Each section and every strip triangle must match, including the source
end taper, before native reconstruction is attempted.
"""
import math
from .helix_curve import helical_curve_data, split_helical_sections


def select_sections(sections, max_angle=15):
    """Keep endpoints, radius-law corners and bounded angular spacing."""
    indices = {0, len(sections) - 1}
    for i in range(1, len(sections) - 1):
        left = (sections[i]['radius'] - sections[i - 1]['radius']) / (sections[i]['angle'] - sections[i - 1]['angle'])
        right = (sections[i + 1]['radius'] - sections[i]['radius']) / (sections[i + 1]['angle'] - sections[i]['angle'])
        if abs(left - right) > 1e-7:
            indices.add(i)
    step = abs(sections[1]['angle'] - sections[0]['angle'])
    stride = max(1, int(math.radians(max_angle) / step + 1e-9))
    for start, end in zip(sorted(indices), sorted(indices)[1:]):
        indices.update(range(start, end, stride))
    return [sections[i] for i in sorted(indices)]


def create_helical_sweep(core, fusion, comp, sections):
    """At most five analytic radius-law Sweeps sharing one centerline/rail sketch."""
    regions = split_helical_sections(sections)
    if regions is None:
        raise ValueError('Helix requires more than five radius-law regions')
    paths = comp.sketches.add(comp.xYConstructionPlane)
    paths.name = 'SCAD helix paths (regenerate from SCAD)'
    paths.is3D = True
    region_curves = []
    for region in regions:
        curves = []
        varying = abs(region[-1]['radius'] - region[0]['radius']) > 1e-9
        for guide in ((False, True) if varying else (False,)):
            data = helical_curve_data(region, guide=guide)
            curve = core.NurbsCurve3D.createNonRational(
                [core.Point3D.create(*(v / 10 for v in p)) for p in data['control_points']],
                data['degree'], data['knots'], False)
            if curve is None:
                raise RuntimeError('Could not define helical NURBS path')
            curves.append(paths.sketchCurves.sketchFixedSplines.addByNurbsCurve(curve))
        region_curves.append(curves)
    bodies = []
    for region, curves in zip(regions, region_curves):
        path = comp.features.createPath(curves[0], False)
        section = region[0]
        inp = comp.constructionPlanes.createInput()
        if not inp.setByPath(path, fusion.PathDistanceTypes.ProportionalPathDistanceType,
                             core.ValueInput.createByReal(0)):
            raise RuntimeError('Could not define helical profile plane')
        plane = comp.constructionPlanes.add(inp)
        sketch = comp.sketches.add(plane)
        sketch.name = 'SCAD radius-law profile (regenerate from SCAD)'
        center = sketch.modelToSketchSpace(core.Point3D.create(*(v / 10 for v in section['center'])))
        if abs(center.z) > 1e-6:
            raise RuntimeError('Helical section center is outside its normal plane')
        circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center, section['radius'] / 10)
        circle.isFixed = True
        if sketch.profiles.count != 1 or not sketch.isFullyConstrained or not paths.isFullyConstrained:
            raise RuntimeError('Expected fully constrained helical path and profile')
        inp = comp.features.sweepFeatures.createInput(sketch.profiles.item(0), path,
                                                     fusion.FeatureOperations.NewBodyFeatureOperation)
        if len(curves) == 2:
            inp.guideRail = comp.features.createPath(curves[1], False)
            inp.profileScaling = fusion.SweepProfileScalingOptions.SweepProfileScaleOption
        feature = comp.features.sweepFeatures.add(inp)
        feature.name = 'SCAD helical radius-law Sweep (regenerate from SCAD)'
        if feature.healthState != fusion.FeatureHealthStates.HealthyFeatureHealthState:
            raise RuntimeError('Helical Sweep failed: ' + feature.errorOrWarningMessage)
        if feature.bodies.count != 1 or not feature.bodies.item(0).isSolid:
            raise RuntimeError('Expected one solid helical Sweep')
        bodies.append(feature.bodies.item(0))
        sketch.isLightBulbOn = plane.isLightBulbOn = False
    paths.isLightBulbOn = False
    if len(bodies) > 1:
        tools = core.ObjectCollection.create()
        for body in bodies[1:]:
            tools.add(body)
        inp = comp.features.combineFeatures.createInput(bodies[0], tools)
        inp.operation = fusion.FeatureOperations.JoinFeatureOperation
        feature = comp.features.combineFeatures.add(inp)
        feature.name = 'SCAD continuous rounded thread'
        if feature.bodies.count != 1 or not feature.bodies.item(0).isSolid:
            raise RuntimeError('Helical Sweep regions did not join into one solid')
    return feature


def recognize_helical_sections(points, faces):
    """Return measured sections, or None when this ordered mesh is not supported.

    Input is numeric mesh data, not symbolic IR. Section error is numerical fitting
    residual; profile sagitta only bounds polygon-to-circle error within a section.
    Neither quantity bounds a Fusion loft's surface error.
    """
    if not isinstance(points, (list, tuple)) or not points or any(
            not isinstance(p, (list, tuple)) or len(p) != 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in p) for p in points):
        return None
    if not isinstance(faces, (list, tuple)) or any(
            not isinstance(f, (list, tuple)) or len(f) < 3 or any(isinstance(v, bool) or not isinstance(v, int) or
                           not 0 <= v < len(points) for v in f) for f in faces):
        return None
    edges = {}
    for face in faces:
        if len(set(face)) != len(face):
            return None
        for a, b in zip(face, face[1:] + face[:1]):
            edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
    if any(len(pair) != 2 or pair[0] != pair[1][::-1] for pair in edges.values()):
        return None
    caps = [f for f in faces if len(f) != 3]
    if len(caps) != 2 or len(caps[0]) < 13 or len(caps[0]) != len(caps[1]):
        return None
    sides = len(caps[0])
    if len(points) % sides or len(points) // sides < 3:
        return None
    count = len(points) // sides
    end_sets = {frozenset(range(sides)), frozenset(range((count - 1) * sides, count * sides))}
    if {frozenset(f) for f in caps} != end_sets:
        return None
    # Verify both cap boundaries and every triangulated cell, allowing either diagonal.
    for cap in caps:
        if len(set(cap)) != sides or any((b - a) % sides not in (1, sides - 1)
                                        for a, b in zip(cap, cap[1:] + cap[:1])):
            return None
    triangles = {tuple(sorted(f)) for f in faces if len(f) == 3}
    if len(triangles) != len(faces) - 2:
        return None
    for i in range(count - 1):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c, d = a + sides, b + sides
            options = (((a, b, d), (a, c, d)), ((a, b, c), (b, c, d)))
            for option in options:
                pair = {tuple(sorted(f)) for f in option}
                if pair <= triangles:
                    triangles.difference_update(pair)
                    break
            else:
                return None
    if triangles:
        return None
    extent = max(max(p[k] for p in points) - min(p[k] for p in points) for k in range(3))
    tolerance = max(1e-7, extent * 1e-9, max(math.ulp(v) for p in points for v in p) * 8)
    sections, residual = [], 0.
    center_radius = None
    profile_phase, profile_sense = None, None
    for i in range(count):
        ring = points[i * sides:(i + 1) * sides]
        center = [math.fsum(p[k] for p in ring) / sides for k in range(3)]
        radial = math.hypot(*center[:2])
        radius = math.dist(ring[0], center)
        if radial <= radius + tolerance or radius <= tolerance:
            return None
        if center_radius is None:
            center_radius = radial
        if abs(radial - center_radius) > tolerance:
            return None
        angle = math.atan2(center[1], center[0])
        if sections:
            angle = sections[-1]['angle'] + math.remainder(angle - sections[-1]['angle'], 2 * math.pi)
        x, y = center[0] / radial, center[1] / radial
        start = math.atan2(ring[0][2] - center[2], (ring[0][0] - center[0]) * x + (ring[0][1] - center[1]) * y)
        # Determine the ring traversal direction independently of face winding.
        second = math.atan2(ring[1][2] - center[2], (ring[1][0] - center[0]) * x + (ring[1][1] - center[1]) * y)
        sense = 1 if math.remainder(second - start, 2 * math.pi) > 0 else -1
        if profile_phase is None:
            profile_phase, profile_sense = start, sense
        if sense != profile_sense or abs(math.remainder(start - profile_phase, 2 * math.pi)) * radius > tolerance:
            return None
        for j, point in enumerate(ring):
            beta = start + sense * 2 * math.pi * j / sides
            expected = [center[0] + radius * math.cos(beta) * x,
                        center[1] + radius * math.cos(beta) * y,
                        center[2] + radius * math.sin(beta)]
            error = math.dist(point, expected)
            if error > tolerance:
                return None
            residual = max(residual, error)
        sections.append({'angle': angle, 'center': center, 'radius': radius, 'vertices': ring})
    delta = sections[1]['angle'] - sections[0]['angle']
    if abs(delta) < 1e-8 or abs(delta) >= math.pi / 2:
        return None
    if any(abs(s['angle'] - sections[0]['angle'] - i * delta) * center_radius > tolerance
           for i, s in enumerate(sections)):
        return None
    pitch = (sections[-1]['center'][2] - sections[0]['center'][2]) * 2 * math.pi / (sections[-1]['angle'] - sections[0]['angle'])
    if abs(pitch) < tolerance:
        return None
    for i, section in enumerate(sections):
        expected_z = sections[0]['center'][2] + pitch * (section['angle'] - sections[0]['angle']) / (2 * math.pi)
        if abs(section['center'][2] - expected_z) > tolerance:
            return None
    return {'axis': 'source_z', 'center_radius': center_radius, 'pitch': pitch,
            'profile_sides': sides, 'sections': sections, 'max_vertex_residual': residual,
            'profile_sagitta': max(s['radius'] for s in sections) * (1 - math.cos(math.pi / sides))}
