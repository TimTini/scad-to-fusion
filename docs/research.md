# Architecture decision and reference survey

2026-10-15/16. MVP uses a stdlib source parser, symbolic IR and a single native Fusion script backend. This keeps source expressions and generates reusable operation mappings; no tray-name recognizer or prebuilt tray script is part of conversion.

The local OpenSCAD 2026.09.29 probe successfully exported AST and CSG. AST retained `wall = width / 10`; CSG contained evaluated numbers. [OpenSCAD source](https://github.com/openscad/openscad/blob/master/src/openscad.cc) confirms different export paths. CSG alone therefore does not provide the formula graph needed for this goal. Source/AST parsing was selected; OpenSCAD remains the geometry reference.

Reference survey from primary README/documentation, without installing or executing third-party frameworks:

- [OpenSCAD_2_F360](https://github.com/schneik80/OpenSCAD_2_F360): README is an initial TODO list; no runnable converter capability established in this survey.
- [fscad](https://github.com/JesusFreke/fscad): Fusion API wrapper for programmatic CAD. Useful design reference; preservation of source expressions/native feature dependencies would still require implementation and tests.
- [scad123d](https://github.com/etjones/scad123d) and [scad2step](https://pypi.org/project/scad2step/): evaluate through OpenSCAD and rebuild using build123d/OpenCASCADE for solid/STEP output. Relevant for broad geometry conversion; this does not establish a native Fusion feature timeline linked to original SCAD parameters.
- [fusion360-addin-template](https://github.com/sorglos-it/fusion360-addin-template): packaging/lifecycle reference; Add-in is outside this MVP.

Third-party source code was not copied into the converter. The implementation uses Python stdlib and Fusion-supplied adsk. Audit extras and exact resolved versions are recorded in uv.lock. Source geometry fixture comes from the user's bath-sponge-tray project; no public release or license grant is asserted by this local repository.

Evidence-driven native choices:

- Fusion 2705.1.30 microprobe: positive-magnitude horizontal dimensions retained negative point coordinates after a parameter change; zero coordinates use axis relationships. Coordinate-sign branch crossings remain rebuild-only.
- Two identical coordinate distance dimensions on endpoints of a line produced overconstraint. Shared horizontal/vertical coordinate anchors remove duplicate driving constraints; all tested sketches are fully constrained.
- ProfileCurves enumeration is unordered. Stitch sampled segments by geometric endpoints before finding interior samples; a shoulder difference regression demonstrates the need.
- Native Pattern Identical compute failed at 1x1; Optimized and Adjust succeeded on the same test. Backend selects Optimized and verifies actual counts/health.
- Offset-square bounds must retain symbolic Scalars. Numeric extrema are valid for containment, but freezing contour coordinates broke resize; regression now checks preserved expression names.
- Local MCP script dispatch initially misdecoded a literal Unicode path. Encoding the injected Python configuration with `ascii(config)` preserves the Unicode runtime value through this transport. The copied package and the complete 13-case suite then passed. This is same-host path portability, not second-machine verification.

Future complex input is evaluated against the compatibility document and added as a fixture before expanding syntax/backend coverage. Optional backend abstractions and library integrations remain driven by demonstrated input needs.
# Toothbrush extension, Fusion2705.1.30, 2026-10-16

- `BRepBodyDefinition` can construct the original23.042-face thread as a solid using shared vertices/edges; tetrahedron and fullthread probes passed. Persist through an edited BaseFeature. The direct BRep requires regeneration for geometry changes; it has no automatic source-expression linkage.
- Native `min/max` expressions use semicolon-separated arguments. Comma syntax could create a zero-valued UserParameter in a probe and failed when applied to a sketch dimension. Render binary calls with`;` and nest calls for SCAD varargs. Regression tests protect this translation.
- Adding axis points recomputes sketch profiles: cached Profile handles may become invalid. Reselect profiles by Region containment after creating the axis.
- An inverted cap profile translated285.2mm in its sketch plane failed with `VCS_SKETCH_OVER_CONSTRAINTS` on equivalent zero ordinates expressed differently. Building the revolve at a local origin and applying a native Move translation removed that redundant-coordinate failure in the cap probe. Placement dependencies are explicitly `rebuild`; fullsuite results live in toothbrush validation.
- A finite-angle native Revolve depended on its sketch basis: a profile rotated90° ontoYZ swept into quadrantI instead of source quadrantII. Build every revolve in localXZ with positive radial/axial scales, then Move through the proper source rotation/translation. Reflections reverse sweep sense; reject shear. The native quarter-turn regression now checks phase and bounds explicitly.
-19coplanar cylinders of identical depth can share one Extrude Cut. The toothbrush timeline dropped from67to13 before the placement Move was added, with the same native volumes. Pattern recognition remains first choice for regular ranges.
- A single nearest-surface query on all dense-mesh vertices exhausted RAM. Batch256points retains the same allvertices+deterministic-samples method with bounded temporary proximity arrays. Closed two-part models compare component count with their reference, rather than assuming one part.
