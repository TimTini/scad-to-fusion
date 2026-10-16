# Development progress

## Verified public baseline

Scope: source-driven conversion of the documented OpenSCAD subset to standalone Autodesk Fusion Python scripts. The current baseline has 93 offline tests, 19 native cases and four toothbrush mesh comparisons. Detailed evidence is linked from testing.md and toothbrush-validation.md.

Publication uses a fresh Git history containing source, fixtures, tests, tools and sanitized documentation/evidence. Private prompts, local work logs, machine paths, runtime output and environment files are excluded. Numeric evidence and source hashes are retained; paths in evidence identify relative artifacts rather than a developer machine.

## Next checkpoint: simpler native geometry

Preserve the verified baseline before experimenting. Recognize geometric regularity from source-derived data without hard-coding project/module/parameter names. Start with rounded helical geometry while retaining its radial/Z section, phase, pitch and end taper. Add offline recognition tests, run isolated native probes, measure face/feature count and compare shape against the source. Keep arbitrary polyhedron support explicit. Publish updates only after independent review and relevant verification; no physical fit claim follows from CAD checks.
