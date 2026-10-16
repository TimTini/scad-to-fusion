"""Conservative offline recovery of stacked polygon profiles from a mesh.

The recognizer deliberately stops at a measured profile plan.  It does not
claim that a later Fusion loft has the same surface, volume, or topology as
the source mesh; the reported error is only the 2D vertex interpolation error
between selected source sections.
"""

import math


_AXIS_NAMES = ("x", "y", "z")
_PROFILE_AXES = (("y", "z"), ("x", "z"), ("x", "y"))


def _finite_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _tolerance(points):
    extent = max(max(p[axis] for p in points) - min(p[axis] for p in points)
                 for axis in range(3))
    ulp = max(math.ulp(value) for point in points for value in point)
    return max(1e-8, extent * 1e-9, ulp * 8)


def _profile_area(profile):
    return math.fsum(a * next_b - b * next_a
                     for (a, b), (next_a, next_b) in zip(
                         profile, profile[1:] + profile[:1])) / 2


def _same_profile(left, right, tolerance):
    return (len(left) == len(right)
            and all(math.dist(a, b) <= tolerance for a, b in zip(left, right)))


def _ring_size(points, axis, tolerance):
    """Return the first contiguous plane run, or None."""
    if not points:
        return None
    first = points[0][axis]
    size = 1
    while size < len(points) and abs(points[size][axis] - first) <= tolerance:
        size += 1
    if size < 3 or size == len(points) or len(points) % size:
        return None
    return size


def _rings(points, axis, sides, tolerance):
    rings = []
    for start in range(0, len(points), sides):
        ring = points[start:start + sides]
        plane = ring[0][axis]
        if any(abs(point[axis] - plane) > tolerance for point in ring):
            return None
        rings.append((plane, ring))
    if len(rings) < 2:
        return None
    direction = rings[1][0] - rings[0][0]
    if abs(direction) <= tolerance:
        return None
    if any((right[0] - left[0]) * direction <= tolerance * abs(direction)
           for left, right in zip(rings, rings[1:])):
        return None
    return rings


def _face_edges(face):
    return zip(face, face[1:] + face[:1])


