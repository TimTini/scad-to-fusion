// Bath sponge tray. All dimensions are millimetres.
/* [Tray - mm] */
// Outside length of the tray.
length = 100;
// Outside width of the tray.
width = 70;
// Tray body height, excluding the raised hanging ear.
height = 30;
// Wall thickness; also the thickness of the hanging ear.
wall = 3;
// Floor thickness.
floor_thickness = 3;
// Outside corner radius in plan view; inside radius = this minus wall thickness.
corner_radius = 8;

/* [Drainage - mm] */
// Drain hole diameter; hole count and layout adapt to tray size.
drain_diameter = 6;
// Centre-to-centre distance between adjacent drain holes.
drain_pitch = 12;
// Minimum distance from the outside edge to the outermost hole centres.
drain_edge_margin = 10;

/* [Wall hooks - mm] */
// Number of hanging holes; one hole uses a raised central ear.
hook_count = 1; // [1:One hole,2:Two holes]
// Diameter of the hanging holes for both options.
hook_diameter = 10;
// Centre-to-centre distance, only for the two-hole option.
hook_spacing = 60;
// Hole centre height above the tray bottom, only for the two-hole option.
hook_height = 20;

/* [Single-hole ear - mm] */
// Width of the central hanging ear, only for the one-hole option.
ear_width = 30;
// Ear height above the tray rim; the hole is automatically centred in this height.
ear_rise = 17;
// Concave fillet radius where the ear joins the tray rim.
ear_root_radius = 3;

/* [Hidden] */
$fn = 64;
eps = 0.05;
// Keep the hole centred in the exposed ear whenever its height changes.
ear_hole_height = ear_rise / 2;
drain_columns = floor((length - 2 * drain_edge_margin) / drain_pitch) + 1;
drain_rows = floor((width - 2 * drain_edge_margin) / drain_pitch) + 1;
drain_start_x = (length - (drain_columns - 1) * drain_pitch) / 2;
drain_start_y = (width - (drain_rows - 1) * drain_pitch) / 2;

assert(length > 2 * corner_radius && width > 2 * corner_radius);
assert(wall > 0 && corner_radius > wall);
assert(floor_thickness > 0 && height > floor_thickness);
assert(drain_diameter > 0 && drain_pitch >= drain_diameter + 3);
// Keep centres beyond corner arcs and at least 3 mm of floor beside each hole.
assert(drain_edge_margin >= max(corner_radius, wall + drain_diameter / 2 + 3));
assert(drain_columns > 0 && drain_rows > 0);
assert(hook_count == 1 || hook_count == 2);
assert(hook_diameter > 0);
if (hook_count == 2) {
    assert(hook_spacing > hook_diameter);
    assert((length - hook_spacing) / 2 - hook_diameter / 2 >= corner_radius + 3);
    assert(hook_height - hook_diameter / 2 >= floor_thickness + 3);
    assert(hook_height + hook_diameter / 2 <= height - 3);
} else {
    assert(ear_width >= hook_diameter + 10 && ear_width <= length - 2 * corner_radius);
    assert(ear_rise >= hook_diameter + 4);
    assert(ear_hole_height - hook_diameter / 2 >= 2);
    assert(ear_rise - ear_hole_height - hook_diameter / 2 >= 3);
    assert(ear_root_radius > 0 && ear_root_radius <= ear_rise / 2);
    assert(ear_width + 2 * ear_root_radius <= length - 2 * corner_radius);
}

module rounded_rectangle(l, w, r) {
    translate([r, r])
        offset(r = r)
            square([l - 2 * r, w - 2 * r]);
}

difference() {
    union() {
        difference() {
            linear_extrude(height = height)
                rounded_rectangle(length, width, corner_radius);
            translate([wall, wall, floor_thickness])
                linear_extrude(height = height - floor_thickness + eps)
                    rounded_rectangle(length - 2 * wall, width - 2 * wall,
                                      corner_radius - wall);
        }
        if (hook_count == 1) {
            translate([(length - ear_width) / 2, width, height - 5])
                rotate([90, 0, 0])
                    linear_extrude(height = wall)
                        rounded_rectangle(ear_width, ear_rise + 5, 5);
            // Concave quarter-circle transitions at both shoulders of the ear.
            for (side = [-1, 1])
                translate([length / 2 + side * ear_width / 2, width, height])
                    rotate([90, 0, 0])
                        linear_extrude(height = wall)
                            scale([side, 1])
                                difference() {
                                    square([ear_root_radius, ear_root_radius]);
                                    translate([ear_root_radius, ear_root_radius])
                                        circle(r = ear_root_radius);
                                }
        }
    }

    for (col = [0 : drain_columns - 1], row = [0 : drain_rows - 1])
        translate([drain_start_x + col * drain_pitch,
                   drain_start_y + row * drain_pitch, -eps])
            cylinder(d = drain_diameter, h = floor_thickness + 2 * eps);

    for (x = hook_count == 1 ? [length / 2] :
             [(length - hook_spacing) / 2, (length + hook_spacing) / 2])
        translate([x, width + eps, hook_count == 1 ? height + ear_hole_height : hook_height])
            rotate([90, 0, 0])
                cylinder(d = hook_diameter, h = wall + 2 * eps);
}
