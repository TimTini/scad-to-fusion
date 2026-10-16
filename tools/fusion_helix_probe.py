"""Isolated native experiment, embedded by prepare_helix_probe.py."""
import json
from pathlib import Path
import time
import sys
import adsk.core
import adsk.fusion


def run(context):
    app = adsk.core.Application.get()
    previous = app.activeDocument
    reports = []
    for case in PROBE['cases']:
        report = {'name': case['name'], 'native_health': 'not_run', 'fidelity': 'not_run'}
        reports.append(report)
        doc = None
        try:
            doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            design = adsk.fusion.Design.cast(app.activeProduct)
            comp = design.rootComponent
            started = time.monotonic()
            profiles = []
            for section in case['sections']:
                inp = comp.constructionPlanes.createInput()
                if not inp.setByAngle(comp.zConstructionAxis,
                        adsk.core.ValueInput.createByReal(section['angle']), comp.xZConstructionPlane):
                    raise RuntimeError('Could not define radial section plane')
                plane = comp.constructionPlanes.add(inp)
                sketch = comp.sketches.add(plane)
                world = adsk.core.Point3D.create(*(v / 10 for v in section['center']))
                center = sketch.modelToSketchSpace(world)
                if abs(center.z) > 1e-6:
                    raise RuntimeError('Section center is outside its radial/Z plane')
                vertices = [sketch.modelToSketchSpace(adsk.core.Point3D.create(*(v / 10 for v in point)))
                            for point in section['vertices']]
                if any(abs(p.z) > 1e-6 for p in vertices):
                    raise RuntimeError('Section vertices are outside their radial/Z plane')
                anchors = [sketch.sketchPoints.add(p) for p in vertices]
                for point in anchors:
                    point.isFixed = True
                for a, b in zip(anchors, anchors[1:] + anchors[:1]):
                    sketch.sketchCurves.sketchLines.addByTwoPoints(a, b)
                if sketch.profiles.count != 1 or not sketch.isFullyConstrained:
                    raise RuntimeError('Expected one fully constrained polygon profile; count=' +
                                       str(sketch.profiles.count) + ', constrained=' + str(sketch.isFullyConstrained) +
                                       ', section=' + str(len(profiles)))
                profiles.append(sketch.profiles.item(0))
                sketch.isLightBulbOn = False
                plane.isLightBulbOn = False
            inp = comp.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            inp.isSolid = True
            inp.isClosed = False
            for profile in profiles:
                inp.loftSections.add(profile)
            loft = comp.features.loftFeatures.add(inp)
            design.computeAll()
            if loft.bodies.count != 1:
                raise RuntimeError('Expected one Loft solid')
            body = loft.bodies.item(0)
            if not body.isSolid or loft.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
                raise RuntimeError('Unhealthy Loft: ' + loft.errorOrWarningMessage)
            manager = design.exportManager
            options = manager.createSTLExportOptions(body, str(Path(PROBE['evidence']) / (case['name'] + '-loft.stl')))
            options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementCustom
            options.surfaceDeviation = .0005  # cm: 0.005 mm
            options.normalDeviation = .05
            options.maximumEdgeLength = .05
            if not manager.execute(options):
                raise RuntimeError('Loft STL export failed')
            report.update({'source_faces': case['source_faces'],
                      'source_sections': case['source_sections'], 'loft_sections': len(profiles),
                      'native_faces': body.faces.count, 'solid': body.isSolid,
                      'volume_mm3': body.volume * 1000, 'seconds': time.monotonic() - started,
                      'high_accuracy_volume_mm3': body.getPhysicalProperties(
                          adsk.fusion.CalculationAccuracy.HighCalculationAccuracy).volume * 1000,
                      'profile_representation': 'source_polygon',
                      'fusion_build': app.version, 'native_health': 'passed'})
            print(json.dumps(report))
        finally:
            error = sys.exc_info()[1]
            if error is not None:
                report.update({'native_health': 'failed', 'error': str(error)})
            Path(PROBE['evidence'], 'native-probe.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
            if doc:
                doc.close(False)
            if previous:
                previous.activate()
