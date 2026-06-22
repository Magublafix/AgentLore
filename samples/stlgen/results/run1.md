# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-06-22 16:25 |
| Model | qwen2.5-coder:32b |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 30 |
| Turns (main loop) | 30 |
| Turns (capture) | 0 |
| Turns (wrapup) | 0 |
| Task submitted | no (hit limit) |
| Input tokens | 317,496 |
| Output tokens | 9,421 |
| Total tokens | 326,917 |
| Concepts captured this run | 0 |
| Elapsed | 9663.0s |
| Tests passed | ❌ no |

## Test output

```
2stl_cli.py:200: in test_width_scales_with_char_count
    text2stl("HELLO", "-o", str(out5))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-354/test_width_scales_with_char_co0/hello.stl exited 1
E   stdout: 
E   stderr: No vertices generated for character: H
E   No vertices generated for character: E
E   No vertices generated for character: L
E   No vertices generated for character: L
E   No vertices generated for character: O
E   Error converting text to STL: could not broadcast input array from shape (0,3) into shape (0,3,3)
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-354/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: No vertices generated for character: H
E   No vertices generated for character: E
E   No vertices generated for character: L
E   No vertices generated for character: L
E   No vertices generated for character: O
E   Error converting text to STL: could not broadcast input array from shape (0,3) into shape (0,3,3)
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-354/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: No vertices generated for character: H
E   No vertices generated for character: E
E   No vertices generated for character: L
E   No vertices generated for character: L
E   No vertices generated for character: O
E   Error converting text to STL: could not broadcast input array from shape (0,3) into shape (0,3,3)
=========================== short test summary info ============================
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
==================== 6 failed, 3 passed, 4 errors in 34.53s ====================

```
