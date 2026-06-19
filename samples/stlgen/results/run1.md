# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-06-18 17:46 |
| Model | qwen2.5-coder:32b |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 20 |
| Turns (main loop) | 20 |
| Turns (capture) | 15 |
| Turns (wrapup) | 6 |
| Task submitted | no (hit limit) |
| Input tokens | 169,527 |
| Output tokens | 6,277 |
| Total tokens | 175,804 |
| Concepts captured this run | 6 |
| Elapsed | 3097.4s |
| Tests passed | ❌ no |

## Test output

```
th.polygons.find_contours(ascii_array, mask_value=True)
E   AttributeError: module 'trimesh.path.polygons' has no attribute 'find_contours'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:202: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-191/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run1_xzcm4j1k/src/text2stl.py", line 25, in main
E       mesh = string_to_mesh(args.text)
E     File "/tmp/lore_stlgen_run1_xzcm4j1k/src/text2stl.py", line 13, in string_to_mesh
E       contours = trimesh.path.polygons.find_contours(ascii_array, mask_value=True)
E   AttributeError: module 'trimesh.path.polygons' has no attribute 'find_contours'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-191/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run1_xzcm4j1k/src/text2stl.py", line 25, in main
E       mesh = string_to_mesh(args.text)
E     File "/tmp/lore_stlgen_run1_xzcm4j1k/src/text2stl.py", line 13, in string_to_mesh
E       contours = trimesh.path.polygons.find_contours(ascii_array, mask_value=True)
E   AttributeError: module 'trimesh.path.polygons' has no attribute 'find_contours'
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
==================== 7 failed, 2 passed, 4 errors in 21.34s ====================

```
