"""Validated source mesh and revolve geometry, shared by offline and Fusion builds."""
import math
from .planar import Scalar


def revolve_profile_frame(frame):
    # SCAD profile (radius, height) lies in XZ; positive rotation is about Z.
    matrix = [[row[0], row[2], -row[1]] for row in frame.matrix]
    radial_x = math.sqrt(sum(row[0]**2 for row in frame.matrix))
    radial_y = math.sqrt(sum(row[1]**2 for row in frame.matrix))
    if abs(radial_x-radial_y) > 1e-9:
        raise ValueError('rotate_extrude requires uniform radial scale')
    return type(frame)(matrix, frame.origin)


def revolve_placement(frame):
    columns = [[row[j] for row in frame.matrix] for j in range(3)]
    scales = [math.sqrt(sum(v*v for v in column)) for column in columns]
    if min(scales) < 1e-12: raise ValueError('Revolve scale must be nonzero')
    if abs(scales[0]-scales[1]) > 1e-9:
        raise ValueError('rotate_extrude requires uniform radial scale')
    unit = [[v/length for v in column] for column,length in zip(columns,scales)]
    if any(abs(sum(a*b for a,b in zip(unit[i],unit[j])))>1e-9 for i,j in ((0,1),(0,2),(1,2))):
        raise ValueError('Sheared rotate_extrude transforms are outside supported geometry')
    x,z = unit[0],unit[2]
    y = [z[(i+1)%3]*x[(i+2)%3]-z[(i+2)%3]*x[(i+1)%3] for i in range(3)]
    sense = 1 if sum(a*b for a,b in zip(y,unit[1]))>0 else -1
    return scales,[x,y,z],sense


def polyhedron_mesh(args, frame):
    points = [[Scalar.from_ir(v).value for v in frame.point([Scalar.from_ir(v) for v in p])]
              for p in args['points'] if len(p) == 3]
    if len(points) != len(args['points']) or len(points) < 4:
        raise ValueError('polyhedron requires at least four 3D points')
    if any(not math.isfinite(v) for p in points for v in p):
        raise ValueError('polyhedron coordinates must be finite')
    faces, edges, volume = [], {}, 0.
    for raw in args['faces']:
        face = [Scalar.from_ir(v).value for v in raw]
        if len(face) < 3 or any(not isinstance(v, (int,float)) or int(v) != v or not 0 <= v < len(points) for v in face):
            raise ValueError('polyhedron face has invalid vertex indices')
        face = [int(v) for v in face]
        if len(set(face)) != len(face):
            raise ValueError('polyhedron face repeats a vertex')
        a, b, c = [points[v] for v in face[:3]]
        u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
        normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        length = math.sqrt(sum(x*x for x in normal))
        if length < 1e-12: raise ValueError('polyhedron has a degenerate face')
        if any(abs(sum((points[j][i]-a[i])*normal[i] for i in range(3)))/length > 1e-6 for j in face):
            raise ValueError('polyhedron faces must be planar')
        for start, end in zip(face, face[1:]+face[:1]):
            edges.setdefault(tuple(sorted((start,end))), []).append((start,end))
        for j in range(1,len(face)-1):
            b,c = points[face[j]],points[face[j+1]]
            volume += sum(a[i]*(b[(i+1)%3]*c[(i+2)%3]-b[(i+2)%3]*c[(i+1)%3]) for i in range(3))/6
        faces.append(face)
    if any(len(pair) != 2 or pair[0] != pair[1][::-1] for pair in edges.values()):
        raise ValueError('polyhedron must be a closed consistently oriented manifold')
    neighbors = {}
    for a,b in edges:
        neighbors.setdefault(a,set()).add(b)
        neighbors.setdefault(b,set()).add(a)
    reached, pending = set(), [next(iter(neighbors))] if neighbors else []
    while pending:
        vertex = pending.pop()
        if vertex not in reached:
            reached.add(vertex)
            pending.extend(neighbors[vertex]-reached)
    if len(reached) != len(neighbors):
        raise ValueError('polyhedron requires one connected shell; use separate polyhedron solids for separate shells')
    if abs(volume) < 1e-9: raise ValueError('polyhedron must enclose nonzero volume')
    if volume < 0: faces = [list(reversed(face)) for face in faces]
    return points, faces


def create_polyhedron_body(core, fusion, points, faces):
    definition = fusion.BRepBodyDefinition.create()
    definition.doFullHealing = False
    vertices = [definition.createVertexDefinition(core.Point3D.create(*(v/10 for v in p))) for p in points]
    shell = definition.lumpDefinitions.add().shellDefinitions.add()
    edges = {}
    for face in faces:
        a,b,c = [core.Point3D.create(*(v/10 for v in points[j])) for j in face[:3]]
        normal = a.vectorTo(b).crossProduct(a.vectorTo(c))
        normal.normalize()
        surface = core.Plane.create(a, normal)
        loop = shell.faceDefinitions.add(surface, False).loopDefinitions.add()
        for start,end in zip(face,face[1:]+face[:1]):
            key = tuple(sorted((start,end)))
            if key not in edges:
                first,last = key
                line = core.Line3D.create(core.Point3D.create(*(v/10 for v in points[first])),core.Point3D.create(*(v/10 for v in points[last])))
                edges[key] = definition.createEdgeDefinitionByCurve(vertices[first],vertices[last],line)
            loop.bRepCoEdgeDefinitions.add(edges[key], start != key[0])
    body = definition.createBody()
    if body is None or not body.isSolid:
        raise RuntimeError('polyhedron BRep construction failed: ' + str(definition.outcomeInfo))
    return body
