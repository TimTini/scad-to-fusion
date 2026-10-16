/*
  Electric toothbrush case: fully parametric reconstruction, millimetres.
  No STL imports or external libraries. Sized for a 35 mm x 270 mm envelope.
  Default output is both parts standing on the print bed (Z=0).
  Reconstructed threads are a matching pair; mixing with old parts is untested.
*/

/* [Common settings - mm] */
// Select the part or inspection view to display/export.
output_part = "layout"; // [layout,body,cap,assembled,section,bottom_detail]
// Outside diameter of body and cap. Body bore = this minus 2 * wall_thickness.
outside_diameter = 51.4;
// Overall body height including the neck. Height changes also need advanced shoulder/thread positions.
body_height = 213.6;
// Overall cap height. Height changes also need advanced cap_thread_z.
cap_height = 85.2;
// Main body wall; changing it also changes the shared body/neck bore.
wall_thickness = 4.5;
bottom_thickness = 2.6;
// Outer bottom fillet radius, shared by body and cap.
outside_bottom_radius = 3.6;
// Inner bottom fillet radius, shared by body and cap.
inside_bottom_radius = 2.8;
// Body bottom drainage only; no side holes.
bottom_drains_enabled = true;
// Diameter of all bottom holes; default 19 holes.
bottom_drain_diameter = 3;
// Radial thread clearance; the diameter gap is twice this value.
thread_clearance = 0.2;

/* [Advanced settings] */
// Neck position and edge fillets. Keep shoulder and thread heights coordinated.
shoulder_height = 200;
shoulder_radius = 0.6;
neck_root_diameter = 46;
neck_lip_radius = 0.8;
mouth_inside_radius = 0.3;
cap_lip_radius = 0.35;
cap_entry_radius = 0.7;
// Matching thread pair: edit body and cap together.
thread_pitch = 4.68;
thread_radius = 0.9;
thread_embed = 0.1;
body_thread_z = 202.45;
body_thread_turns = 2;
cap_thread_z = 71.2;
cap_thread_turns = 2.5;
cap_thread_phase = 90;
thread_end_taper = 45;
// Bottom hole layout [radius, count, phase]; one center hole is always added.
bottom_drain_rings = [[7,6,0],[14,12,15]];
// Mesh resolution. More segments increase export size and render time.
radial_segments = 240;
fillet_segments = 16;
thread_segments_per_turn = 240;
thread_profile_segments = 24;
drain_segments = 48;

/* [Hidden] */
outer_r = outside_diameter/2;
body_inner_r = outer_r-wall_thickness;
neck_r = neck_root_diameter/2;
// One bore through the body and neck; no internal shoulder.
neck_inner_r = body_inner_r;
male_thread_center = neck_r-thread_embed;
male_thread_crest = male_thread_center+thread_radius;
cap_inner_r = male_thread_crest+thread_clearance;
female_thread_center = cap_inner_r+thread_embed;
assembly_top = shoulder_height+cap_height;
// Invert the cap for assembly. Set its phase half a pitch between male ridges.
assembly_rotation = ((assembly_top-(cap_thread_z-thread_pitch*cap_thread_phase/360)
    -(body_thread_z+thread_pitch/2))/thread_pitch*360)%360;
eps = 0.02;

assert(outside_diameter>0 && body_height>shoulder_height && cap_height>0);
assert(wall_thickness>0 && bottom_thickness>0);
assert(outside_bottom_radius>0 && outside_bottom_radius<outer_r);
assert(inside_bottom_radius>0 && inside_bottom_radius<body_inner_r);
assert(neck_inner_r>0 && neck_r>neck_inner_r);
assert(shoulder_radius>0 && outer_r-neck_r>2*shoulder_radius);
assert(neck_r-body_inner_r>=1.8-0.0001, "Neck wall must be at least 1.8 mm");
assert(neck_r-neck_lip_radius>neck_inner_r+mouth_inside_radius);
assert(thread_pitch>4*thread_radius && thread_embed>0 && thread_embed<thread_radius);
assert(thread_clearance>0 && thread_clearance<thread_radius);
assert(cap_inner_r>body_inner_r && outer_r-cap_inner_r>cap_lip_radius+cap_entry_radius);
assert(body_thread_z-thread_radius>shoulder_height+shoulder_radius);
assert(body_thread_z+thread_pitch*body_thread_turns+thread_radius<body_height);
assert(cap_thread_z-thread_radius>bottom_thickness+inside_bottom_radius);
assert(cap_thread_z+thread_pitch*cap_thread_turns+thread_radius<cap_height-cap_entry_radius);
assert(thread_end_taper>0 && thread_end_taper<min(body_thread_turns,cap_thread_turns)*180);
function bottom_centers() = concat([[0,0]],
    [for(ring=bottom_drain_rings) for(i=[0:ring[1]-1])
        [ring[0]*cos(ring[2]+i*360/ring[1]),ring[0]*sin(ring[2]+i*360/ring[1])]]);
