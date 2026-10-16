"""Prepare an experimental source-section Loft probe from source polyhedra.

Run the emitted probe.py as a Fusion script, or dispatch it through the local
MCP runner. This does not alter converter output. Mesh audit dependencies are
needed only here; the emitted Fusion script uses the standard library and adsk.
"""
import argparse
import json
import math
from pathlib import Path

from scad2fusion.frontend import compile_source
from scad2fusion.generator import json_value
from scad2fusion.helical import recognize_helical_sections, select_sections


def prepare(source, output, max_angle=15):
    import trimesh
    if not math.isfinite(max_angle) or not 0 < max_angle <= 45:
        raise ValueError('max-angle must be in (0, 45] degrees')
    program = json_value(compile_source(source.read_text(encoding='utf-8'), filename=source.name))
    def walk(node):
        yield node
        for child in node['children']:
            yield from walk(child)
    cases = []
    meshes = []
    for node in walk(program['geometry']):
        if node['op'] != 'polyhedron':
            continue
        points, faces = node['args']['points'], node['args']['faces']
        recognized = recognize_helical_sections(points, faces)
        if recognized is None:
            continue
        name = 'helix-' + str(len(cases) + 1)
        selected = select_sections(recognized['sections'], max_angle)
        cases.append({'name': name, 'sections': selected,
                      'source_sections': len(recognized['sections']), 'source_faces': len(faces),
                      'pitch': recognized['pitch'], 'profile_sagitta': recognized['profile_sagitta']})
        triangles = [[f[0], f[i], f[i + 1]] for f in faces for i in range(1, len(f) - 1)]
        mesh = trimesh.Trimesh(vertices=points, faces=triangles, process=False)
        mesh.fix_normals()
        meshes.append((name, mesh))
    if not cases:
        raise ValueError('No supported helical polyhedra found')
    output.mkdir(parents=True, exist_ok=False)
    for name, mesh in meshes:
        mesh.export(output / (name + '-reference.stl'))
    config = {'cases': cases, 'evidence': str(output.resolve())}
    template = Path(__file__).with_name('fusion_helix_probe.py').read_text(encoding='utf-8')
    script = 'PROBE = ' + ascii(config) + '\n' + template
    compile(script, 'probe.py', 'exec')
    (output / 'probe.py').write_text(script, encoding='utf-8')
    (output / 'recognition.json').write_text(json.dumps(cases, indent=2), encoding='utf-8')
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, help='New, private evidence directory')
    parser.add_argument('--max-angle', type=float, default=15)
    args = parser.parse_args()
    cases = prepare(args.source, args.output, args.max_angle)
    print(json.dumps([{'name': c['name'], 'source_sections': c['source_sections'],
                       'loft_sections': len(c['sections'])} for c in cases]))


if __name__ == '__main__':
    main()
