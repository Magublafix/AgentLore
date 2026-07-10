# Benchmark — Run 7

| Field | Value |
|-------|-------|
| Date | 2026-07-08 22:43 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (20 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 9 |
| Task submitted | no (hit limit) |
| Input tokens | 22,123 |
| Output tokens | 13,785 |
| Total tokens | 35,908 |
| Concepts captured this run | 2 |
| Elapsed | 1376.4s |
| Tests passed | ❌ no |

## Test output

```
stl.cli import main
E     File "/tmp/lore_stlgen_run7_oz0imox5/src/text2stl/cli.py", line 131
E       return np.sqrt((point[0] - line_start[0])**2 + **(point[1] - line_start[1])2)
E                                                      ^
E   SyntaxError: invalid syntax
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:299: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2176/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 3, in <module>
E       from text2stl.cli import main
E     File "/tmp/lore_stlgen_run7_oz0imox5/src/text2stl/cli.py", line 131
E       return np.sqrt((point[0] - line_start[0])**2 + **(point[1] - line_start[1])2)
E                                                      ^
E   SyntaxError: invalid syntax
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2176/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 3, in <module>
E       from text2stl.cli import main
E     File "/tmp/lore_stlgen_run7_oz0imox5/src/text2stl/cli.py", line 131
E       return np.sqrt((point[0] - line_start[0])**2 + **(point[1] - line_start[1])2)
E                                                      ^
E   SyntaxError: invalid syntax
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_single_char - Failed:...
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
==================== 8 failed, 2 passed, 4 errors in 0.81s =====================

```
