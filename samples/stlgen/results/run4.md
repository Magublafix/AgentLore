# Benchmark — Run 4

| Field | Value |
|-------|-------|
| Date | 2026-06-23 07:30 |
| Model | qwen2.5-coder:32b |
| Lore search active | yes (9 concepts) |
| Web search active | yes |
| Turn budget | 30 |
| Turns (main loop) | 18 |
| Turns (capture) | 15 |
| Turns (wrapup) | 10 |
| Task submitted | no (hit limit) |
| Input tokens | 237,475 |
| Output tokens | 11,528 |
| Total tokens | 249,003 |
| Concepts captured this run | 5 |
| Elapsed | 8586.1s |
| Tests passed | ❌ no |

## Test output

```
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl ABCDEFGHIJKLMNO -o /tmp/pytest-of-magublafix/pytest-372/test_max_length0/max.stl exited 1
E   stdout: 
E   stderr: matrix not a valid transformation matrix
_________________ TestInvocation.test_default_output_filename __________________
/tmp/lore_stlgen_run4_0dz0kpyo/tests/test_text2stl_cli.py:132: in test_default_output_filename
    text2stl("HI")
/tmp/lore_stlgen_run4_0dz0kpyo/tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HI exited 1
E   stdout: 
E   stderr: matrix not a valid transformation matrix
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:199: in test_width_scales_with_char_count
    text2stl("A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-372/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: matrix not a valid transformation matrix
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-372/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: matrix not a valid transformation matrix
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-372/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: matrix not a valid transformation matrix
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_single_char - Failed:...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_five_chars - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight - ...
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
==================== 7 failed, 2 passed, 4 errors in 30.46s ====================

```
