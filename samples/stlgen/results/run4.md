# Benchmark — Run 4

| Field | Value |
|-------|-------|
| Date | 2026-06-19 09:39 |
| Model | qwen2.5-coder:32b |
| Lore search active | yes (17 concepts) |
| Web search active | yes |
| Turn budget | 20 |
| Turns (main loop) | 20 |
| Turns (capture) | 15 |
| Turns (wrapup) | 15 |
| Task submitted | no (hit limit) |
| Input tokens | 202,709 |
| Output tokens | 10,568 |
| Total tokens | 213,277 |
| Concepts captured this run | 10 |
| Elapsed | 6945.8s |
| Tests passed | ❌ no |

## Test output

```
___________
tests/test_text2stl_cli.py:184: in test_width_scales_with_char_count
    text2stl("A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-217/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 3, in <module>
E       from text2stl.__main__ import cli_entry
E   ImportError: cannot import name 'cli_entry' from 'text2stl.__main__' (/tmp/lore_stlgen_run4_a7fouubd/text2stl/__main__.py)
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:202: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-217/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 3, in <module>
E       from text2stl.__main__ import cli_entry
E   ImportError: cannot import name 'cli_entry' from 'text2stl.__main__' (/tmp/lore_stlgen_run4_a7fouubd/text2stl/__main__.py)
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-217/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 3, in <module>
E       from text2stl.__main__ import cli_entry
E   ImportError: cannot import name 'cli_entry' from 'text2stl.__main__' (/tmp/lore_stlgen_run4_a7fouubd/text2stl/__main__.py)
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
==================== 7 failed, 2 passed, 4 errors in 20.59s ====================

```
