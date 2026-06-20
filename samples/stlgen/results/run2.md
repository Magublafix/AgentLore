# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-06-20 06:38 |
| Model | qwen2.5-coder:32b |
| Lore search active | yes (1 concepts) |
| Web search active | yes |
| Turn budget | 30 |
| Turns (main loop) | 30 |
| Turns (capture) | 15 |
| Turns (wrapup) | 12 |
| Task submitted | no (hit limit) |
| Input tokens | 418,918 |
| Output tokens | 9,766 |
| Total tokens | 428,684 |
| Concepts captured this run | 11 |
| Elapsed | 4941.1s |
| Tests passed | ❌ no |

## Test output

```
ating polygon: No available triangulation engine!
E   try running `pip install mapbox-earcut manifold3d`or `triangle`, `mapbox_earcut`, then explicitly pass:
E   `triangulate_polygon(*args, engine="triangle")`
E   to use the non-FSF-approved-license triangle engine
E   Error triangulating polygon: No available triangulation engine!
E   try running `pip install mapbox-earcut manifold3d`or `triangle`, `mapbox_earcut`, then explicitly pass:
E   `triangulate_polygon(*args, engine="triangle")`
E   to use the non-FSF-approved-license triangle engine
E   Error triangulating polygon: No available triangulation engine!
E   try running `pip install mapbox-earcut manifold3d`or `triangle`, `mapbox_earcut`, then explicitly pass:
E   `triangulate_polygon(*args, engine="triangle")`
E   to use the non-FSF-approved-license triangle engine
E   Error triangulating polygon: No available triangulation engine!
E   try running `pip install mapbox-earcut manifold3d`or `triangle`, `mapbox_earcut`, then explicitly pass:
E   `triangulate_polygon(*args, engine="triangle")`
E   to use the non-FSF-approved-license triangle engine
E   Error triangulating polygon: No available triangulation engine!
E   try running `pip install mapbox-earcut manifold3d`or `triangle`, `mapbox_earcut`, then explicitly pass:
E   `triangulate_polygon(*args, engine="triangle")`
E   to use the non-FSF-approved-license triangle engine
E   Error triangulating polygon: No available triangulation engine!
E   Traceback (most recent call last):
E     File "/home/magublafix/.local/bin/text2stl", line 6, in <module>
E       sys.exit(main())
E     File "/tmp/lore_stlgen_run2_gn3yf8v1/text2stl/cli.py", line 50, in main
E       mesh = text_to_mesh(args.text)
E     File "/tmp/lore_stlgen_run2_gn3yf8v1/text2stl/cli.py", line 38, in text_to_mesh
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
==================== 7 failed, 2 passed, 4 errors in 24.40s ====================

```
