// Reconstructed from reference/dustpan.step. Millimetres.
// Analytic profiles, not an imported/embedded reference mesh.
/* [Dimensions] */
width = 200;
depth = 200;
wall_height = 50;
thickness = 3;
rear_radius = 23;
handle_diameter = 20;
total_height = 250;
/* [Reinforcement - sand and soil trial] */
reinforce_floor = true;
reinforce_handle = true;
reinforce_walls = true;
reinforce_rim = true;
floor_rear_extra = 1.2;
floor_start = 0.1*depth;
floor_ramp = 30;
brace_thickness = 3;
brace_reach = 15;
brace_rise = 15;
wall_rib_projection = 3;
wall_rib_width = 4;
wall_rib_radius = 1;
rim_projection = 3;
rim_height = 6;
rim_start = 20;
rim_taper = 20;
/* [Fillets and front ramp] */
floor_fillet = 5;
handle_fillet = 5;
ramp_angle = 30;
ramp_radius = 100;
/* [Resolution] */
arc_steps = 48;
fillet_steps = 24;
$fn = 192;

bottom = -wall_height/2;
top = wall_height/2;
front = -depth/2;
back = depth/2;
half = width/2;
hr = handle_diameter/2;
hy = back-thickness/2;
cx = half-rear_radius;
cy = back-rear_radius;
// Tangent-circle centers follow wall/cylinder geometry.
jx = sqrt(pow(hr+handle_fillet,2)-pow(handle_fillet+thickness/2,2));
outer_angle = atan2(hy-(back+handle_fillet),-jx);
inner_angle = atan2(hy-(back-thickness-handle_fillet),-jx);
ha = outer_angle+180;
handle_angles=[for(i=[0:$fn-1]) each concat([i*360/$fn],
    [for(t=[ha,180-ha,180+ha,360-ha])
        if(t>i*360/$fn && t<(i+1)*360/$fn) t])];
function handle_arc(r,a,b) = a<b ?
    [for(t=handle_angles) if(t>=a-1e-8 && t<=b+1e-8) [r*cos(t),hy+r*sin(t)]] :
    [for(i=[len(handle_angles)-1:-1:0]) let(t=handle_angles[i])
        if(t<=a+1e-8 && t>=b-1e-8) [r*cos(t),hy+r*sin(t)]];

function arc(c,r,a,b,n=arc_steps) =
    [for(i=[0:n]) c+r*[cos(a+(b-a)*i/n),sin(a+(b-a)*i/n)]];
function mirror_reverse(p) = [for(i=[len(p)-1:-1:0]) [-p[i][0],p[i][1]]];

// Back outline includes the measured R5 concave blend into the handle.
function outer_back() = concat(
    arc([cx,cy],rear_radius,0,90),
    arc([jx,back+handle_fillet],handle_fillet,-90,outer_angle),
    handle_arc(hr,ha,180-ha),
    mirror_reverse(arc([jx,back+handle_fillet],handle_fillet,-90,outer_angle)),
    mirror_reverse(arc([cx,cy],rear_radius,0,90)));

// A cavity ring inset by d. The R5 floor blends continuously into the
// R20 rear corners, the handle, and its R5 wall junctions.
function cavity_ring(d) = let(
    r=rear_radius-thickness-d,
    jr=handle_fillet-d,
    right=concat(arc([cx,cy],r,0,90),
        arc([jx,back-thickness-handle_fillet],jr,90,inner_angle)))
    concat([[half-thickness-d,front-10]],right,
        // 0.01 mm cavity relief prevents coincident boolean facets at handle.
        handle_arc(hr+d+0.01,360-ha,180+ha),
        mirror_reverse(right),[[-half+thickness+d,front-10]]);

// Formula-generated loft for the cavity's quarter-circle bottom fillet.
// Rings preserve the concave handle outline; hull() would erase it.
module cavity() {
    angles=[for(i=[0:fillet_steps]) -90+90*i/fillet_steps];
    rings=concat([for(a=angles) cavity_ring(floor_fillet*(1-cos(a)))],
                 [cavity_ring(0)]);
    zs=concat([for(a=angles) bottom+thickness+floor_fillet+
        floor_fillet*sin(a)],[bottom+total_height+10]);
    n=len(rings[0]);
    layers=len(rings);
    pts=[for(k=[0:layers-1]) for(p=rings[k]) [p[0],p[1],zs[k]]];
    faces=concat(
        [[for(i=[0:n-1]) i]],
        [for(k=[0:layers-2]) for(i=[0:n-1])
            let(j=(i+1)%n) each
            [[k*n+i,(k+1)*n+i,(k+1)*n+j],
             [k*n+i,(k+1)*n+j,k*n+j]]],
        [[for(i=[n-1:-1:0]) (layers-1)*n+i]]);
    polyhedron(pts,faces,convexity=10);
}

