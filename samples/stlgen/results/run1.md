# Benchmark — Run 1

| Field | Value |
|-------|-------|
| Date | 2026-06-17 14:55 |
| Model | qwen2.5-coder:32b |
| Lore search active | no |
| Web search active | yes |
| Turn budget | 20 |
| Turns (main loop) | 20 |
| Turns (capture) | 0 |
| Turns (wrapup) | 0 |
| Task submitted | no (hit limit) |
| Input tokens | 108,240 |
| Output tokens | 4,603 |
| Total tokens | 112,843 |
| Concepts captured this run | 0 |
| Elapsed | 4532.3s |
| Tests passed | ❌ no |

## Test output

```
FGHIJKLMNO -o /tmp/pytest-of-magublafix/pytest-157/test_max_length0/max.stl exited 1
E   stdout: 
E   stderr: Error: module 'trimesh.voxel' has no attribute 'marching_cubes'
_________________ TestInvocation.test_default_output_filename __________________
/tmp/lore_stlgen_run1_68wz9qce/tests/test_text2stl_cli.py:117: in test_default_output_filename
    text2stl("HI")
/tmp/lore_stlgen_run1_68wz9qce/tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HI exited 1
E   stdout: 
E   stderr: Error: module 'trimesh.voxel' has no attribute 'marching_cubes'
_______________ TestDimensions.test_width_scales_with_char_count _______________
tests/test_text2stl_cli.py:184: in test_width_scales_with_char_count
    text2stl("A", "-o", str(out1))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl A -o /tmp/pytest-of-magublafix/pytest-157/test_width_scales_with_char_co0/a.stl exited 1
E   stdout: 
E   stderr: Error: module 'trimesh.voxel' has no attribute 'marching_cubes'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:202: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-157/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Error: module 'trimesh.voxel' has no attribute 'marching_cubes'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-157/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Error: module 'trimesh.voxel' has no attribute 'marching_cubes'
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
==================== 7 failed, 2 passed, 4 errors in 50.49s ====================

```
