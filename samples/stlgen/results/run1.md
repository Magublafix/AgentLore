# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-06-26 08:54 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (capture) | 15 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 81,650 |
| Output tokens | 25,060 |
| Total tokens | 106,710 |
| Concepts captured this run | 7 |
| Elapsed | 2534.5s |
| Tests passed | ❌ no |

## Test output

```

E       mesh = _create_text_mesh(text)
E     File "/tmp/lore_stlgen_run1_c1820u6o/text2stl/cli.py", line 167, in _create_text_mesh
E       mesh.remove_degenerate_faces()
E   AttributeError: 'NoneType' object has no attribute 'remove_degenerate_faces'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-576/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Error creating mesh: 'NoneType' object has no attribute 'remove_degenerate_faces'
E   Traceback (most recent call last):
E     File "/tmp/lore_stlgen_run1_c1820u6o/text2stl/cli.py", line 228, in main
E       mesh = _create_text_mesh(text)
E     File "/tmp/lore_stlgen_run1_c1820u6o/text2stl/cli.py", line 167, in _create_text_mesh
E       mesh.remove_degenerate_faces()
E   AttributeError: 'NoneType' object has no attribute 'remove_degenerate_faces'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-576/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Error creating mesh: 'NoneType' object has no attribute 'remove_degenerate_faces'
E   Traceback (most recent call last):
E     File "/tmp/lore_stlgen_run1_c1820u6o/text2stl/cli.py", line 228, in main
E       mesh = _create_text_mesh(text)
E     File "/tmp/lore_stlgen_run1_c1820u6o/text2stl/cli.py", line 167, in _create_text_mesh
E       mesh.remove_degenerate_faces()
E   AttributeError: 'NoneType' object has no attribute 'remove_degenerate_faces'
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
=============== 7 failed, 2 passed, 4 errors in 74.98s (0:01:14) ===============

```