def _validate_connectivity(faces, sides, ring_count):
    """Validate one polygon cap at each end and triangulated side quads."""
    if len(faces) != 2 + 2 * sides * (ring_count - 1):
        return False
    first = set(range(sides))
    last = set(range((ring_count - 1) * sides, ring_count * sides))
    caps = {0: [], ring_count - 1: []}
    side_triangles = {}
    all_edges = {}
    for raw in faces:
        face = list(raw)
        if len(face) < 3 or len(set(face)) != len(face):
            return False
        face_set = set(face)
        if face_set <= first:
            caps[0].append(face)
            continue
        if face_set <= last:
            caps[ring_count - 1].append(face)
            continue
        if len(face) != 3:
            return False
        rings = {value // sides for value in face}
        if len(rings) != 2:
            return False
        low, high = sorted(rings)
        if high != low + 1 or any(not (low * sides <= value < (low + 2) * sides)
                                  for value in face):
            return False
        normalized = tuple(sorted(face))
        if normalized in side_triangles.setdefault(low, set()):
            return False
        side_triangles[low].add(normalized)
    if len(caps[0]) != 1 or len(caps[ring_count - 1]) != 1:
        return False
    for cap, expected in ((caps[0][0], first), (caps[ring_count - 1][0], last)):
        if set(cap) != expected:
            return False
        if any((right - left) % sides not in (1, sides - 1)
               for left, right in _face_edges(cap)):
            return False

    expected_triangle_count = 2 * sides
    for strip in range(ring_count - 1):
        triangles = side_triangles.get(strip, set())
        if len(triangles) != expected_triangle_count:
            return False
        for side in range(sides):
            nxt = (side + 1) % sides
            a, b = strip * sides + side, strip * sides + nxt
            c, d = a + sides, b + sides
            quad = {a, b, c, d}
            matches = [triangle for triangle in triangles if set(triangle) <= quad]
            if len(matches) != 2 or set().union(*map(set, matches)) != quad:
                return False

    # Every mesh edge must have two incident faces.  This catches a face
    # accidentally assigned to a neighboring strip even when the counts match.
    for face in faces:
        for start, end in _face_edges(list(face)):
            all_edges.setdefault(tuple(sorted((start, end))), []).append((start, end))
    if any(len(incidents) != 2 for incidents in all_edges.values()):
        return False
    if any(incidents[0] != tuple(reversed(incidents[1])) for incidents in all_edges.values()):
        return False
    return True


def _make_source_sections(rings, axis, tolerance):
    sections = []
    signs = []
    degenerate = []
    for index, (plane, ring) in enumerate(rings):
        profile_axes = [coordinate for coordinate in range(3) if coordinate != axis]
        profile = [(point[profile_axes[0]], point[profile_axes[1]]) for point in ring]
        area = _profile_area(profile)
        if abs(area) <= tolerance * tolerance:
            degenerate.append(index)
        else:
            signs.append(1 if area > 0 else -1)
        sections.append({
            "index": index,
            "plane": float(plane),
            "profile": profile,
            "vertices": [tuple(point) for point in ring],
            "degenerate": abs(area) <= tolerance * tolerance,
        })
    if not signs or len(set(signs)) != 1:
        return None
    return sections, degenerate


def _circle_data(sections, tolerance):
    centers = []
    radii = []
    for section in sections:
        profile = section["profile"]
        center = (math.fsum(point[0] for point in profile) / len(profile),
                  math.fsum(point[1] for point in profile) / len(profile))
        radius = math.fsum(math.dist(point, center) for point in profile) / len(profile)
        if radius <= tolerance:
            return None
        residual = max(abs(math.dist(point, center) - radius) for point in profile)
        if residual > tolerance:
            return None
        centers.append(center)
        radii.append(radius)
    if max(math.dist(center, centers[0]) for center in centers) > tolerance:
        return None
    return {"center": tuple(centers[0]), "radii": radii,
            "max_circle_residual": max(
                abs(math.dist(point, centers[i]) - radii[i])
                for i, section in enumerate(sections)
                for point in section["profile"])}


def _interpolation_error(sections, left, right, index):
    a, b = sections[left], sections[right]
    target = sections[index]
    fraction = ((target["plane"] - a["plane"]) /
                (b["plane"] - a["plane"]))
    return max(math.dist(point,
                         tuple((1 - fraction) * first + fraction * second
                               for first, second in zip(a_point, b_point)))
               for point, a_point, b_point in zip(
                   target["profile"], a["profile"], b["profile"]))


def _select_indices(sections, max_sections):
    if len(sections) <= max_sections:
        return list(range(len(sections))), 0.0
    selected = {0, len(sections) - 1}
    while len(selected) < max_sections:
        ordered = sorted(selected)
        best = None
        for left, right in zip(ordered, ordered[1:]):
            for index in range(left + 1, right):
                if index in selected:
                    continue
                error = _interpolation_error(sections, left, right, index)
                candidate = (error, -index, index)
                if best is None or candidate > best:
                    best = candidate
        if best is None or best[0] <= 0.0:
            break
        selected.add(best[2])
    ordered = sorted(selected)
    maximum = 0.0
    for left, right in zip(ordered, ordered[1:]):
        for index in range(left + 1, right):
            maximum = max(maximum, _interpolation_error(sections, left, right, index))
    return ordered, maximum


def _tail_start(sections, tolerance):
    if len(sections) < 3:
        return None
    start = len(sections) - 1
    while start > 0 and _same_profile(sections[start - 1]["profile"],
                                      sections[-1]["profile"], tolerance):
        start -= 1
    return start if 0 < start < len(sections)-1 else None


def recognize_layered_sections(points, faces, max_sections=5):
    """Return a bounded plan for an ordered, axis-aligned ring mesh.

    ``sections`` contains at most ``max_sections`` source profiles.  ``mode``
    is ``extrude`` for a fixed profile, ``circular_radius_law`` for concentric
    circular profiles with changing radii, and ``loft`` for other smooth
    profile changes.  A constant suffix is exposed as ``tail_extrusion`` so a
    caller can retain that exact prismatic region separately.
    """
    if (not isinstance(points, (list, tuple)) or len(points) < 6
            or any(not isinstance(point, (list, tuple)) or len(point) != 3
                   or any(not _finite_number(value) for value in point)
                   for point in points)
            or not isinstance(faces, (list, tuple)) or not faces
            or any(not isinstance(face, (list, tuple)) or len(face) < 3
                   or any(isinstance(value, bool) or not isinstance(value, int)
                          or not 0 <= value < len(points) for value in face)
                   for face in faces)
            or isinstance(max_sections, bool) or not isinstance(max_sections, int)
            or max_sections < 2):
        return None
    max_sections = min(max_sections, 5)
    numeric_points = [tuple(float(value) for value in point) for point in points]
    tolerance = _tolerance(numeric_points)
    candidates = []
    for axis in range(3):
        sides = _ring_size(numeric_points, axis, tolerance)
        if sides is None:
            continue
        rings = _rings(numeric_points, axis, sides, tolerance)
        if rings is None or not _validate_connectivity(faces, sides, len(rings)):
            continue
        section_data = _make_source_sections(rings, axis, tolerance)
        if section_data is not None:
            sections, degenerate = section_data
            candidates.append((axis, sides, sections, degenerate))
    if len(candidates) != 1:
        return None

    axis, sides, source_sections, degenerate_profiles = candidates[0]
    tail_start = _tail_start(source_sections, tolerance)
    working = source_sections[:tail_start + 1] if tail_start is not None else source_sections
    all_identical = all(_same_profile(working[0]["profile"], section["profile"], tolerance)
                         for section in working[1:])
    circle = _circle_data(working, tolerance)
    radii_vary = (circle is not None and
                  max(circle["radii"]) - min(circle["radii"]) > tolerance)
    if all_identical:
        mode = "extrude"
    elif radii_vary:
        mode = "circular_radius_law"
    else:
        mode = "loft"
    indices, interpolation_error = _select_indices(working, max_sections)
    selected = [working[index] for index in indices]
    tail = None
    if tail_start is not None:
        tail = {
            "start_index": tail_start,
            "end_index": len(source_sections) - 1,
            "plane_start": source_sections[tail_start]["plane"],
            "plane_end": source_sections[-1]["plane"],
            "profile": list(source_sections[tail_start]["profile"]),
        }
    result = {
        "axis": _AXIS_NAMES[axis],
        "axis_index": axis,
        "profile_axes": _PROFILE_AXES[axis],
        "ring_size": sides,
        "source_section_count": len(source_sections),
        "degenerate_profiles": degenerate_profiles,
        "source_sections": source_sections,
        "selected_indices": indices,
        "sections": selected,
        "mode": mode,
        "tail_extrusion": tail,
        "max_profile_interpolation_error": interpolation_error,
        "max_vertex_residual": 0.0,
        "tolerance": tolerance,
        "error_scope": "2D profile vertex interpolation residual; does not bound loft surface error; collapsed source vertices are retained",
    }
    if circle is not None:
        result["circle"] = circle
    return result


def layered_plan(args, max_sections=5):
    """Return the compact numeric plan consumed by the native builder.

    ``args`` is the serialized polyhedron argument mapping.  The full source
    rings remain available as ``all_rings``; ``sections`` is the bounded
    selection intended for a smooth continuous zone.
    """
    if not isinstance(args, dict):
        return None
    result = recognize_layered_sections(args.get("points"), args.get("faces"), max_sections)
    if result is None:
        return None

    def public_section(section):
        return {
            "index": section["index"],
            "position": section["plane"],
            "points": [list(point) for point in section["profile"]],
        }

    plan = dict(result)
    plan["axis"] = result["axis_index"]
    plan["axis_name"] = result["axis"]
    plan["source_sections"] = result["source_section_count"]
    plan["sections"] = [public_section(section) for section in result["sections"]]
    plan["all_rings"] = [public_section(section) for section in result["source_sections"]]
    if result["tail_extrusion"] is not None:
        tail = dict(result["tail_extrusion"])
        tail["points"] = [list(point) for point in tail.pop("profile")]
        plan["tail_extrusion"] = tail
    return plan


__all__ = ["layered_plan", "recognize_layered_sections"]
