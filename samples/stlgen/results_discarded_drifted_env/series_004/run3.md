# Benchmark — Run 3

| Field | Value |
|-------|-------|
| Date | 2026-11-20 01:41 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 1637 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (5 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 10 |
| Task submitted | no (hit limit) |
| Input tokens | 37,988 |
| Output tokens | 15,483 |
| Total tokens | 53,471 |
| Concepts captured this run | 3 |
| Noise concepts injected | 0 |
| Elapsed | 837.7s |
| Tests passed | ❌ no |

## Test output

```
ne 6, in <module>
E       sys.exit(main())
E                ^^^^^^
E     File "/tmp/lore_stlgen_run3_nvspqmqy/src/text2stl/cli.py", line 55, in main
E       mesh = generate_text_mesh(text)
E              ^^^^^^^^^^^^^^^^^^^^^^^^
E     File "/tmp/lore_stlgen_run3_nvspqmqy/src/text2stl/text.py", line 101, in generate_text_mesh
E       mesh = trimesh.creation.extrude_polygon(union, height=height)
E              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/creation.py", line 235, in extrude_polygon
E       vertices, faces = triangulate_polygon(polygon, **kwargs)
E                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/creation.py", line 659, in triangulate_polygon
E       arg = _polygon_to_kwargs(polygon)
E             ^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/creation.py", line 745, in _polygon_to_kwargs
E       start = add_boundary(polygon.exterior, 0)
E                            ^^^^^^^^^^^^^^^^
E   AttributeError: 'MultiPolygon' object has no attribute 'exterior'
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
==================== 8 failed, 2 passed, 4 errors in 11.75s ====================
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
