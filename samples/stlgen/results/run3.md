# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-06-27 08:14 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (15 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (capture) | 15 |
| Turns (wrapup) | 0 |
| Task submitted | no (hit limit) |
| Input tokens | 49,266 |
| Output tokens | 22,476 |
| Total tokens | 71,742 |
| Concepts captured this run | 2 |
| Elapsed | 2059.9s |
| Tests passed | ❌ no |

## Test output

```
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl ABCDEFGHIJKLMNO -o /tmp/pytest-of-magublafix/pytest-650/test_max_length0/max.stl exited 1
E   stdout: 
E   stderr: Error: Could not create mesh from text
_________________ TestInvocation.test_default_output_filename __________________
/tmp/lore_stlgen_run3_yn72sm65/tests/test_text2stl_cli.py:132: in test_default_output_filename
    text2stl("HI")
/tmp/lore_stlgen_run3_yn72sm65/tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HI exited 1
E   stdout: 
E   stderr: Error: Could not create mesh from text
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:199: in test_width_scales_with_char_count
    text2stl("A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-650/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: Error: Could not create mesh from text
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-650/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Error: Could not create mesh from text
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-650/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Error: Could not create mesh from text
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
==================== 7 failed, 2 passed, 4 errors in 19.28s ====================

```