if(bottom_drains_enabled) {
    assert(bottom_drain_diameter>0);
    for(ring=bottom_drain_rings) {
        assert(ring[0]>0 && ring[1]>=3 && ring[1]==floor(ring[1]));
        assert(body_inner_r-inside_bottom_radius-ring[0]-bottom_drain_diameter/2>=2.5,
               "Bottom holes need at least 2.5 mm to the inner fillet");
    }
    centers=bottom_centers();
    for(i=[0:len(centers)-2],j=[i+1:len(centers)-1])
        assert(norm(centers[i]-centers[j])-bottom_drain_diameter>=3,
               "Bottom holes need at least 3 mm material between them");
}
assert(radial_segments>=48 && fillet_segments>=4 && thread_segments_per_turn>=48);
assert(thread_profile_segments>=12 && drain_segments>=16);

function arc(center,r,start,end) =
    let(n=max(2,ceil(abs(end-start)/90*fillet_segments)))
    [for(i=[0:n]) let(a=start+(end-start)*i/n)
        [center[0]+r*cos(a),center[1]+r*sin(a)]];

// Ascending outer contour, counterclockwise quarter circle at the closed end.
function outer_bottom() = arc([outer_r-outside_bottom_radius,outside_bottom_radius],
                              outside_bottom_radius,-90,0);

// Descending inner contour, tangent to the cylindrical wall and the flat floor.
function inner_bottom(r) = arc([r-inside_bottom_radius,bottom_thickness+inside_bottom_radius],
                              inside_bottom_radius,0,-90);

function body_profile() =
    concat([[0,0]],outer_bottom(),
        arc([outer_r-shoulder_radius,shoulder_height-shoulder_radius],shoulder_radius,0,90),
        arc([neck_r+shoulder_radius,shoulder_height+shoulder_radius],shoulder_radius,270,180),
        arc([neck_r-neck_lip_radius,body_height-neck_lip_radius],neck_lip_radius,0,90),
        arc([neck_inner_r+mouth_inside_radius,body_height-mouth_inside_radius],mouth_inside_radius,90,180),
        inner_bottom(body_inner_r),[[0,bottom_thickness]]);

function cap_profile() = concat([[0,0]],outer_bottom(),
    arc([outer_r-cap_lip_radius,cap_height-cap_lip_radius],cap_lip_radius,0,90),
    arc([cap_inner_r+cap_entry_radius,cap_height-cap_entry_radius],cap_entry_radius,90,180),
    inner_bottom(cap_inner_r),[[0,bottom_thickness]]);

// A sweep through radial/vertical circles produces a genuinely round helical
// ridge. Faded ends lie inside the supporting wall, so no exposed end disks.
module round_thread(center_r,z_start,turns,phase=0) {
    steps=ceil(turns*thread_segments_per_turn);
    sides=thread_profile_segments;
    total_angle=360*turns;
    points=[for(i=[0:steps],j=[0:sides-1])
        let(t=total_angle*i/steps,
            a=t+phase,
            fade=min(1,t/thread_end_taper,(total_angle-t)/thread_end_taper),
            r=max(thread_embed/4,thread_radius*fade),
            b=360*j/sides)
        [(center_r+r*cos(b))*cos(a),
         (center_r+r*cos(b))*sin(a),
         z_start+thread_pitch*t/360+r*sin(b)]];
    faces=concat(
        [for(i=[0:steps-1],j=[0:sides-1])
            [i*sides+j,(i+1)*sides+j,(i+1)*sides+(j+1)%sides]],
        [for(i=[0:steps-1],j=[0:sides-1])
            [i*sides+j,(i+1)*sides+(j+1)%sides,i*sides+(j+1)%sides]],
        [[for(j=[0:sides-1]) j]],
        [[for(j=[sides-1:-1:0]) steps*sides+j]]);
    // OpenSCAD polyhedron faces wind clockwise as seen from outside.
    polyhedron(points=points,
               faces=[for(face=faces) [for(k=[len(face)-1:-1:0]) face[k]]],convexity=12);
}

module body() {
    difference() {
        union() {
            rotate_extrude($fn=radial_segments,convexity=12) polygon(body_profile());
            round_thread(male_thread_center,body_thread_z,body_thread_turns);
        }
        if(bottom_drains_enabled)
            for(center=bottom_centers())
                translate([center[0],center[1],-eps])
                    cylinder(h=bottom_thickness+2*eps,d=bottom_drain_diameter,$fn=drain_segments);
    }
}

module cap() {
    union() {
        rotate_extrude($fn=radial_segments,convexity=12) polygon(cap_profile());
        round_thread(female_thread_center,cap_thread_z,cap_thread_turns,cap_thread_phase);
    }
}

module assembled() {
    body();
    translate([0,0,assembly_top]) rotate([0,0,assembly_rotation]) rotate([180,0,0]) cap();
}

if(output_part=="body") body();
else if(output_part=="cap") cap();
else if(output_part=="layout") {
    body();
    translate([outside_diameter+12,0,0]) cap();
}
else if(output_part=="assembled") assembled();
else if(output_part=="section") intersection() {
    assembled();
    translate([-outer_r-1,0,-eps]) cube([outside_diameter+2,outer_r+1,assembly_top+2*eps]);
}
else if(output_part=="bottom_detail") intersection() {
    body();
    translate([-outer_r-1,-outer_r-1,-eps])
        cube([outside_diameter+2,outside_diameter+2,bottom_thickness+inside_bottom_radius+4+eps]);
}
else assert(false,str("Unknown output_part: ",output_part));
