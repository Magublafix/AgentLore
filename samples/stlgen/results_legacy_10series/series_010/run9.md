# Benchmark — Run 9

| Field | Value |
|-------|-------|
| Date | 2026-07-09 17:47 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (28 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 8 |
| Task submitted | no (hit limit) |
| Input tokens | 31,777 |
| Output tokens | 18,245 |
| Total tokens | 50,022 |
| Concepts captured this run | 3 |
| Elapsed | 2142.7s |
| Tests passed | ❌ no |

## Test output

```
 77, in extrude_text_to_mesh
E       verts, faces, normals, values = measure.marching_cubes(
E     File "/home/magublafix/.local/lib/python3.9/site-packages/skimage/measure/_marching_cubes_lewiner.py", line 139, in marching_cubes
E       return _marching_cubes_lewiner(
E     File "/home/magublafix/.local/lib/python3.9/site-packages/skimage/measure/_marching_cubes_lewiner.py", line 180, in _marching_cubes_lewiner
E       raise ValueError("Surface level must be within volume data range.")
E   ValueError: Surface level must be within volume data range.
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2349/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run9_thimvdtb/text2stl/cli.py", line 155, in main
E       mesh = extrude_text_to_mesh(bitmap, height_mm=2.0)
E     File "/tmp/lore_stlgen_run9_thimvdtb/text2stl/cli.py", line 77, in extrude_text_to_mesh
E       verts, faces, normals, values = measure.marching_cubes(
E     File "/home/magublafix/.local/lib/python3.9/site-packages/skimage/measure/_marching_cubes_lewiner.py", line 139, in marching_cubes
E       return _marching_cubes_lewiner(
E     File "/home/magublafix/.local/lib/python3.9/site-packages/skimage/measure/_marching_cubes_lewiner.py", line 180, in _marching_cubes_lewiner
E       raise ValueError("Surface level must be within volume data range.")
E   ValueError: Surface level must be within volume data range.
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
==================== 8 failed, 2 passed, 4 errors in 20.33s ====================

```
