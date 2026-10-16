difference() {
    linear_extrude(2) square(10);
    difference() {
        linear_extrude(3) square(2);
        linear_extrude(3) square(1);
    }
}
