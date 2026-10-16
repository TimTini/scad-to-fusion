"""Native Fusion construction. Also embedded verbatim into generated scripts."""
from __future__ import annotations

import json
import math
from pathlib import Path
import traceback
import ast

from .planar import Scalar, Region
from .units import fusion_expression, expression_ast
from .native_geometry import revolve_profile_frame, revolve_placement, polyhedron_mesh, create_polyhedron_body, revolve_corner_edge, helical_plan, revolve_round_plan
from .helical import create_helical_loft


def _s(value):
    return Scalar.from_ir(value)


def _group(children):
    return {'op': 'union', 'args': {}, 'children': children, 'line': 1}


def ordered_loop(segments):
    """ProfileCurves enumeration is unordered; connect their actual endpoints."""
    if not segments: raise ValueError('Empty profile boundary')
    remaining = [list(part) for part in segments]
    points = remaining.pop(0)
    while remaining:
        candidates = [(math.dist(points[-1], part[index]), i, index == -1)
                      for i, part in enumerate(remaining) for index in (0, -1)]
        distance, index, reverse = min(candidates)
        if distance > 1e-6: raise ValueError('Profile boundary curves do not form a connected loop')
        part = remaining.pop(index)
        if reverse: part.reverse()
        points.extend(part[1:])
    if math.dist(points[0], points[-1]) > 1e-6: raise ValueError('Profile boundary is open')
    return points


