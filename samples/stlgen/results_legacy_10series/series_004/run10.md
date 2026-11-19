# Benchmark — Run 10

| Field | Value |
|-------|-------|
| Date | 2026-07-08 09:19 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (17 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 18 |
| Task submitted | no (hit limit) |
| Input tokens | 33,661 |
| Output tokens | 16,859 |
| Total tokens | 50,520 |
| Concepts captured this run | 5 |
| Elapsed | 1640.0s |
| Tests passed | ❌ no |

## Test output

```
 meshes from contours")
E   ValueError: Failed to create extruded meshes from contours
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:299: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2065/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run10_8m3yoale/text2stl/cli.py", line 35, in main
E       text_to_stl(text, str(output_path))
E     File "/tmp/lore_stlgen_run10_8m3yoale/text2stl/converter.py", line 89, in text_to_stl
E       raise ValueError("Failed to create extruded meshes from contours")
E   ValueError: Failed to create extruded meshes from contours
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-2065/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run10_8m3yoale/text2stl/cli.py", line 35, in main
E       text_to_stl(text, str(output_path))
E     File "/tmp/lore_stlgen_run10_8m3yoale/text2stl/converter.py", line 89, in text_to_stl
E       raise ValueError("Failed to create extruded meshes from contours")
E   ValueError: Failed to create extruded meshes from contours
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
==================== 8 failed, 2 passed, 4 errors in 15.75s ====================

```
