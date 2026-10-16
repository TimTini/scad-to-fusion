"""Bounded native Loft construction for recognized stacked polygon shells."""

from .planar import Region
from .planar import Scalar
from .planar_recovery import recover_polygon_curves
import math


def offset_cove_radius(plan, frame=None):
    if frame is not None:
        scales=[math.sqrt(sum(row[i]**2 for row in frame.matrix)) for i in range(3)]
        if max(scales)-min(scales)>1e-9:return None
    rings=plan['all_rings']
    tail=plan.get('tail_extrusion')
    if not tail or tail['start_index']<4: return None
    curved=rings[:tail['start_index']+1]
    first,last=curved[0],curved[-1]
    radius=last['position']-first['position']
    if radius<=0.01: return None
    directions=[((a[0]-b[0])/radius,(a[1]-b[1])/radius) for a,b in zip(first['points'],last['points'])]
    if any(abs(math.hypot(*d)-1)>1e-6 for d in directions):return None
    for ring in curved:
        z=ring['position']-last['position']
        inset=radius-math.sqrt(max(0,radius*radius-z*z))
        if any(math.dist(a,[b[0]+inset*d[0],b[1]+inset*d[1]])>1e-5
               for a,b,d in zip(ring['points'],last['points'],directions)):return None
    return radius


def translated_profile_suffix(plan):
    rings=plan['all_rings']
    start=len(rings)-1
    reference=rings[-1]['points']
    while start>0:
        points=rings[start-1]['points']
        delta=[points[0][i]-reference[0][i] for i in range(2)]
        if any(math.dist(p,[q[0]+delta[0],q[1]+delta[1]])>1e-7 for p,q in zip(points,reference)):break
        start-=1
    if not 0<start<len(rings)-2:return None
    shifts=[[r['points'][0][i]-rings[start]['points'][0][i] for i in range(2)] for r in rings[start:]]
    if sum(max(abs(s[i]) for s in shifts)>1e-7 for i in range(2))!=1:return None
    return start if prefix_law_indices(rings,start) is not None else None


def sector_profile(plan, frame=None):
    if frame is not None:
        local=section_frame(frame,plan['axis'],0)
        scales=[math.sqrt(sum(row[i]**2 for row in local.matrix)) for i in range(3)]
        if abs(scales[0]-scales[1])>1e-9:return None
    rings=plan['all_rings']
    center=rings[0]['points'][0]
    radii=[];angles=None
    for ring in rings:
        points=ring['points']
        if len(points)<6 or math.dist(points[0],center)>1e-7:return None
        radius=math.dist(points[1],center)
        if radius<=0 or any(abs(math.dist(p,center)-radius)>1e-5 for p in points[1:]):return None
        current=[math.atan2(p[1]-center[1],p[0]-center[0]) for p in points[1:]]
        if angles is not None and any(abs(math.remainder(a-b,2*math.pi))>1e-6 for a,b in zip(angles,current)):return None
        angles=current;radii.append(radius)
    steps=[math.remainder(b-a,2*math.pi) for a,b in zip(angles,angles[1:])]
    if any(s<=0 for s in steps):return None
    sweep=math.degrees(sum(steps))
    if not 0<sweep<360:return None
    profile=[[0,rings[0]['position']]]+[[r,ring['position']] for r,ring in zip(radii,rings)]+[[0,rings[-1]['position']]]
    return {'center':center,'start':math.degrees(angles[0]),'sweep':sweep,'points':profile}


def prefix_law_indices(rings,start):
    indices=[0]
    slopes=[]
    for left,right in zip(rings[:start],rings[1:start+1]):
        distance=right['position']-left['position']
        slopes.append([(b[k]-a[k])/distance for a,b in zip(left['points'],right['points']) for k in range(2)])
    for i in range(1,len(slopes)):
        if max(abs(a-b) for a,b in zip(slopes[i-1],slopes[i]))>1e-7:indices.append(i)
    indices.append(start)
    return indices if len(indices)<=5 else None