class Frame:
    def __init__(self, matrix=None, origin=None):
        self.matrix = matrix or [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
        self.origin = origin or [Scalar(0), Scalar(0), Scalar(0)]

    def point(self, coordinates):
        return [self.origin[i] + sum((coordinates[j] * self.matrix[i][j] for j in range(3)), Scalar(0))
                for i in range(3)]

    def transformed(self, node):
        op, args = node['op'], node['args']
        if op == 'translate':
            if not isinstance(args['v'], list) or len(args['v']) not in (2, 3):
                raise ValueError('Translate vector must have two or three coordinates')
            values = [_s(v) for v in args['v']]
            values += [Scalar(0)] * (3 - len(values))
            return Frame(self.matrix, self.point(values))
        if op == 'scale':
            values = args['v'] if isinstance(args['v'], list) else [args['v']] * 3
            if len(values) not in (2, 3): raise ValueError('Scale vector must have two or three coordinates')
            values = [_s(v).value for v in values]
            values += [1.] * (3 - len(values))
            if any(abs(v) < 1e-12 for v in values):
                raise ValueError('Zero scale is outside supported solid geometry')
            local = [[values[i] if i == j else 0. for j in range(3)] for i in range(3)]
        else:
            if args.get('v') is not None:
                raise ValueError('Axis-angle rotation is not supported yet')
            a = args['a'] if isinstance(args['a'], list) else [0, 0, args['a']]
            x, y, z = [math.radians(_s(v).value) for v in a]
            cx, cy, cz, sx, sy, sz = math.cos(x), math.cos(y), math.cos(z), math.sin(x), math.sin(y), math.sin(z)
            local = [[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx],
                     [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx], [-sy, cy*sx, cy*cx]]
            local = [[0. if abs(v) < 1e-12 else v for v in row] for row in local]
        matrix = [[sum(self.matrix[i][k] * local[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        return Frame(matrix, self.origin)


def _extrusion(node):
    args = node['args']
    if node['op'] == 'linear_extrude':
        if _s(args.get('twist', 0)).value != 0 or _s(args.get('scale', 1)).value != 1:
            raise ValueError('Twisted/scaled linear_extrude is outside this backend')
        return Region(_group(node['children'])), _s(args['height']), bool(_s(args.get('center', False)).value)
    if node['op'] == 'cube':
        size = args['size'] if isinstance(args['size'], list) else [args['size']] * 3
        return Region({'op': 'square', 'args': {'size': size[:2], 'center': args.get('center', False)}, 'children': []}), _s(size[2]), bool(_s(args.get('center', False)).value)
    if node['op'] == 'cylinder':
        if _s(args['r1']).text != _s(args['r2']).text:
            raise ValueError('Conical cylinders are outside this backend')
        region = Region({'op': 'circle', 'args': {'r': args['r1'], 'fn': args.get('fn', 64)}, 'children': []})
        return region, _s(args['h']), bool(_s(args.get('center', False)).value)
    raise ValueError('Unsupported solid operation ' + node['op'])


def pattern_spec(node, frame):
    """Recognize one translated extrusion per Cartesian range iteration."""
    bindings = node['args']['bindings']
    probes = node['args'].get('probes', [])
    if not node['args'].get('pattern_safe') or not node['args'].get('template'): return None
    loop_names = {'__loop_' + b['name'] for b in bindings}

    def degree(expr):
        if isinstance(expr, ast.Constant): return 0
        if isinstance(expr, ast.Name): return 1 if expr.id in loop_names else 0
        if isinstance(expr, ast.UnaryOp): return degree(expr.operand)
        if isinstance(expr, ast.BinOp):
            a, b = degree(expr.left), degree(expr.right)
            if isinstance(expr.op, (ast.Add, ast.Sub)): return max(a, b)
            if isinstance(expr.op, ast.Mult): return a + b
            if isinstance(expr.op, ast.Div): return a if b == 0 else 2
        if not any(isinstance(n, ast.Name) and n.id in loop_names for n in ast.walk(expr)): return 0
        return 2

    def check_template(item):
        def scalar_parts(value):
            if isinstance(value, dict) and 'text' in value: yield value['text']
            elif isinstance(value, list):
                for part in value: yield from scalar_parts(part)
        allowed = 1 if item['op'] == 'translate' else 0
        for text in scalar_parts(list(item['args'].values())):
            if not any(name in text for name in loop_names): continue
            if degree(expression_ast(text)) > allowed: return False
        return all(check_template(child) for child in item['children'])
    if not check_template(node['args']['template']): return None
    if not node['children'] or not 1 <= len(bindings) <= 2 or len(probes) != len(bindings):
        return None
    if any(b['start'] is None or b['step'] is None or b['end'] is None for b in bindings):
        return None

    def leaf(item, current):
        if item['op'] in ('translate', 'rotate', 'scale') and len(item['children']) == 1:
            return leaf(item['children'][0], current.transformed(item))
        if item['op'] == 'union' and len(item['children']) == 1:
            return leaf(item['children'][0], current)
        if item['op'] not in ('linear_extrude', 'cube', 'cylinder'): return None
        return item, current

    seed = leaf(node['children'][0], frame)
    if seed is None: return None
    axes = []
    for binding, probe in zip(bindings, probes):
        other = leaf(probe, frame)
        if other is None or other[0] != seed[0] or other[1].matrix != seed[1].matrix: return None
        vector = [other[1].origin[i] - seed[1].origin[i] for i in range(3)]
        nonzero = [i for i, v in enumerate(vector) if abs(v.value) > 1e-8]
        if len(nonzero) != 1: return None
        axis = nonzero[0]
        start, step, end = [_s(binding[key]) for key in ('start', 'step', 'end')]
        count = (end-start)/step + 1
        if abs(count.value - len(binding['values'])) > 1e-7: return None
        axes.append({'axis': axis, 'spacing': vector[axis], 'count': count})
    if len({a['axis'] for a in axes}) != len(axes): return None
    return {'seed': seed[0], 'frame': seed[1], 'axes': axes}


def batch_cylinder_cuts(node, frame):
    """Group parallel holes of one depth, avoiding one boolean per expanded hole."""
    if node['op'] not in ('for','union') or len(node['children']) < 2: return None
    profiles, common = [], None
    for child in node['children']:
        while child['op'] == 'union' and len(child['children']) == 1: child = child['children'][0]
        if child['op'] != 'translate' or len(child['children']) != 1: return None
        vector = child['args']['v']
        if len(vector) not in (2,3): return None
        cylinder = child['children'][0]
        if cylinder['op'] != 'cylinder': return None
        args = cylinder['args']
        if _s(args['r1']).text != _s(args['r2']).text: return None
        z = vector[2] if len(vector) == 3 else 0
        key = (_s(z).text,_s(args['h']).text,bool(_s(args.get('center',False)).value))
        if common is not None and key != common: return None
        common = key
        circle = {'op':'circle','args':{'r':args['r1'],'fn':args.get('fn',64)},'children':[]}
        profiles.append({'op':'translate','args':{'v':vector[:2]},'children':[circle]})
    extrusion = {'op':'linear_extrude','args':{'height':args['h'],'center':args.get('center',False)},
                 'children':profiles,'line':node.get('line',1)}
    return extrusion,frame.transformed({'op':'translate','args':{'v':[0,0,z]}})


def validate_program(program):
    operations, rebuild, approximations = set(), set(), set()
    loops, representations = [], []

    def deps(value):
        if isinstance(value, dict):
            if 'text' in value:
                rebuild.update(value.get('deps', []))
            else:
                for item in value.values(): deps(item)
        elif isinstance(value, list):
            for item in value: deps(item)

    def walk(node, frame, cutter=False):
        op = node['op']
        operations.add(op)
        try:
            if op in ('translate', 'rotate', 'scale'):
                if op != 'translate': deps(node['args'])
                frame = frame.transformed(node)
                for child in node['children']: walk(child, frame, cutter)
            elif op in ('union', 'difference', 'for'):
                if op == 'difference' and not node['children']:
                    raise ValueError('Empty solid difference is outside supported output; supply a target')
                if op == 'for':
                    spec = pattern_spec(node, frame) if cutter else None
                    if spec is None: deps(node['args']['bindings'])
                    loops.append({'line': node.get('line', 1), 'instances_at_generation': len(node['children']),
                                  'update': 'recompute_pattern' if spec else 'rebuild_count',
                                  'bindings': [b['name'] for b in node['args']['bindings']]})
                for index, child in enumerate(node['children']):
                    walk(child, frame, cutter or (op == 'difference' and index > 0))
            elif op == 'polyhedron':
                polyhedron_mesh(node['args'], frame)
                plan = helical_plan(node['args'], frame)
                representations.append({'line':node.get('line',1), 'source':'polyhedron',
                    'native':'smooth_helical_loft' if plan else 'faceted_base_feature',
                    'source_faces':len(node['args']['faces']),
                    'sections':len(plan['sections']) if plan else 0})
                deps(node['args'].get('points', []))
                rebuild.update(node['args'].get('rebuild_dependencies', []))
                rebuild.update(n.id for value in frame.origin for n in ast.walk(expression_ast(value.text))
                               if isinstance(n,ast.Name) and n.id in program.get('parameters',{}))
                if plan:
                    approximations.add('Recognized helix uses circular radial/Z Loft sections with source pitch/phase/taper; polygon-to-circle and Loft approximation require mesh comparison; geometry changes require regeneration')
                else:
                    approximations.add('Polyhedron uses original planar faces as a fixed native BRep base feature; regenerate to change its geometry')
            elif op == 'rotate_extrude':
                deps(node['args'].get('angle',360))
                resolution_dependencies(node)
                # Axis datum points are fixed at Run; translating it needs a rebuild.
                rebuild.update(n.id for value in frame.origin for n in ast.walk(expression_ast(value.text))
                               if isinstance(n,ast.Name) and n.id in program.get('parameters',{}))
                region = Region(_group(node['children']))
                angle = _s(node['args'].get('angle', 360))
                if not 0 < angle.value <= 360: raise ValueError('rotate_extrude angle must be in (0, 360]')
                if region.bounds[0] < -1e-9: raise ValueError('rotate_extrude profile must lie at nonnegative radius')
                revolve_placement(frame)
                rounded = revolve_round_plan(node, frame, program.get('parameters'))
                representations.append({'line':node.get('line',1), 'source':'rotate_extrude',
                    'native':'revolve_with_fillets' if rounded else 'revolve',
                    'fillets':len(rounded['fillets']) if rounded else 0})
                if rounded:
                    approximations.add('Explicit circular quarter-round samples become source-linked native Fillet features on a sharp Revolve profile')
                approximations.add('Native revolve replaces angular OpenSCAD facets; sampled polygon profile is retained')
            else:
                resolution_dependencies(node)
                region, height, _ = _extrusion(node)
                if height.value <= 0: raise ValueError('Extrusion height must be positive')
                normal = [frame.matrix[i][2] for i in range(3)]
                if sum(abs(v) > 1e-9 for v in normal) != 1:
                    raise ValueError('Extrusion plane must be parallel to XY/XZ/YZ in this version')
                if any(curve['kind'] in ('circle', 'arc') for curve in region.curves):
                    x = math.sqrt(sum(frame.matrix[i][0]**2 for i in range(3)))
                    y = math.sqrt(sum(frame.matrix[i][1]**2 for i in range(3)))
                    if abs(x-y) > 1e-9: raise ValueError('Non-uniform solid scale of curves requires ellipses')
                    approximations.add('Analytic native circles/arcs replace high-fn OpenSCAD facets; low fn<=12 stays polygonal')
        except (ValueError, KeyError) as error:
            if str(error).startswith(program['source_name'] + ':'): raise
            raise ValueError(program['source_name'] + ':' + str(node.get('line', 1)) + ': ' + str(error)) from error
    def resolution_dependencies(node):
        if 'fn' in node['args']: deps(node['args']['fn'])
        for child in node['children']: resolution_dependencies(child)

    walk(program['geometry'], Frame())
    return {'operations': sorted(operations), 'generation_time_transform_parameters': sorted(rebuild),
            'structure_update': 'SCAD conditions and non-pattern loops require regeneration',
            'approximations': sorted(approximations), 'plane_support': 'XY/XZ/YZ parallel extrusions',
            'loops': loops, 'representations':representations,
            'coordinate_branches': 'Coordinates keep their generation-time sign; crossing zero or changing a symbolic zero requires rebuilding',
            'assertions': 'Checked during conversion; keep SCAD input domain when editing Fusion parameters'}


class NativeBuilder:
    def __init__(self, design, program):
        import adsk.core as core
        import adsk.fusion as fusion
        self.core, self.fusion = core, fusion
        self.design, self.comp, self.program = design, design.rootComponent, program
        self.count = 0
        self.patterns = []
        self.stage = 'parameters'
        for name in program['parameter_order']:
            unit = 'mm' if program['dimensions'][name] else ''
            design.userParameters.add(name, core.ValueInput.createByString(program['parameter_expressions'][name]), unit,
                                      'SCAD input/derived expression; keep formula dependencies')

    def expression(self, value, dimension=1):
        return fusion_expression(_s(value).text, self.program['dimensions'], dimension)

    def collection(self, items):
        result = self.core.ObjectCollection.create()
        for item in items: result.add(item)
        return result

    def sketch_region(self, region, frame):
        core, comp = self.core, self.comp
        axis = next(i for i in range(3) if abs(frame.matrix[i][2]) > 1e-9)
        base = [comp.yZConstructionPlane, comp.xZConstructionPlane, comp.xYConstructionPlane][axis]
        normal = base.geometry.normal
        normal_values = [normal.x, normal.y, normal.z]
        distance = frame.origin[axis] * normal_values[axis]
        plane = base
        if abs(distance.value) > 1e-10 or distance.text != '0':
            inp = comp.constructionPlanes.createInput()
            inp.setByOffset(base, core.ValueInput.createByString(self.expression(distance)))
            plane = comp.constructionPlanes.add(inp)
            plane.isLightBulbOn = False
        sketch = comp.sketches.add(plane)
        self.count += 1
        sketch.name = 'SCAD profile ' + str(self.count)
        self.stage = sketch.name
        origin = sketch.sketchToModelSpace(core.Point3D.create(0, 0, 0))
        px = sketch.sketchToModelSpace(core.Point3D.create(1, 0, 0))
        py = sketch.sketchToModelSpace(core.Point3D.create(0, 1, 0))
        basis = [[px.x-origin.x, px.y-origin.y, px.z-origin.z],
                 [py.x-origin.x, py.y-origin.y, py.z-origin.z]]
        plane_origin = [Scalar(0), Scalar(0), Scalar(0)]
        plane_origin[axis] = frame.origin[axis]

        def mapped(point):
            world = frame.point([point[0], point[1], Scalar(0)])
            return [sum(((world[i]-plane_origin[i])*b[i] for i in range(3)), Scalar(0)) for b in basis]

        point_cache = {}
        dimensions = []

        def vertex(point):
            x, y = mapped(point)
            key = (x.text, y.text)
            if key not in point_cache:
                if abs(x.value) < 1e-10 and abs(y.value) < 1e-10 and x.text == '0' and y.text == '0':
                    point_cache[key] = sketch.originPoint
                else:
                    p = sketch.sketchPoints.add(core.Point3D.create(x.value/10, y.value/10, 0))
                    point_cache[key] = p
                    dimensions.append((p, x, y))
            return point_cache[key]

        radius_scale = math.sqrt(sum(frame.matrix[i][0]**2 for i in range(3)))
        radial = []
        for curve in region.curves:
            kind = curve['kind']
            if kind == 'line':
                sketch.sketchCurves.sketchLines.addByTwoPoints(vertex(curve['start']), vertex(curve['end']))
            elif kind == 'arc':
                mid = mapped(curve['mid'])
                arc = sketch.sketchCurves.sketchArcs.addByThreePoints(vertex(curve['start']),
                      core.Point3D.create(mid[0].value/10, mid[1].value/10, 0), vertex(curve['end']))
                radial.append((arc, curve['radius'] * radius_scale))
            else:
                center = mapped(curve['center'])
                circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(
                    core.Point3D.create(center[0].value/10, center[1].value/10, 0), curve['radius'].value*radius_scale/10)
                dimensions.append((circle.centerSketchPoint, center[0], center[1]))
                radial.append((circle, curve['radius'] * radius_scale))
        coordinate_anchors = [{}, {}]
        for point, x, y in dimensions:
            for i, coordinate in enumerate((x, y)):
                self.stage = sketch.name + ' coordinate ' + str(i) + ': ' + coordinate.text + ' at ' + str(point.geometry.asArray())
                method = sketch.geometricConstraints.addVerticalPoints if i == 0 else sketch.geometricConstraints.addHorizontalPoints
                anchor = coordinate_anchors[i].get(coordinate.text)
                if anchor is not None:
                    method(anchor, point)
                elif abs(coordinate.value) < 1e-9:
                    # Zero at generation is an axis relation; crossing this branch requires rebuild.
                    method(sketch.originPoint, point)
                else:
                    orientation = [self.fusion.DimensionOrientations.HorizontalDimensionOrientation,
                                   self.fusion.DimensionOrientations.VerticalDimensionOrientation][i]
                    dim = sketch.sketchDimensions.addDistanceDimension(sketch.originPoint, point, orientation,
                          core.Point3D.create(point.geometry.x+0.1, point.geometry.y+0.1, 0))
                    dim.parameter.expression = self.expression(coordinate if coordinate.value > 0 else -coordinate)
                coordinate_anchors[i][coordinate.text] = point
        for curve, radius in radial:
            dim = sketch.sketchDimensions.addRadialDimension(curve, core.Point3D.create(1, 1, 0))
            dim.parameter.expression = self.expression(radius)
        selected = self.select_profiles(sketch, region, frame)
        if not sketch.isFullyConstrained:
            raise RuntimeError('Unconstrained native sketch: ' + sketch.name)
        return sketch, selected, normal_values[axis] * frame.matrix[axis][2]

    def select_profiles(self, sketch, region, frame):
        selected = []
        for profile in sketch.profiles:
            point = self.profile_sample(profile)
            # Back-project sample to the local XY plane of the extrusion.
            model = sketch.sketchToModelSpace(self.core.Point3D.create(point[0], point[1], 0))
            delta = [model.x*10-frame.origin[0].value, model.y*10-frame.origin[1].value, model.z*10-frame.origin[2].value]
            coords = [sum(delta[i]*frame.matrix[i][j] for i in range(3)) /
                      sum(frame.matrix[i][j]**2 for i in range(3)) for j in (0, 1)]
            if region.contains(*coords): selected.append(profile)
        if not selected:
            raise RuntimeError('No selected closed profiles in ' + sketch.name)
        return self.collection(selected)

    def profile_sample(self, profile):
        polygons = []
        for loop in profile.profileLoops:
            segments = []
            for curve in loop.profileCurves:
                evaluator = curve.geometry.evaluator
                ok, start, end = evaluator.getParameterExtents()
                if not ok: raise RuntimeError('Profile curve has no finite parameter interval')
                ok, strokes = evaluator.getStrokes(start, end, 0.00005)
                if not ok: raise RuntimeError('Profile curve tessellation failed')
                pairs = [(p.x, p.y) for p in strokes]
                segments.append(pairs)
            polygons.append((loop.isOuter, ordered_loop(segments)))

        def inside(x, y):
            def polygon(points):
                result = False
                for a, b in zip(points, points[1:]+points[:1]):
                    if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]: result = not result
                return result
            return any(polygon(p) for outer, p in polygons if outer) and not any(polygon(p) for outer, p in polygons if not outer)
        center = profile.areaProperties().centroid
        if inside(center.x, center.y): return center.x, center.y
        points = [p for _, loop in polygons for p in loop]
        low = [min(p[i] for p in points) for i in range(2)]
        high = [max(p[i] for p in points) for i in range(2)]
        for x in range(1, 33):
            for y in range(1, 33):
                candidate = (low[0]+(high[0]-low[0])*x/33, low[1]+(high[1]-low[1])*y/33)
                if inside(*candidate): return candidate
        raise RuntimeError('Could not find an interior profile sample')

    def extrude(self, node, frame, targets=None):
        region, height, centered = _extrusion(node)
        if centered:
            frame = Frame(frame.matrix, frame.point([Scalar(0), Scalar(0), -height/2]))
        sketch, profiles, direction = self.sketch_region(region, frame)
        operation = self.fusion.FeatureOperations.CutFeatureOperation if targets else self.fusion.FeatureOperations.NewBodyFeatureOperation
        inp = self.comp.features.extrudeFeatures.createInput(profiles, operation)
        inp.setOneSideExtent(self.fusion.DistanceExtentDefinition.create(self.core.ValueInput.createByString(
            self.expression(height * abs(direction)))), self.fusion.ExtentDirections.PositiveExtentDirection if direction > 0 else self.fusion.ExtentDirections.NegativeExtentDirection)
        if targets: inp.participantBodies = targets
        feature = self.comp.features.extrudeFeatures.add(inp)
        feature.name = ('SCAD cut ' if targets else 'SCAD extrude ') + str(self.count)
        sketch.isVisible = False
        return feature

    def join(self, bodies):
        merged = []
        for body in bodies:
            index = 0
            while index < len(merged):
                target = merged[index]
                distance = self.core.Application.get().measureManager.measureMinimumDistance(target, body).value
                if distance > 1e-7:
                    index += 1
                    continue
                inp = self.comp.features.combineFeatures.createInput(target, self.collection([body]))
                inp.operation = self.fusion.FeatureOperations.JoinFeatureOperation
                feature = self.comp.features.combineFeatures.add(inp)
                feature.name = 'SCAD union'
                body = feature.bodies.item(0)
                merged.pop(index)
                index = 0
            merged.append(body)
        return merged

    def revolve(self, node, frame):
        rounded = revolve_round_plan(node, frame, self.program.get('parameters'))
        profile = {'op':'polygon','args':{'points':rounded['points']},'children':[]} if rounded else _group(node['children'])
        region = Region(profile)
        angle = _s(node['args'].get('angle', 360))
        # Build about a local datum. World in-plane translation can make
        # equivalent zero profile ordinates receive redundant dimensions.
        scales,axes,sense = revolve_placement(frame)
        local_frame = Frame([[scales[i] if i==j else 0. for j in range(3)] for i in range(3)])
        profile_frame = revolve_profile_frame(local_frame)
        sketch, profiles, _ = self.sketch_region(region, profile_frame)
        start = local_frame.point([Scalar(0), Scalar(0), Scalar(0)])
        end = local_frame.point([Scalar(0), Scalar(0), Scalar(10)])
        points = [sketch.modelToSketchSpace(self.core.Point3D.create(*(v.value/10 for v in p))) for p in (start,end)]
        axis_points = [sketch.sketchPoints.add(point) for point in points]
        for point in axis_points: point.isFixed = True
        axis_input = self.comp.constructionAxes.createInput()
        axis_input.setByTwoPoints(*axis_points)
        axis = self.comp.constructionAxes.add(axis_input)
        axis.isLightBulbOn = False
        # Adding axis points recomputes sketch profiles and invalidates old handles.
        profiles = self.select_profiles(sketch, region, profile_frame)
        inp = self.comp.features.revolveFeatures.createInput(profiles, axis, self.fusion.FeatureOperations.NewBodyFeatureOperation)
        # The profile XZ frame normal is -Y; its positive in-plane axis is +Z.
        angle = _s(node['args'].get('angle', 360))
        inp.setAngleExtent(False, self.core.ValueInput.createByString('(' + self.expression(angle*sense,0) + ') * 1 deg'))
        feature = self.comp.features.revolveFeatures.add(inp)
        feature.name = 'SCAD revolve ' + str(self.count)
        sketch.isVisible = False
        bodies = list(feature.bodies)
        if rounded:
            for corner in rounded['fillets']:
                if len(bodies) != 1:
                    raise RuntimeError('Rounded Revolve requires one connected body')
                r, z = corner['position']
                edge = revolve_corner_edge(bodies[0], r.value*scales[0], z.value*scales[2])
                inp = self.comp.features.filletFeatures.createInput()
                radius = _s(corner['radius']) * scales[0]
                inp.edgeSetInputs.addConstantRadiusEdgeSet(self.collection([edge]),
                    self.core.ValueInput.createByString(self.expression(radius)), False)
                self.stage = 'SCAD fillet ' + radius.text
                fillet = self.comp.features.filletFeatures.add(inp)
                fillet.name = self.stage
                bodies = list(fillet.bodies)
        return self.place_bodies(bodies, frame, axes)

    def place_bodies(self, bodies, frame, axes):
        if any(abs(v.value)>1e-10 for v in frame.origin) or any(abs(v-(1 if i==j else 0))>1e-10 for j,axis in enumerate(axes) for i,v in enumerate(axis)):
            transform = self.core.Matrix3D.create()
            transform.setWithCoordinateSystem(self.core.Point3D.create(*(v.value/10 for v in frame.origin)),
                *(self.core.Vector3D.create(*axis) for axis in axes))
            inp = self.comp.features.moveFeatures.createInput2(self.collection(bodies))
            if not inp.defineAsFreeMove(transform): raise RuntimeError('Could not define solid placement')
            move = self.comp.features.moveFeatures.add(inp)
            move.name = 'SCAD solid placement (regenerate from SCAD)'
            bodies = list(move.bodies)
        return bodies

    def polyhedron(self, node, frame):
        self.stage = 'SCAD polyhedron line ' + str(node.get('line',1))
        points, faces = polyhedron_mesh(node['args'], frame)
        plan = helical_plan(node['args'], frame)
        if plan is not None:
            feature = create_helical_loft(self.core, self.fusion, self.comp, plan['sections'])
            return self.place_bodies(list(feature.bodies), frame, plan['axes'])
        body = create_polyhedron_body(self.core,self.fusion,points,faces)
        feature = self.comp.features.baseFeatures.add()
        feature.name = self.stage + ' (regenerate from SCAD)'
        feature.startEdit()
        try:
            added = self.comp.bRepBodies.add(body,feature)
            if added is None: raise RuntimeError('Could not add polyhedron to base feature')
        finally:
            feature.finishEdit()
        return list(feature.bodies)

    def build(self, node, frame=None):
        frame = frame or Frame()
        op = node['op']
        if op in ('translate', 'rotate', 'scale'):
            return self.build(_group(node['children']), frame.transformed(node))
        if op in ('union', 'for'):
            return self.join([body for child in node['children'] for body in self.build(child, frame)])
        if op == 'difference':
            if not node['children']: return []
            bodies = self.build(node['children'][0], frame)
            for cutter in node['children'][1:]: self.cut(cutter, frame, bodies)
            return bodies
        if op == 'rotate_extrude': return self.revolve(node,frame)
        if op == 'polyhedron': return self.polyhedron(node,frame)
        return list(self.extrude(node, frame).bodies)

    def cut(self, node, frame, targets):
        if node['op'] in ('translate', 'rotate', 'scale'):
            return self.cut(_group(node['children']), frame.transformed(node), targets)
        if node['op'] == 'for' and self.pattern_cut(node, frame, targets): return
        if node['op'] in ('union', 'for'):
            batch = batch_cylinder_cuts(node, frame)
            if batch:
                self.extrude(batch[0],batch[1],targets)
                return
            for child in node['children']: self.cut(child, frame, targets)
        elif node['op'] in ('difference','rotate_extrude','polyhedron'):
            tools = self.build(node, frame)
            for tool in tools:
                updated = []
                for index, target in enumerate(list(targets)):
                    inp = self.comp.features.combineFeatures.createInput(target, self.collection([tool]))
                    inp.operation = self.fusion.FeatureOperations.CutFeatureOperation
                    inp.isKeepToolBodies = index < len(targets)-1
                    feature = self.comp.features.combineFeatures.add(inp)
                    feature.name = 'SCAD composite cut'
                    updated.extend(list(feature.bodies))
                targets[:] = updated
        else:
            self.extrude(node, frame, targets)

    def pattern_cut(self, node, frame, targets):
        spec = pattern_spec(node, frame)
        if spec is None: return False
        seed = self.extrude(spec['seed'], spec['frame'], targets)
        axes = [self.comp.xConstructionAxis, self.comp.yConstructionAxis, self.comp.zConstructionAxis]
        first = spec['axes'][0]
        patterns = self.comp.features.rectangularPatternFeatures
        inp = patterns.createInput(self.collection([seed]), axes[first['axis']],
              self.core.ValueInput.createByString(self.expression(first['count'], 0)),
              self.core.ValueInput.createByString(self.expression(first['spacing'])),
              self.fusion.PatternDistanceType.SpacingPatternDistanceType)
        if len(spec['axes']) == 2:
            second = spec['axes'][1]
            inp.setDirectionTwo(axes[second['axis']],
                 self.core.ValueInput.createByString(self.expression(second['count'], 0)),
                 self.core.ValueInput.createByString(self.expression(second['spacing'])))
        # Identical compute fails at 1x1 in Fusion 2705; optimized recomputes the seed-only case.
        inp.patternComputeOption = self.fusion.PatternComputeOptions.OptimizedPatternCompute
        feature = patterns.add(inp)
        feature.name = 'SCAD range pattern ' + str(len(self.patterns)+1)
        self.patterns.append({'name': feature.name, 'axes': [
            {'axis': a['axis'], 'count': a['count'].value, 'spacing_mm': a['spacing'].value,
             'count_expression': self.expression(a['count'], 0), 'spacing_expression': self.expression(a['spacing'])}
            for a in spec['axes']]})
        return True


def native_report(design, builder):
    fusion = builder.fusion
    if not design.computeAll(): raise RuntimeError('Fusion computeAll failed')
    errors = []
    for i in range(design.timeline.count):
        entity = design.timeline.item(i).entity
        if isinstance(entity, fusion.Feature) and entity.healthState != fusion.FeatureHealthStates.HealthyFeatureHealthState:
            errors.append(entity.name + ': ' + entity.errorOrWarningMessage)
    if errors: raise RuntimeError('Feature health: ' + '; '.join(errors))
    bodies = []
    for body in design.rootComponent.bRepBodies:
        b = body.boundingBox
        bodies.append({'solid': body.isSolid, 'bounds_mm': [[b.minPoint.x*10,b.minPoint.y*10,b.minPoint.z*10],
                      [b.maxPoint.x*10,b.maxPoint.y*10,b.maxPoint.z*10]], 'volume_mm3': body.volume*1000,
                      'faces':body.faces.count, 'edges':body.edges.count})
    sketches = [{'name': s.name, 'fully_constrained': s.isFullyConstrained} for s in design.rootComponent.sketches]
    if any(not s['fully_constrained'] for s in sketches): raise RuntimeError('Sketch lost constraints after recompute')
    patterns = [{'name': p.name, 'count_x': p.quantityOne.value, 'count_y': p.quantityTwo.value,
                 'spacing_one_cm': p.distanceOne.value, 'spacing_two_cm': p.distanceTwo.value}
                for p in design.rootComponent.features.rectangularPatternFeatures]
    return {'status': 'passed', 'fusion_version': builder.core.Application.get().version,
            'bodies': bodies, 'timeline_count': design.timeline.count, 'patterns': patterns, 'sketches': sketches,
            'native_features':{'fillet':design.rootComponent.features.filletFeatures.count,
                               'loft':design.rootComponent.features.loftFeatures.count,
                               'base':design.rootComponent.features.baseFeatures.count}}


def run(context):
    import adsk.core as core
    import adsk.fusion as fusion
    app = core.Application.get()
    doc = app.documents.add(core.DocumentTypes.FusionDesignDocumentType)
    doc.name = PROGRAM['name']
    design = fusion.Design.cast(app.activeProduct)
    design.designType = fusion.DesignTypes.ParametricDesignType
    report_path = Path(__file__).with_name('native-report.json')
    builder = None
    try:
        builder = NativeBuilder(design, PROGRAM)
        builder.build(PROGRAM['geometry'])
        report = native_report(design, builder)
        report['source_sha256'] = PROGRAM['source_sha256']
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        app.activeViewport.fit()
        print(json.dumps(report))
        return doc
    except Exception:
        report_path.write_text(json.dumps({'status': 'failed', 'stage': builder.stage if builder else 'parameters',
                                         'traceback': traceback.format_exc()}, indent=2), encoding='utf-8')
        raise
