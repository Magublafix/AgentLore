# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-06-29 01:25 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (6 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 7 |
| Turns (wrapup) | 4 |
| Task submitted | no (hit limit) |
| Input tokens | 63,658 |
| Output tokens | 13,871 |
| Total tokens | 77,529 |
| Concepts captured this run | 4 |
| Elapsed | 1424.2s |
| Tests passed | ❌ no |

## Test output

```
cent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 261, in main
E       create_stl(args.text, output_path)
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 202, in create_stl
E       mesh = _create_text_mesh(text, height=2.0)
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 161, in _create_text_mesh
E       path = _create_2d_path(bitmap, scale=0.05)
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 146, in _create_2d_path
E       if pts[0] != pts[-1]:
E   ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-802/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 261, in main
E       create_stl(args.text, output_path)
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 202, in create_stl
E       mesh = _create_text_mesh(text, height=2.0)
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 161, in _create_text_mesh
E       path = _create_2d_path(bitmap, scale=0.05)
E     File "/tmp/lore_stlgen_run3_75utkh1x/text2stl/__init__.py", line 146, in _create_2d_path
E       if pts[0] != pts[-1]:
E   ValueError: The truth value of an array with more than one element is ambiguous. Use a.any() or a.all()
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
==================== 7 failed, 2 passed, 4 errors in 14.99s ====================

```
