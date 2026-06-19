# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-06-19 02:04 |
| Model | qwen2.5-coder:32b |
| Lore search active | yes (7 concepts) |
| Web search active | yes |
| Turn budget | 20 |
| Turns (main loop) | 20 |
| Turns (capture) | 15 |
| Turns (wrapup) | 10 |
| Task submitted | no (hit limit) |
| Input tokens | 245,387 |
| Output tokens | 14,315 |
| Total tokens | 259,702 |
| Concepts captured this run | 5 |
| Elapsed | 6112.4s |
| Tests passed | ❌ no |

## Test output

```
)
E     File "/home/magublafix/.local/lib/python3.9/site-packages/fontTools/ttLib/sfnt.py", line 490, in fromFile
E       sstruct.unpack(self.format, file.read(self.formatSize), self)
E     File "/home/magublafix/.local/lib/python3.9/site-packages/fontTools/misc/sstruct.py", line 95, in unpack
E       elements = struct.unpack(formatstring, data)
E   struct.error: unpack requires a buffer of 16 bytes
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:219: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-magublafix/pytest-195/test_character_shapes_match_te0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run2_0zcb7h3y/text2stl/__init__.py", line 85, in main
E       polygons = get_glyph_polygons('arial.ttf', text)
E     File "/tmp/lore_stlgen_run2_0zcb7h3y/text2stl/__init__.py", line 42, in get_glyph_polygons
E       font = TTFont(font_path)
E     File "/home/magublafix/.local/lib/python3.9/site-packages/fontTools/ttLib/ttFont.py", line 189, in __init__
E       self.reader = SFNTReader(file, checkChecksums, fontNumber=fontNumber)
E     File "/home/magublafix/.local/lib/python3.9/site-packages/fontTools/ttLib/sfnt.py", line 90, in __init__
E       entry.fromFile(self.file)
E     File "/home/magublafix/.local/lib/python3.9/site-packages/fontTools/ttLib/sfnt.py", line 490, in fromFile
E       sstruct.unpack(self.format, file.read(self.formatSize), self)
E     File "/home/magublafix/.local/lib/python3.9/site-packages/fontTools/misc/sstruct.py", line 95, in unpack
E       elements = struct.unpack(formatstring, data)
E   struct.error: unpack requires a buffer of 16 bytes
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
==================== 7 failed, 2 passed, 4 errors in 23.21s ====================

```
