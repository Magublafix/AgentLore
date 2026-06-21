# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-06-21 15:39 |
| Model | qwen2.5-coder:32b |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 30 |
| Turns (main loop) | 28 |
| Turns (capture) | 0 |
| Turns (wrapup) | 0 |
| Task submitted | no (hit limit) |
| Input tokens | 267,440 |
| Output tokens | 13,079 |
| Total tokens | 280,519 |
| Concepts captured this run | 0 |
| Elapsed | 15371.7s |
| Tests passed | ❌ no |

## Test output

```
mlq/text2stl/cli.py", line 34, in create_text_mesh
E       extruded_mesh = planar_mesh.extrude(0.1)  # Add 0.1 units of thickness
E   AttributeError: 'Trimesh' object has no attribute 'extrude'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:202: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-292/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run1_ckjglmlq/text2stl/cli.py", line 53, in main
E       mesh = create_text_mesh(text)
E     File "/tmp/lore_stlgen_run1_ckjglmlq/text2stl/cli.py", line 34, in create_text_mesh
E       extruded_mesh = planar_mesh.extrude(0.1)  # Add 0.1 units of thickness
E   AttributeError: 'Trimesh' object has no attribute 'extrude'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-292/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run1_ckjglmlq/text2stl/cli.py", line 53, in main
E       mesh = create_text_mesh(text)
E     File "/tmp/lore_stlgen_run1_ckjglmlq/text2stl/cli.py", line 34, in create_text_mesh
E       extruded_mesh = planar_mesh.extrude(0.1)  # Add 0.1 units of thickness
E   AttributeError: 'Trimesh' object has no attribute 'extrude'
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
==================== 7 failed, 2 passed, 4 errors in 14.43s ====================

```
