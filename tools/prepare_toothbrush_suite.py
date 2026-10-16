"""Prepare source-driven toothbrush native cases and fresh OpenSCAD references."""
import argparse
import json
from pathlib import Path
import subprocess

import trimesh
from scad2fusion.generator import generate_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--openscad',type=Path,required=True)
    args = parser.parse_args()
    source,directory = args.source.resolve(),args.directory.resolve()
    directory.mkdir(parents=True,exist_ok=False)
    cases = []
    configurations = [
        ('layout','HopBanChaiDien',{}),
        ('body_custom','ToothbrushBody',{'output_part':'body','bottom_drain_rings':[[7,6,0]],
            'body_thread_turns':1.5,'thread_segments_per_turn':64,'thread_profile_segments':12}),
        ('assembled','ToothbrushAssembled',{'output_part':'assembled'}),
    ]
    for tag,name,overrides in configurations:
        package = directory/'packages'/name
        generate_package(source,package,overrides)
        reference = directory/(tag+'-reference.stl')
        command = [str(args.openscad.resolve()),'--backend','Manifold','-o',str(reference)]
        for key,value in overrides.items(): command.extend(['-D',key+'='+json.dumps(value)])
        subprocess.run(command+[str(source)],check=True)
        mesh = trimesh.load_mesh(reference,process=True)
        if not mesh.is_watertight: raise ValueError('Reference is not closed: '+tag)
        variants = [{'name':'baseline','parameters':{},'bounds_mm':mesh.bounds.tolist(),
                     'body_count':len(mesh.split())}]
        if tag == 'layout':
            variants.append({'name':'height_resize','parameters':{'body_height':'219.6 mm','cap_height':'90.2 mm'},
                'bounds_mm':[[-25.7,-25.7,0],[89.1,25.7,219.6]],'body_count':2})
            resized = directory/'layout-height_resize-reference.stl'
            subprocess.run([str(args.openscad.resolve()),'--backend','Manifold','-D','body_height=219.6',
                '-D','cap_height=90.2','-o',str(resized),str(source)],check=True)
            round_values = {'outside_bottom_radius':4.2, 'inside_bottom_radius':2.2,
                            'neck_lip_radius':.9, 'mouth_inside_radius':.35,
                            'cap_lip_radius':.4, 'cap_entry_radius':.8}
            variants.append({'name':'round_resize',
                'parameters':{key:str(value)+' mm' for key,value in round_values.items()},
                'bounds_mm':mesh.bounds.tolist(),'body_count':2})
            command = [str(args.openscad.resolve()),'--backend','Manifold',
                       '-o',str(directory/'layout-round_resize-reference.stl')]
            for key,value in round_values.items():
                command.extend(['-D',key+'='+str(value)])
            subprocess.run(command+[str(source)],check=True)
        cases.append({'name':tag,'script':str(package/(name+'.py')),'variants':variants})
    config = {'evidence':str(directory/'native'),'cases':cases}
    (directory/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print(directory/'config.json')


if __name__ == '__main__': main()