def translated_sweep(builder,plan,frame,start):
    rings=plan['all_rings'];initial=rings[start];axis=plan['axis']
    # This subset translates the profile in one of its own coordinates.
    shifts=[[r['points'][0][i]-initial['points'][0][i] for i in range(2)] for r in rings[start:]]
    moving=[i for i in range(2) if max(abs(s[i]) for s in shifts)>1e-7]
    if len(moving)!=1: return None
    coordinate=moving[0]
    path_points=[(Scalar(r['position']),Scalar(s[coordinate])) for r,s in zip(rings[start:],shifts)]
    curves=recover_polygon_curves(path_points)
    # Recovery treats the sequence as closed; discard only its closing edge.
    curves=curves[:-1]
    sketch=builder.comp.sketches.add(builder.comp.xYConstructionPlane)
    sketch.name='SCAD translated-profile path'
    sketch.is3D=True
    def point(p):
        values=[Scalar(v) for v in initial['points'][0]]
        values[coordinate]=values[coordinate]+p[1]
        world=section_frame(frame,axis,p[0]).point(values+[Scalar(0)])
        return builder.core.Point3D.create(*[v.value/10 for v in world])
    entities=[]
    for curve in curves:
        if curve['kind']=='line':entity=sketch.sketchCurves.sketchLines.addByTwoPoints(point(curve['start']),point(curve['end']))
        else:entity=sketch.sketchCurves.sketchArcs.addByThreePoints(point(curve['start']),point(curve['mid']),point(curve['end']))
        entity.isFixed=True;entities.append(entity)
    for vertex in sketch.sketchPoints:
        if not vertex.isFixed: vertex.isFixed=True
    path=builder.fusion.Path.create(builder.collection(entities),builder.fusion.ChainedCurveOptions.noChainedCurves)
    profile_sketch,profiles,_=builder.sketch_region(section_region(initial['points']),section_frame(frame,axis,initial['position']),fixed=True)
    inp=builder.comp.features.sweepFeatures.createInput(profiles.item(0),path,builder.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.orientation=builder.fusion.SweepOrientationTypes.ParallelOrientationType
    builder.stage='SCAD translated-profile Sweep'
    feature=builder.comp.features.sweepFeatures.add(inp)
    feature.name='SCAD translated-profile Sweep'
    sketch.isVisible=False;profile_sketch.isVisible=False
    indices=prefix_law_indices(rings,start)
    bodies=list(feature.bodies)
    for left,right in zip(indices,indices[1:]):
        prefix=dict(plan);prefix['sections']=[rings[left],rings[right]];prefix['tail_extrusion']=None
        prefix['all_rings']=prefix['sections']
        bodies.extend(create_layered_body(builder,prefix,frame))
    return builder.join(bodies)


def section_frame(frame, axis, position):
    bases = [[[0,0,1],[1,0,0],[0,1,0]],
             [[1,0,0],[0,0,1],[0,1,0]],
             [[1,0,0],[0,1,0],[0,0,1]]]
    matrix = [row+[position if i==axis else 0] for i,row in enumerate(bases[axis])]
    return frame.transformed({'op':'multmatrix','args':{'m':matrix+[[0,0,0,1]]}})


def section_region(points):
    return Region({'op':'polygon','args':{'points':points},'children':[]})


def create_layered_body(builder, plan, frame):
    sector=sector_profile(plan,frame)
    if sector:
        local=section_frame(frame,plan['axis'],0)
        local=local.transformed({'op':'translate','args':{'v':sector['center']+[0]}})
        local=local.transformed({'op':'rotate','args':{'a':[0,0,sector['start']]}})
        return builder.revolve({'op':'rotate_extrude','args':{'angle':sector['sweep']},
            'children':[{'op':'polygon','args':{'points':sector['points']},'children':[]}]},local)
    radius=offset_cove_radius(plan,frame)
    if radius:
        first,last=plan['all_rings'][0],plan['all_rings'][-1]
        local=section_frame(frame,plan['axis'],first['position'])
        node={'op':'linear_extrude','args':{'height':last['position']-first['position']},
              'children':[{'op':'polygon','args':{'points':last['points']},'children':[]}]}
        bodies=list(builder.extrude(node,local).bodies)
        axis=next(i for i in range(3) if abs(local.matrix[i][2])>1e-9)
        position=local.origin[axis].value/10
        edges=[edge for edge in bodies[0].edges if abs(edge.boundingBox.minPoint.asArray()[axis]-position)<1e-7
               and abs(edge.boundingBox.maxPoint.asArray()[axis]-position)<1e-7]
        inp=builder.comp.features.filletFeatures.createInput()
        # The source can collapse a concave offset arc to a point at full R.
        # Leave a declared 0.01 mm margin; mesh acceptance still gates delivery.
        inp.edgeSetInputs.addConstantRadiusEdgeSet(builder.collection(edges),builder.core.ValueInput.createByReal((radius-0.01)*math.sqrt(sum(row[0]**2 for row in frame.matrix))/10),False)
        builder.stage='SCAD recovered offset cove Fillet'
        feature=builder.comp.features.filletFeatures.add(inp)
        feature.name='SCAD recovered offset cove'
        return list(feature.bodies)
    start=translated_profile_suffix(plan)
    if start is not None:
        result=translated_sweep(builder,plan,frame,start)
        if result is not None:return result
    if plan['mode']=='extrude':
        first,last = plan['all_rings'][0],plan['all_rings'][-1]
        local = section_frame(frame,plan['axis'],first['position'])
        length = last['position']-first['position']
        if length<0: local=local.transformed({'op':'scale','args':{'v':[1,1,-1]}})
        node={'op':'linear_extrude','args':{'height':abs(length)},
              'children':[{'op':'polygon','args':{'points':first['points']},'children':[]}]}
        return list(builder.extrude(node,local).bodies)
    sections = plan['sections']
    if not 2 <= len(sections) <= 5:
        raise ValueError('Layered construction requires two to five profiles')
    profiles = []
    sketches = []
    for section in sections:
        region = section_region(section['points'])
        local = section_frame(frame,plan['axis'],section['position'])
        sketch, selected, _ = builder.sketch_region(region,local,fixed=True)
        if selected.count != 1:
            raise ValueError('Layered shell requires one closed profile per section')
        profiles.append(selected.item(0))
        sketches.append(sketch)
    inp = builder.comp.features.loftFeatures.createInput(builder.fusion.FeatureOperations.NewBodyFeatureOperation)
    inp.isSolid = True
    for profile in profiles: inp.loftSections.add(profile)
    builder.stage = 'SCAD bounded layered loft'
    feature = builder.comp.features.loftFeatures.add(inp)
    feature.name = 'SCAD bounded layered loft (regenerate from source)'
    bodies = list(feature.bodies)
    for sketch in sketches: sketch.isVisible = False
    tail = plan.get('tail_extrusion')
    if tail:
        # Preserve a constant section after the curved region as an exact prism.
        length = tail['plane_end']-tail['plane_start']
        local = section_frame(frame,plan['axis'],tail['plane_start'])
        if length<0:
            local = local.transformed({'op':'scale','args':{'v':[1,1,-1]}})
        node = {'op':'linear_extrude','args':{'height':abs(length)},
                'children':[{'op':'polygon','args':{'points':tail['points']},'children':[]}]}
        bodies = builder.join(bodies+list(builder.extrude(node,local).bodies))
    return bodies
