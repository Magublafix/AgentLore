# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-06-23 04:31 |
| Model | qwen2.5-coder:32b |
| Lore search active | yes (5 concepts) |
| Web search active | yes |
| Turn budget | 30 |
| Turns (main loop) | 30 |
| Turns (capture) | 15 |
| Turns (wrapup) | 9 |
| Task submitted | no (hit limit) |
| Input tokens | 334,347 |
| Output tokens | 9,525 |
| Total tokens | 343,872 |
| Concepts captured this run | 4 |
| Elapsed | 4951.3s |
| Tests passed | ❌ no |

## Test output

```
ns(text_string)
E     File "/tmp/lore_stlgen_run3_55x6wpgv/text2stl.py", line 10, in text_to_polygons
E       polygon = font.get_path(char).to_polygons()
E   AttributeError: 'FontProperties' object has no attribute 'get_path'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-365/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run3_55x6wpgv/text2stl.py", line 23, in main
E       polygons = text_to_polygons(text_string)
E     File "/tmp/lore_stlgen_run3_55x6wpgv/text2stl.py", line 10, in text_to_polygons
E       polygon = font.get_path(char).to_polygons()
E   AttributeError: 'FontProperties' object has no attribute 'get_path'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-365/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run3_55x6wpgv/text2stl.py", line 23, in main
E       polygons = text_to_polygons(text_string)
E     File "/tmp/lore_stlgen_run3_55x6wpgv/text2stl.py", line 10, in text_to_polygons
E       polygon = font.get_path(char).to_polygons()
E   AttributeError: 'FontProperties' object has no attribute 'get_path'
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
==================== 7 failed, 2 passed, 4 errors in 5.28s =====================

```
