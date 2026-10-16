"""Generate isolated native regression packages and a Fusion harness config."""
import json
import math
from pathlib import Path
import re
import shutil
import sys

from scad2fusion.generator import generate_package


def main():
    root = Path(__file__).resolve().parents[1]
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'work/evidence/native-suite'
    directory = directory.resolve()
    if directory.exists(): raise FileExistsError('Choose a new suite directory: ' + str(directory))
    directory.mkdir(parents=True)
    tray = root / 'tests/fixtures/tray.scad'
    packages = directory / 'packages'
    paths = {}
    for name, source, overrides in [('Tray', tray, {}), ('Two', tray, {'hook_count': 2}),
        ('Composite', root/'tests/fixtures/composite.scad', {}), ('Bridge', root/'tests/fixtures/bridge.scad', {}),
        ('Hexagon', root/'tests/fixtures/hexagon.scad', {}), ('Plate', root/'tests/fixtures/plate.scad', {}),
        ('RevolveCuts',root/'tests/fixtures/revolve-polyhedron-cuts.scad',{}),
        ('PartialRevolve',root/'tests/fixtures/partial-revolve.scad',{})]:
        generate_package(source, packages/name, overrides)
        paths[name] = str(packages/name/(name+'.py'))
    text = tray.read_text(encoding='utf-8-sig')
    for old, new in [('rounded_rectangle','smooth_outline'), ('length','span_x'), ('width','span_y')]:
        text = re.sub(r'\b' + old + r'\b', new, text)
    renamed = directory / 'renamed.scad'
    renamed.write_text(text, encoding='utf-8')
    generate_package(renamed, packages/'Renamed')
    paths['Renamed'] = str(packages/'Renamed/Renamed.py')
    portable = directory / 'Bộ có khoảng trắng/Tray'
    shutil.copytree(packages/'Tray', portable)

    def variant(name, parameters, top, **checks):
        return {'name': name, 'parameters': parameters, 'bounds_mm': [[0,0,0],top], **checks}

    cases = [
        {'name':'tray','script':paths['Tray'],'variants':[
            variant('baseline',{},[100,70,47],grid=[7,5],circle_centers=[[50,70.05,38.5]]),
            variant('resize',{'length':'160 mm','width':'100 mm','ear_rise':'20 mm'},[160,100,50],grid=[12,7],circle_centers=[[80,100.05,40]]),
            variant('one',{'length':'52 mm','width':'21 mm','drain_pitch':'40 mm'},[52,21,47],grid=[1,1],circle_centers=[[26,21.05,38.5]])]},
        {'name':'two','script':paths['Two'],'variants':[
            variant('baseline',{},[100,70,30],grid=[7,5],circle_centers=[[20,70.05,20],[80,70.05,20]]),
            variant('resize',{'length':'150 mm','hook_spacing':'80 mm','hook_height':'22 mm'},[150,70,30],grid=[11,5],circle_centers=[[35,70.05,22],[115,70.05,22]])]},
        {'name':'composite','script':paths['Composite'],'variants':[variant('baseline',{},[10,10,2],body_count=2,volume_mm3=194)]},
        {'name':'bridge','script':paths['Bridge'],'variants':[variant('baseline',{},[6,2,2],volume_mm3=24)]},
        {'name':'hexagon','script':paths['Hexagon'],'variants':[{'name':'baseline','parameters':{},
            'bounds_mm':[[-4,-4*math.sqrt(3)/2,0],[4,4*math.sqrt(3)/2,3]],'volume_mm3':72*math.sqrt(3)}]},
        {'name':'renamed','script':paths['Renamed'],'variants':[
            variant('baseline',{},[100,70,47],grid=[7,5]),
            variant('resize',{'span_x':'160 mm','span_y':'100 mm'},[160,100,47],grid=[12,7])]},
        {'name':'plate','script':paths['Plate'],'variants':[
            variant('baseline',{},[20,10,3],volume_mm3=600), variant('resize',{'w':'25 mm','h':'4 mm'},[25,10,4],volume_mm3=1000)]},
        {'name':'portable','script':str(portable/'Tray.py'),'variants':[variant('baseline',{},[100,70,47],grid=[7,5])]},
        {'name':'revolve_cuts','script':paths['RevolveCuts'],'variants':[
            variant('baseline',{},[20,20,6],volume_mm3=2400-24*math.pi-36)]},
        {'name':'partial_revolve','script':paths['PartialRevolve'],'variants':[
            {'name':'baseline','parameters':{},'bounds_mm':[[-2,0,0],[0,2,3]],'volume_mm3':3*math.pi}]},
    ]
    config = directory / 'config.json'
    config.write_text(json.dumps({'evidence':str(directory/'native'), 'cases':cases},indent=2,ensure_ascii=False),encoding='utf-8')
    print(str(config))


if __name__ == '__main__':
    main()
