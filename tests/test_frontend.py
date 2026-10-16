import pathlib
import hashlib
import unittest
from ast import parse

from scad2fusion.frontend import ScadError, compile_source
from scad2fusion.model import Expr, Node
from scad2fusion.units import expression_ast


SOURCE = pathlib.Path(__file__).parent / "fixtures" / "tray.scad"
SOURCE_ELECTRIC = pathlib.Path(__file__).parent / "fixtures" / "electric-toothbrush-case.scad"


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


class FrontendTests(unittest.TestCase):
    def test_small_model_compiles_to_symbolic_geometry(self):
        program = compile_source(
            """
            width = 12;
            module plate(w) { cube([w, width, 2], center=true); }
            translate([width / 2, 0, 1]) plate(width);
            """,
            filename="small.scad",
        )
        self.assertEqual(program.source_name, "small.scad")
        self.assertEqual(program.parameters["width"].value, 12)
        self.assertEqual(program.geometry.op, "union")
        cube = next(n for n in walk(program.geometry) if n.op == "cube")
        self.assertEqual(cube.args["center"].value, True)
        self.assertEqual(cube.args["size"][0].value, 12)
        self.assertEqual(cube.args["size"][1].text, "width")
        self.assertEqual(cube.args["size"][1].deps, frozenset({"width"}))
        self.assertEqual(next(n for n in walk(program.geometry) if n.op == "translate").args["v"][0].text, "(width / 2)")

    def test_forward_reference_and_derived_parameter_keep_expression(self):
        program = compile_source(
            "height = width / 2; width = 20; cube([width, 4, height]);",
            filename="forward.scad",
        )
        self.assertEqual(program.parameters["height"].value, 10)
        self.assertEqual(program.parameters["height"].text, "(width / 2)")
        cube = next(n for n in walk(program.geometry) if n.op == "cube")
        self.assertEqual(cube.args["size"][0].text, "width")
        self.assertEqual(cube.args["size"][2].text, "height")

    def test_derived_range_formulas_keep_grouping_for_python_ast_consumers(self):
        source = (
            "length = 100; margin = 10; pitch = 12; "
            "columns = floor((length - 2 * margin) / pitch) + 1; "
            "start = (length - (columns - 1) * pitch) / 2; "
            "cube([columns, start, 1]);"
        )
        for overrides, expected_columns, expected_start in (
            ({}, 7, 14),
            ({"length": 160}, 12, 14),
            ({"length": 52, "pitch": 40}, 1, 26),
        ):
            program = compile_source(source, overrides=overrides, filename="grouping.scad")
            columns = program.parameters["columns"]
            start = program.parameters["start"]
            self.assertEqual(columns.value, expected_columns)
            self.assertEqual(start.value, expected_start)
            parse(columns.text.replace("^", "**"), mode="eval")
            parse(start.text.replace("^", "**"), mode="eval")
            expression_ast(columns.text)
            expression_ast(start.text)
            self.assertIn("(length - (2 * margin))", columns.text)
            self.assertIn("(length - ((columns - 1) * pitch))", start.text)

    def test_generation_condition_uses_selected_branch_and_marks_rebuild_parameter(self):
        program = compile_source(
            "mode = 1; first = 12; second = 24; selected = mode == 1 ? first : second; "
            "cube(selected);",
            filename="conditional.scad",
        )
        self.assertEqual(program.parameters["selected"].text, "first")
        self.assertEqual(program.parameters["selected"].deps, frozenset({"first"}))
        self.assertEqual(program.rebuild_parameters, frozenset({"mode"}))

    def test_if_condition_marks_rebuild_parameter_but_assert_does_not(self):
        program = compile_source(
            "mode = true; assert(mode); if (mode) cube(1);",
            filename="if.scad",
        )
        self.assertEqual(program.rebuild_parameters, frozenset({"mode"}))

    def test_override_updates_base_value_but_preserves_symbolic_references(self):
        program = compile_source(
            "width = 20; height = width / 2; cube([width, 1, height]);",
            overrides={"width": 30},
        )
        self.assertEqual(program.parameters["width"].value, 30)
        self.assertEqual(program.parameters["height"].value, 15)
        self.assertEqual(
            next(n for n in walk(program.geometry) if n.op == "cube").args["size"][0].text,
            "width",
        )

    def test_cartesian_for_retains_range_metadata_and_expands_children(self):
        program = compile_source(
            "for (x = [0:2], y = [-1, 1]) translate([x, y, 0]) cube(1);",
            filename="loop.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertEqual([b["name"] for b in loop.args["bindings"]], ["x", "y"])
        self.assertEqual(loop.args["bindings"][0]["start"].value, 0)
        self.assertEqual(loop.args["bindings"][0]["step"].value, 1)
        self.assertEqual(loop.args["bindings"][0]["end"].value, 2)
        self.assertEqual([v.value for v in loop.args["bindings"][1]["values"]], [-1, 1])
        self.assertEqual(len(loop.children), 6)
        translations = [n for n in walk(loop) if n.op == "translate"]
        self.assertEqual([t.args["v"][0].value for t in translations], [0, 0, 1, 1, 2, 2])

    def test_list_for_binding_preserves_symbolic_element_in_children(self):
        program = compile_source(
            "L = 100; for (x = [L / 2]) "
            "translate([x, 0, 0]) cylinder(h=3, r=1);",
            filename="symbolic-list.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        translate = next(n for n in walk(loop.children[0]) if n.op == "translate")
        self.assertEqual(translate.args["v"][0].value, 50)
        self.assertEqual(translate.args["v"][0].text, "(L / 2)")
        self.assertEqual(translate.args["v"][0].deps, frozenset({"L"}))

    def test_list_for_binding_preserves_second_symbolic_element_in_probe(self):
        program = compile_source(
            "L = 100; for (x = [L / 2, (L + 20) / 2]) "
            "translate([x, 0, 0]) cylinder(h=3, r=1);",
            filename="symbolic-list-two.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        expanded = [n for n in walk(loop) if n.op == "translate"]
        self.assertEqual([item.args["v"][0].text for item in expanded], ["(L / 2)", "((L + 20) / 2)"])
        probe = next(n for n in walk(loop.args["probes"][0]) if n.op == "translate")
        self.assertEqual(probe.args["v"][0].text, "((L + 20) / 2)")
        self.assertEqual(probe.args["v"][0].deps, frozenset({"L"}))

    def test_for_template_preserves_non_linear_loop_placeholder(self):
        program = compile_source(
            "for (x = [0:2]) translate([x * x, 0, 0]) cube(1);",
            filename="template-nonlinear.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        template = loop.args["template"]
        translate = next(n for n in walk(template) if n.op == "translate")
        self.assertEqual(translate.args["v"][0].text, "(__loop_x * __loop_x)")
        self.assertEqual(translate.args["v"][0].deps, frozenset())
        self.assertTrue(loop.args["pattern_safe"])
        self.assertEqual([n.args["v"][0].value for n in loop.children], [0, 1, 4])

    def test_for_template_preserves_affine_global_expression(self):
        program = compile_source(
            "pitch = 12; for (x = [0:2]) "
            "translate([5 + x * pitch, 0, 0]) cube(1);",
            filename="template-affine.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        template = loop.args["template"]
        translate = next(n for n in walk(template) if n.op == "translate")
        self.assertEqual(translate.args["v"][0].text, "(5 + (__loop_x * pitch))")
        self.assertEqual(translate.args["v"][0].deps, frozenset({"pitch"}))
        self.assertTrue(loop.args["pattern_safe"])

    def test_for_template_marks_loop_dependent_branch_unsafe(self):
        program = compile_source(
            "for (x = [0:2]) if (x > 0) cube(1);",
            filename="template-branch.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertIsNotNone(loop.args["template"])
        self.assertFalse(loop.args["pattern_safe"])

    def test_for_template_marks_loop_dependent_ternary_unsafe(self):
        program = compile_source(
            "for (x = [0:2]) translate([x > 0 ? x : 0, 0, 0]) cube(1);",
            filename="template-ternary.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertFalse(loop.args["pattern_safe"])

    def test_for_template_marks_local_loop_dependent_ternary_unsafe(self):
        program = compile_source(
            "for (x = [0:2]) { y = x; translate([y > 0 ? y : 0, 0, 0]) cube(1); }",
            filename="template-local-ternary.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertFalse(loop.args["pattern_safe"])

    def test_unsafe_loop_does_not_execute_hypothetical_probe(self):
        program = compile_source(
            "for (x = [0:0]) { assert(x == 0); cube(1); }",
            filename="unsafe-probe.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertFalse(loop.args["pattern_safe"])
        self.assertEqual(loop.args["probes"], [])

    def test_recursive_module_is_rejected_with_source_location(self):
        with self.assertRaisesRegex(ScadError, r"recursive.scad:1.*recursive module"):
            compile_source("module recur() { recur(); } recur();", filename="recursive.scad")

    def test_loop_expansion_limit_counts_emitted_nodes_once(self):
        program = compile_source("for (x = [0:447]) cube(1);", filename="large-loop.scad")
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertEqual(len(loop.children), 448)

    def test_override_type_must_match_base_binding(self):
        with self.assertRaisesRegex(ScadError, r"numeric.scad:1.*type"):
            compile_source("width = 20; cube(width);", overrides={"width": True}, filename="numeric.scad")
        with self.assertRaisesRegex(ScadError, r"bool.scad:1.*type"):
            compile_source("enabled = true; if (enabled) cube(1);", overrides={"enabled": 1}, filename="bool.scad")

    def test_invalid_numeric_operations_have_source_errors(self):
        with self.assertRaisesRegex(ScadError, r"power.scad:1.*power"):
            compile_source("cube(0 ^ -1);", filename="power.scad")
        with self.assertRaisesRegex(ScadError, r"huge-power.scad:1.*power"):
            compile_source("cube(10 ^ 10001);", filename="huge-power.scad")
        with self.assertRaisesRegex(ScadError, r"finite.scad:1.*finite"):
            compile_source("x = 1e309; cube(x);", filename="finite.scad")

    def test_excessive_source_nesting_has_a_source_error(self):
        source = "x = " + ("(" * 500) + "1" + (")" * 500) + "; cube(x);"
        with self.assertRaisesRegex(ScadError, r"deep\.scad:1.*nesting"):
            compile_source(source, filename="deep.scad")

    def test_one_by_one_for_has_one_hypothetical_probe_per_binding(self):
        program = compile_source(
            "pitch = 12; for (x = [0:0], y = [0:0]) "
            "translate([x * pitch, y * pitch, 0]) cube(1);",
            filename="one-by-one.scad",
        )
        loop = next(n for n in walk(program.geometry) if n.op == "for")
        self.assertEqual(len(loop.children), 1)
        self.assertEqual(len(loop.args["probes"]), 2)
        self.assertEqual(loop.args["probes"][0].op, loop.children[0].op)
        self.assertEqual(loop.args["probes"][1].op, loop.children[0].op)
        first_v = loop.args["probes"][0].args["v"]
        second_v = loop.args["probes"][1].args["v"]
        self.assertEqual([item.value for item in first_v], [12, 0, 0])
        self.assertEqual([item.value for item in second_v], [0, 12, 0])
        self.assertEqual(first_v[0].deps, frozenset({"pitch"}))
        self.assertEqual(second_v[1].text, "(1 * pitch)")

    def test_empty_for_emits_no_geometry_or_probes(self):
        program = compile_source("for (x = []) cube(1);", filename="empty-loop.scad")
        self.assertFalse(any(node.op == "for" for node in walk(program.geometry)))
        self.assertEqual(program.geometry.children, [])

    def test_if_and_assert_use_evaluated_values(self):
        program = compile_source(
            "enabled = true; assert(enabled); if (enabled) sphere(r=2); else cube(1);",
            filename="condition.scad",
        )
        self.assertTrue(any(node.op == "sphere" for node in walk(program.geometry)))
        self.assertFalse(any(node.op == "cube" for node in walk(program.geometry)))
        with self.assertRaisesRegex(ScadError, r"bad\.scad:1.*assert"):
            compile_source("assert(false, \"bad size\"); cube(1);", filename="bad.scad")

    def test_tray_baseline_and_hook_override_compile(self):
        source = SOURCE.read_text(encoding="utf-8")
        baseline = compile_source(source, filename=str(SOURCE))
        two_hooks = compile_source(source, overrides={"hook_count": 2}, filename=str(SOURCE))
        self.assertIn("length", baseline.parameters)
        self.assertEqual(baseline.parameters["hook_count"].value, 1)
        self.assertEqual(two_hooks.parameters["hook_count"].value, 2)
        self.assertGreaterEqual(sum(n.op == "cylinder" for n in walk(baseline.geometry)), 1)
        self.assertGreaterEqual(sum(n.op == "cylinder" for n in walk(two_hooks.geometry)), 2)

    def test_renamed_module_and_variables_are_not_fixture_special_cases(self):
        program = compile_source(
            "span = 6; module rounded(a) { offset(r=1) square([a, span]); } rounded(span);",
            filename="renamed.scad",
        )
        offset = next(n for n in walk(program.geometry) if n.op == "offset")
        self.assertEqual(offset.args["r"].value, 1)
        square = next(n for n in walk(program.geometry) if n.op == "square")
        self.assertEqual(square.args["size"][0].text, "span")

    def test_vectors_can_be_nested_lists(self):
        program = compile_source("scale([[1, 0], [0, 1]]) cube(1);")
        matrix = program.geometry.children[0].args["v"]
        self.assertEqual(matrix[1][0].value, 0)

    def test_electric_case_fixture_hash_and_compile(self):
        source = SOURCE_ELECTRIC.read_bytes()
        self.assertEqual(
            hashlib.sha256(source).hexdigest(),
            "e32750b76ff4c8620786dfb8463b2d917a5bd6aad8b2ca1f9b32c61d5207fca4",
        )
        program = compile_source(source.decode("utf-8"), filename=str(SOURCE_ELECTRIC))
        self.assertNotIn("output_part", program.parameters)
        self.assertTrue(any(node.op == "polyhedron" for node in walk(program.geometry)))

    def test_functions_let_comprehension_indexing_and_vector_arithmetic(self):
        program = compile_source(
            "function points(n) = let(step=2) [for (i=[0:n-1]) [i * step, i] ]; "
            "p = points(3); translate(p[1] + [1, 2]) cube(1);",
            filename="expressions.scad",
        )
        translate = next(node for node in walk(program.geometry) if node.op == "translate")
        self.assertEqual([item.value for item in translate.args["v"]], [3, 3])

    def test_builtin_concat_norm_and_str_and_string_override(self):
        program = compile_source(
            'label = "layout"; a = concat([[3, 4]], [[0, 0]]); '
            'n = norm(a[0]); s = str(label, "-", n); cube([n, len(a), 1]);',
            overrides={"label": "body"},
            filename="builtins.scad",
        )
        self.assertNotIn("label", program.parameters)
        self.assertNotIn("s", program.parameters)
        cube = next(node for node in walk(program.geometry) if node.op == "cube")
        self.assertEqual([item.value for item in cube.args["size"]], [5, 2, 1])

    def test_len_of_symbolic_array_is_literal_with_rebuild_dependency(self):
        program = compile_source(
            "width = 4; values = [width, 2]; count = len(values); cube([count, 1, 1]);",
            filename="len-array.scad",
        )
        cube = next(node for node in walk(program.geometry) if node.op == "cube")
        self.assertEqual(cube.args["size"][0].value, 2)
        self.assertEqual(program.parameters["count"].text, "2")
        self.assertEqual(program.rebuild_parameters, frozenset({"width"}))

    def test_array_override_and_polygon_rotate_extrude_polyhedron_ir(self):
        program = compile_source(
            "rings = [[2, 3, 0]]; translate([rings[0][0], 0, 0]) cube(1); "
            "polygon(points=[[0,0],[1,0],[0,1]], convexity=3); "
            "rotate_extrude($fn=12, convexity=4) polygon([[0,0],[1,0],[1,1]]); "
            "polyhedron(points=[[0,0,0],[1,0,0],[0,1,0]], faces=[[0,1,2]], convexity=5);",
            overrides={"rings": [[4, 6, 10]]},
            filename="new-primitives.scad",
        )
        translate = next(node for node in walk(program.geometry) if node.op == "translate")
        self.assertEqual(translate.args["v"][0].value, 4)
        polygon = next(node for node in walk(program.geometry) if node.op == "polygon")
        self.assertEqual(polygon.args["points"][1][0].value, 1)
        rotate = next(node for node in walk(program.geometry) if node.op == "rotate_extrude")
        self.assertEqual(rotate.args["fn"].value, 12)
        polyhedron = next(node for node in walk(program.geometry) if node.op == "polyhedron")
        self.assertEqual(polyhedron.args["rebuild_dependencies"], [])
        self.assertEqual(polyhedron.args["points"][1][0], 1)
        self.assertEqual(polyhedron.args["coordinate_expressions"][0][0].value, 0)
        self.assertEqual(polyhedron.args["coordinate_expressions"][0][0].text, "0")

    def test_dependent_cartesian_loop_is_not_pattern_safe(self):
        program = compile_source(
            "for (i=[0:1], j=[0:i]) translate([i,j,0]) cube(1);",
            filename="dependent-loop.scad",
        )
        loop = next(node for node in walk(program.geometry) if node.op == "for")
        self.assertEqual(len(loop.children), 3)
        self.assertFalse(loop.args["pattern_safe"])

    def test_comprehension_branch_inside_loop_is_not_pattern_safe(self):
        program = compile_source(
            "for (i=[0:2]) { vals=[for (j=[0:0]) i==1 ? 10 : 0]; "
            "translate([vals[0],0,0]) cube(1); }",
            filename="comprehension-branch.scad",
        )
        loop = next(node for node in walk(program.geometry) if node.op == "for")
        self.assertFalse(loop.args["pattern_safe"])

    def test_override_base_kind_must_match(self):
        with self.assertRaisesRegex(ScadError, r"label.*type does not match"):
            compile_source('label="layout"; cube(1);', overrides={"label": ["body"]}, filename="kind.scad")
        with self.assertRaisesRegex(ScadError, r"rings.*type does not match"):
            compile_source("rings=[[1,2]]; cube(1);", overrides={"rings": "body"}, filename="kind.scad")

    def test_function_derived_override_is_rejected(self):
        with self.assertRaisesRegex(ScadError, r"derived.*function call"):
            compile_source(
                "width=2; function twice()=width*2; derived=twice(); cube(derived);",
                overrides={"derived": 3},
                filename="function-derived.scad",
            )

    def test_norm_overflow_has_source_error(self):
        with self.assertRaisesRegex(ScadError, r"norm-overflow.scad:1.*finite"):
            compile_source("n=norm([1e308,1e308,1e308,1e308]); cube(n);", filename="norm-overflow.scad")

    def test_polygon_paths_are_rejected_until_supported(self):
        with self.assertRaisesRegex(ScadError, r"paths.*unsupported"):
            compile_source("polygon(points=[[0,0],[1,0],[0,1]], paths=[[0,1,2]]);", filename="paths.scad")

    def test_mixed_type_comparison_has_source_error(self):
        with self.assertRaisesRegex(ScadError, r"mixed.scad:1.*comparison"):
            compile_source("a='x'; cube(a < 1 ? 1 : 2);", filename="mixed.scad")

    def test_polyhedron_triangles_are_rejected_until_supported(self):
        with self.assertRaisesRegex(ScadError, r"triangles.*unsupported"):
            compile_source(
                "polyhedron(points=[[0,0,0],[1,0,0],[0,1,0]], triangles=[[0,1,2]]);",
                filename="triangles.scad",
            )

    def test_polyhedron_coordinate_samples_cover_middle_dependencies(self):
        program = compile_source(
            "x=3; y=4; polyhedron(points=[[0,0,0],[x,0,0],[0,y,0],[0,0,1]], faces=[[0,1,2],[0,2,3]]);",
            filename="samples.scad",
        )
        polyhedron = next(node for node in walk(program.geometry) if node.op == "polyhedron")
        texts = {item.text for point in polyhedron.args["coordinate_expressions"] for item in point}
        self.assertIn("x", texts)
        self.assertIn("y", texts)

    def test_polyhedron_coordinate_samples_cover_distinct_expression_shapes(self):
        program = compile_source(
            "x=3; polyhedron(points=[[x,0,0],[x*x,1,0],[0,0,1]], faces=[[0,1,2]]);",
            filename="sample-shapes.scad",
        )
        polyhedron = next(node for node in walk(program.geometry) if node.op == "polyhedron")
        texts = {item.text for point in polyhedron.args["coordinate_expressions"] for item in point}
        self.assertIn("x", texts)
        self.assertIn("(x * x)", texts)

    def test_comprehension_range_binding_marks_rebuild_dependency(self):
        program = compile_source(
            "n=4; polygon(points=[for (i=[0:n]) [i, i]]);",
            filename="comprehension-rebuild.scad",
        )
        self.assertIn("n", program.rebuild_parameters)

    def test_geometry_loop_count_is_left_to_runtime_policy(self):
        program = compile_source(
            "n=2; for (i=[0:n]) translate([i,0,0]) cube(1);",
            filename="geometry-loop-policy.scad",
        )
        self.assertNotIn("n", program.rebuild_parameters)

    def test_nested_comprehensions_share_expansion_budget(self):
        with self.assertRaisesRegex(ScadError, r"expansion limit"):
            compile_source(
                "a=[for (i=[0:9999]) [for (j=[0:9999]) i+j]]; cube(len(a));",
                filename="nested-limit.scad",
            )

    def test_unknown_argument_and_unsupported_construct_have_location(self):
        with self.assertRaisesRegex(ScadError, r"args\.scad:1.*unknown argument"):
            compile_source("cube(size=1, nope=2);", filename="args.scad")
        with self.assertRaisesRegex(ScadError, r"poly\.scad:1.*polyhedron"):
            compile_source("polyhedron(points=[]);", filename="poly.scad")

    def test_invalid_override_and_cycle_are_rejected(self):
        with self.assertRaisesRegex(ScadError, r"unknown override"):
            compile_source("a = 1; cube(a);", overrides={"missing": 2})
        with self.assertRaisesRegex(ScadError, r"cycle"):
            compile_source("a = b; b = a; cube(1);", filename="cycle.scad")


if __name__ == "__main__":
    unittest.main()
