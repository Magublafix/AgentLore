# Benchmark — Run 6

| Field | Value |
|-------|-------|
| Date | 2026-07-09 04:06 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (15 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 38,379 |
| Output tokens | 26,136 |
| Total tokens | 64,515 |
| Concepts captured this run | 1 |
| Elapsed | 3089.2s |
| Tests passed | ❌ no |

## Test output

```
test.fail(
E   Failed: text2stl HI exited 1
E   stdout: 
E   stderr: Error: 'MultiPolygon' object has no attribute 'exterior'
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:265: in test_width_scales_with_char_count
    text2stl("HELLO", "-o", str(out5))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2220/test_width_scales_with_char_co0/hello.stl exited 1
E   stdout: 
E   stderr: Error: 'MultiPolygon' object has no attribute 'exterior'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:282: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2220/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Error: 'MultiPolygon' object has no attribute 'exterior'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:299: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2220/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Error: 'MultiPolygon' object has no attribute 'exterior'
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2220/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Error: 'MultiPolygon' object has no attribute 'exterior'
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_five_chars - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - Failed: ...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight - ...
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
==================== 7 failed, 3 passed, 4 errors in 38.83s ====================

```
