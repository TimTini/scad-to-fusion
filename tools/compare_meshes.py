"""Compare OpenSCAD reference and Fusion export in millimetres (audit extras)."""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


def compare(reference, candidate, sections=None):
    a = trimesh.load_mesh(reference, process=True)
    b = trimesh.load_mesh(candidate, process=True)
    if not a.is_watertight or not b.is_watertight:
        raise ValueError('Geometry comparison requires two closed meshes')
    a_minus_b = trimesh.boolean.difference([a, b], engine='manifold')
    b_minus_a = trimesh.boolean.difference([b, a], engine='manifold')
    symmetric = float(abs(a_minus_b.volume) + abs(b_minus_a.volume))
    deviations = []
    for source, target in ((a, b), (b, a)):
        samples, _ = trimesh.sample.sample_surface(source, 10000, seed=0)
        points = np.vstack([source.vertices, samples])
        maximum = 0.
        for start in range(0,len(points),256):
            _, distances, _ = trimesh.proximity.closest_point(target, points[start:start+256])
            maximum = max(maximum,float(np.max(distances)))
        deviations.append(maximum)
    result = {
        'reference': str(reference), 'candidate': str(candidate),
        'bounds_error_mm': float(np.max(np.abs(a.bounds-b.bounds))),
        'reference_volume_mm3': float(a.volume), 'candidate_volume_mm3': float(b.volume),
        'relative_volume_error': float(abs(a.volume-b.volume)/abs(a.volume)),
        'symmetric_difference_mm3': symmetric,
        'relative_symmetric_difference': symmetric/abs(a.volume),
        'reference_components': len(a.split()),
        'candidate_components': len(b.split()), 'candidate_watertight': b.is_watertight,
        'sampled_bidirectional_surface_error_mm': max(deviations),
        'surface_method': 'All vertices plus 10000 deterministic surface samples per mesh; not exact Hausdorff proof',
        'sections': [],
    }
    if sections is None: sections = ((2, 1.5), (1, float(a.bounds[1, 1]-1.5)))
    for axis, location in sections:
        normal = np.zeros(3); normal[axis] = 1
        origin = np.zeros(3); origin[axis] = location
        counts = []
        for mesh in (a, b):
            section = mesh.section(plane_origin=origin, plane_normal=normal)
            if section is None: raise ValueError('Missing section')
            counts.append(len(section.discrete))
        result['sections'].append({'axis': axis, 'location_mm': location, 'reference_loops': counts[0], 'candidate_loops': counts[1]})
    result['status'] = 'passed' if (result['bounds_error_mm'] <= .05 and
          result['relative_volume_error'] <= .005 and result['relative_symmetric_difference'] <= .005 and
          result['sampled_bidirectional_surface_error_mm'] <= .05 and
          result['candidate_components'] == result['reference_components'] and all(s['reference_loops'] == s['candidate_loops'] for s in result['sections'])) else 'failed'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--section', action='append', metavar='AXIS=MM', help='Section plane, e.g. Z=1.5; repeat for multiple planes')
    args = parser.parse_args()
    sections = None
    if args.section:
        sections = []
        for item in args.section:
            axis, separator, location = item.partition('=')
            if not separator or axis.upper() not in ('X','Y','Z'):
                parser.error('Section must be X=MM, Y=MM or Z=MM')
            sections.append(('XYZ'.index(axis.upper()),float(location)))
    result = compare(args.reference, args.candidate, sections)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
