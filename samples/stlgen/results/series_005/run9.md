# Benchmark — Run 9

| Field | Value |
|-------|-------|
| Date | 2026-06-30 03:50 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (28 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 4 |
| Turns (wrapup) | 2 |
| Task submitted | no (hit limit) |
| Input tokens | 50,757 |
| Output tokens | 29,241 |
| Total tokens | 79,998 |
| Concepts captured this run | 2 |
| Elapsed | 2797.0s |
| Tests passed | ❌ no |

## Test output

```
lore_stlgen_run9_340adzrh/text2stl/cli.py", line 156, in main
E       mesh = create_text_mesh(args.text)
E     File "/tmp/lore_stlgen_run9_340adzrh/text2stl/cli.py", line 99, in create_text_mesh
E       faces.append([v0, v1, v2])  # Bottom front
E   NameError: name 'v1' is not defined
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-936/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run9_340adzrh/text2stl/cli.py", line 156, in main
E       mesh = create_text_mesh(args.text)
E     File "/tmp/lore_stlgen_run9_340adzrh/text2stl/cli.py", line 99, in create_text_mesh
E       faces.append([v0, v1, v2])  # Bottom front
E   NameError: name 'v1' is not defined
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-936/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run9_340adzrh/text2stl/cli.py", line 156, in main
E       mesh = create_text_mesh(args.text)
E     File "/tmp/lore_stlgen_run9_340adzrh/text2stl/cli.py", line 99, in create_text_mesh
E       faces.append([v0, v1, v2])  # Bottom front
E   NameError: name 'v1' is not defined
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
==================== 7 failed, 2 passed, 4 errors in 21.91s ====================

```