module height_envelope(span=width+2) {
    // Tangent R100 arc joins the 30 degree ramp to the horizontal rim.
    ry=front+(wall_height+ramp_radius*(1/cos(ramp_angle)-1))/tan(ramp_angle);
    rz=top-ramp_radius;
    profile=concat([[front,bottom],[back+hr+10,bottom],
        [back+hr+10,top],[ry,top]],
        arc([ry,rz],ramp_radius,90,90+ramp_angle),[[front,bottom]]);
    // local 2D (y,z), extrusion axis x.
    multmatrix([[0,0,1,0],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
        linear_extrude(span,center=true) polygon(profile);
}

module floor_transition() {
    // Quintic easing has zero slope/curvature at both ends. Carry the R5 cove
    // through the same rise instead of clipping a raised cove with a plane.
    ys=concat([for(i=[0:fillet_steps]) floor_start+floor_ramp*i/fillet_steps],
        [floor_start+floor_ramp+0.5]);
    rings=[for(y=ys) let(t=min(1,(y-floor_start)/floor_ramp),
        lift=floor_rear_extra*(6*pow(t,5)-15*pow(t,4)+10*pow(t,3)),
        z=bottom+thickness+floor_fillet+lift)
        concat([[-half+thickness-0.2,bottom+thickness-0.5],
                [half-thickness+0.2,bottom+thickness-0.5],
                [half-thickness+0.2,z]],
            [for(i=[0:fillet_steps]) let(a=-90*i/fillet_steps)
                [half-thickness-floor_fillet*(1-cos(a)),z+floor_fillet*sin(a)]],
            [for(i=[0:fillet_steps]) let(a=-90+90*i/fillet_steps)
                [-half+thickness+floor_fillet*(1-cos(a)),z+floor_fillet*sin(a)]],
            [[-half+thickness-0.2,z]])];
    n=len(rings[0]);layers=len(rings);
    points=[for(k=[0:layers-1]) for(p=rings[k]) [p[0],ys[k],p[1]]];
    faces=concat([[for(i=[0:n-1]) i]],
        [for(k=[0:layers-2]) for(i=[0:n-1]) let(j=(i+1)%n) each
            [[k*n+i,(k+1)*n+i,(k+1)*n+j],
             [k*n+i,(k+1)*n+j,k*n+j]]],
        [[for(i=[n-1:-1:0]) (layers-1)*n+i]]);
    polyhedron(points,[for(f=faces) [for(i=[len(f)-1:-1:0]) f[i]]],convexity=10);
}

module floor_structure() {
    cap=thickness+floor_rear_extra+floor_fillet;
    floor_transition();
    // Constant rear pad overlaps the flat end of the transition by0.5mm.
    intersection() {
        difference() {
            // Keep pad footprint inside wall material; the base owns exterior faces.
            translate([0,0,bottom]) linear_extrude(cap) offset(delta=-thickness/2)
                polygon(concat([[half,front]],outer_back(),[[-half,front]]));
            translate([0,0,floor_rear_extra]) cavity();
        }
        translate([-half-1,floor_start+floor_ramp,bottom])
            cube([width+2,back+hr+1-floor_start-floor_ramp,cap]);
    }
}

module handle_gussets() {
    // Exterior YZ braces: supported by their full base, tapering upward.
    for(side=[-1,1]) scale([side,1,1])
        translate([hr*0.55-brace_thickness/2,0,0])
            multmatrix([[0,0,1,0],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
                linear_extrude(brace_thickness)
                    polygon([[back-0.5,bottom],[back+brace_reach,bottom],
                        [hy+hr*0.65,top+brace_rise],[back-0.5,top+brace_rise]]);
}

module wall_buttresses() {
    for(side=[-1,1]) scale([side,1,1])
        for(y=[-depth*0.05,depth*0.25]) intersection() {
            translate([0,y-wall_rib_width/2,0])
                multmatrix([[1,0,0,0],[0,0,1,0],[0,1,0,0],[0,0,0,1]])
                    linear_extrude(wall_rib_width) hull() {
                        for(p=[[half-0.5,bottom+wall_rib_radius],
                               [half+wall_rib_projection-wall_rib_radius,bottom+wall_rib_radius],
                               [half-0.5,top-wall_rib_radius]])
                            translate(p) circle(r=wall_rib_radius,$fn=48);
                    }
            height_envelope(width+2*wall_rib_projection+2);
        }
}

function rim_z(y) = let(ry=front+(wall_height+ramp_radius*(1/cos(ramp_angle)-1))/tan(ramp_angle),
    ty=ry-ramp_radius*sin(ramp_angle))
    y<ty ? bottom+(y-front)*tan(ramp_angle) :
    y<ry ? top-ramp_radius+sqrt(pow(ramp_radius,2)-pow(y-ry,2)) : top;

module outer_body() {
    // Rebuild each rear quadrant with wall and rim in one profile. This avoids
    // Boolean intersections between nearly coincident faceted round surfaces.
    difference() {
        translate([0,0,bottom]) linear_extrude(wall_height)
            polygon(concat([[half,front]],outer_back(),[[-half,front]]));
        if(reinforce_rim) for(side=[-1,1]) scale([side,1,1])
            translate([cx,cy,bottom-1])
                cube([rear_radius+rim_projection+1,rear_radius+rim_projection+1,wall_height+2]);
    }
    if(reinforce_rim) for(side=[-1,1]) scale([side,1,1]) {
        // Use the original arc coordinates, including exact tangent endpoints.
        zs=[bottom,top-rim_height*rim_projection/(rim_projection+0.5),top];
        rs=[rear_radius,rear_radius,rear_radius+rim_projection];
        rings=[for(r=rs) concat([[cx,cy]],arc([cx,cy],r,0,90))];
        n=len(rings[0]);
        pts=[for(k=[0:2]) for(p=rings[k]) [p[0],p[1],zs[k]]];
        faces=concat([[for(i=[0:n-1]) i]],
            [for(k=[0:1]) for(i=[0:n-1]) let(j=(i+1)%n) each
                [[k*n+i,(k+1)*n+i,(k+1)*n+j],
                 [k*n+i,(k+1)*n+j,k*n+j]]],
            [[for(i=[n-1:-1:0]) 2*n+i]]);
        polyhedron(pts,faces,convexity=10);
    }
}

module reinforced_rim() {
    // Straight flanges meet the integrated rear-corner wall sections.
    // Triangular underside rises6mm across3.5mm: no horizontal overhang.
    for(side=[-1,1]) scale([side,1,1]) {
        pts=[for(i=[0:arc_steps])
            let(y=front+rim_start+(cy-front-rim_start)*i/arc_steps,
                t=min(1,max(0,(y-front-rim_start)/rim_taper)),z=rim_z(y)) each
            [[half-0.5,y,z-rim_height],
             [half+rim_projection*t,y,z],[half-0.5,y,z]]];
        faces=concat([[2,1,0]],
            [for(i=[0:arc_steps-1]) for(k=[0:2]) let(j=(k+1)%3) each
                [[3*i+k,3*i+j,3*(i+1)+j],[3*i+k,3*(i+1)+j,3*(i+1)+k]]],
            [[3*arc_steps,3*arc_steps+1,3*arc_steps+2]]);
        polyhedron(pts,faces,convexity=10);
    }
    translate([-cx,0,0])
        multmatrix([[0,0,1,0],[1,0,0,0],[0,1,0,0],[0,0,0,1]])
            linear_extrude(2*cx)
                polygon([[back-0.5,top-rim_height],
                    [back+rim_projection,top],[back-0.5,top]]);
}

assert(thickness>0 && thickness<rear_radius);
assert(handle_diameter>thickness && handle_fillet>0);
assert(rear_radius>thickness+floor_fillet);
assert(floor_fillet>0 && floor_fillet<=handle_fillet);
assert(rear_radius<min(width/2,depth/2));
assert(wall_height>thickness+floor_fillet && ramp_radius>0);
assert(arc_steps>=3 && arc_steps==floor(arc_steps));
assert(fillet_steps>=3 && fillet_steps==floor(fillet_steps));
assert(total_height>=wall_height && ramp_angle>0 && ramp_angle<90);
assert(!reinforce_floor || (floor_rear_extra>0 && floor_start>0 && floor_ramp>0 &&
    floor_start+floor_ramp<cy && thickness+floor_rear_extra+floor_fillet<wall_height));
assert(!reinforce_handle || (brace_thickness>0 &&
    hr*0.55+brace_thickness/2<hr && brace_reach>hr &&
    brace_rise>0 && wall_height+brace_rise<total_height));
assert(!reinforce_walls || (wall_rib_width>0 && wall_rib_radius>0 &&
    wall_rib_projection>2*wall_rib_radius && wall_height>4*wall_rib_radius &&
    depth*0.25+wall_rib_width/2<cy));
assert(!reinforce_rim || abs(rim_z(cy)-top)<1e-7,
    "rear rim requires both corner tangencies on the flat wall top");
assert(!reinforce_rim || (rim_projection>0 && rim_height>0 &&
    rim_height<wall_height &&
    rim_height>=rim_projection+0.5 &&
    rim_start>0 && rim_taper>0 &&
    rim_start+rim_taper<depth-rear_radius));

translate([0,0,-bottom]) union() {
    difference() {
        intersection() {
            outer_body();
            height_envelope(reinforce_rim ? width+2*rim_projection+2 : width+2);
        }
        cavity();
    }
    translate([0,0,bottom]) linear_extrude(total_height)
        polygon([for(t=handle_angles) [hr*cos(t),hy+hr*sin(t)]]);
    if(reinforce_floor) floor_structure();
    if(reinforce_handle) handle_gussets();
    if(reinforce_walls) wall_buttresses();
    if(reinforce_rim) reinforced_rim();
}
