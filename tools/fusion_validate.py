"""Run via Fusion MCP with CONFIG injected; touches only new test documents."""
import importlib.util
import json
from pathlib import Path
import sys
import traceback


def run(_context):
    import adsk.core as core
    import adsk.fusion as fusion
    app = core.Application.get()
    previous = app.activeDocument
    original_documents = list(app.documents)
    evidence = Path(CONFIG['evidence'])
    evidence.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        for index, case in enumerate(CONFIG['cases']):
            path = Path(case['script'])
            spec = importlib.util.spec_from_file_location('scad2fusion_native_case_' + str(index), path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            module.run(None)
            doc = app.activeDocument
            design = fusion.Design.cast(app.activeProduct)
            builder = object.__new__(module.NativeBuilder)
            builder.core, builder.fusion = core, fusion
            originals = {p.name: p.expression for p in design.userParameters}
            for variant in case['variants']:
                try:
                    for name, value in variant['parameters'].items():
                        design.userParameters.itemByName(name).expression = value
                    report = module.native_report(design, builder)
                    report['case'] = case['name']
                    report['variant'] = variant['name']
                    report['script_sha256'] = __import__('hashlib').sha256(path.read_bytes()).hexdigest()
                    if len(report['bodies']) != variant.get('body_count', 1):
                        raise RuntimeError('Unexpected body count: ' + str(report['bodies']))
                    actual = [[min(b['bounds_mm'][0][i] for b in report['bodies']) for i in range(3)],
                              [max(b['bounds_mm'][1][i] for b in report['bodies']) for i in range(3)]]
                    tolerance = variant.get('bounds_tolerance_mm',0.00001)
                    report['bounds_tolerance_mm'] = tolerance
                    if any(abs(a-b) > tolerance for row, expected in zip(actual, variant['bounds_mm']) for a, b in zip(row, expected)):
                        raise RuntimeError('Bounds mismatch: ' + str(actual))
                    if 'volume_mm3' in variant:
                        volume = sum(b['volume_mm3'] for b in report['bodies'])
                        if abs(volume-variant['volume_mm3']) > 0.00001: raise RuntimeError('Volume mismatch: ' + str(volume))
                    if 'grid' in variant:
                        pattern = design.rootComponent.features.rectangularPatternFeatures.item(0)
                        if [pattern.quantityOne.value, pattern.quantityTwo.value] != variant['grid']:
                            raise RuntimeError('Pattern count mismatch')
                    if 'circle_centers' in variant:
                        circles = [circle for sketch in design.rootComponent.sketches for circle in sketch.sketchCurves.sketchCircles]
                        for expected in variant['circle_centers']:
                            if not any(max(abs(a-b) for a,b in zip([circle.centerSketchPoint.worldGeometry.x*10,
                                circle.centerSketchPoint.worldGeometry.y*10,circle.centerSketchPoint.worldGeometry.z*10], expected)) < 0.00001 for circle in circles):
                                raise RuntimeError('Missing circle center ' + str(expected))
                    tag = case['name'] + '_' + variant['name']
                    stl = design.exportManager.createSTLExportOptions(design.rootComponent, str(evidence / (tag + '.stl')))
                    stl.meshRefinement = fusion.MeshRefinementSettings.MeshRefinementHigh
                    stl.surfaceDeviation = 0.0002  # cm; 0.002 mm tessellation
                    stl.normalDeviation = 0.05
                    if not design.exportManager.execute(stl): raise RuntimeError('STL export failed')
                    if variant['name'] == 'baseline':
                        step = design.exportManager.createSTEPExportOptions(str(evidence / (tag + '.step')), design.rootComponent)
                        if not design.exportManager.execute(step): raise RuntimeError('STEP export failed')
                    results.append(report)
                finally:
                    for name, value in originals.items(): design.userParameters.itemByName(name).expression = value
                    design.computeAll()
            doc.close(False)
    except Exception:
        results.append({'status': 'failed', 'traceback': traceback.format_exc()})
        raise
    finally:
        (evidence / 'native-validation.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        for doc in list(app.documents):
            if doc not in original_documents: doc.close(False)
        if previous: previous.activate()
    print(json.dumps({'cases': len(results), 'status': 'passed', 'evidence': str(evidence)}))
