# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-06-21 19:23 |
| Model | qwen2.5-coder:32b |
| Lore search active | yes (1 concepts) |
| Web search active | yes |
| Turn budget | 30 |
| Turns (main loop) | 17 |
| Turns (capture) | 15 |
| Turns (wrapup) | 8 |
| Task submitted | no (hit limit) |
| Input tokens | 256,113 |
| Output tokens | 13,889 |
| Total tokens | 270,002 |
| Concepts captured this run | 7 |
| Elapsed | 11376.4s |
| Tests passed | ❌ no |

## Test output

```
lgen_run2_rjd7qnmb/text2stl/cli.py", line 52, in text_to_mesh
E       raise ValueError(f"No renderable glyphs found for {text!r}")
E   ValueError: No renderable glyphs found for 'A'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:202: in test_cross_section_is_nonempty
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-299/test_cross_section_is_nonempty0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run2_rjd7qnmb/text2stl/cli.py", line 65, in main
E       mesh = text_to_mesh(args.text, height=20.0, font_size=192)
E     File "/tmp/lore_stlgen_run2_rjd7qnmb/text2stl/cli.py", line 52, in text_to_mesh
E       raise ValueError(f"No renderable glyphs found for {text!r}")
E   ValueError: No renderable glyphs found for 'HELLO'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-299/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run2_rjd7qnmb/text2stl/cli.py", line 65, in main
E       mesh = text_to_mesh(args.text, height=20.0, font_size=192)
E     File "/tmp/lore_stlgen_run2_rjd7qnmb/text2stl/cli.py", line 52, in text_to_mesh
E       raise ValueError(f"No renderable glyphs found for {text!r}")
E   ValueError: No renderable glyphs found for 'HELLO'
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
