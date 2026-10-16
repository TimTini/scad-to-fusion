difference() {
    cube([20,20,6]);
    translate([5,5,0]) rotate_extrude()
        polygon([[0,0],[2,0],[2,8],[0,8]]);
    translate([10,10,0]) polyhedron(
        points=[[0,0,0],[6,0,0],[0,6,0],[0,0,6]],
        faces=[[0,1,2],[0,3,1],[0,2,3],[1,3,2]]);
}
