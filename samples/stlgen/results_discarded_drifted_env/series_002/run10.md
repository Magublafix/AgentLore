# Benchmark — Run 10

| Field | Value |
|-------|-------|
| Date | 2026-11-19 22:38 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 355 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (23 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 2 |
| Task submitted | no (hit limit) |
| Input tokens | 21,790 |
| Output tokens | 11,285 |
| Total tokens | 33,075 |
| Concepts captured this run | 0 |
| Noise concepts injected | 0 |
| Elapsed | 653.2s |
| Tests passed | ❌ no |

## Test output

```
ed
E       value = function(*args, **kwargs)
E               ^^^^^^^^^^^^^^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/parent.py", line 251, in scale
E       if self.extents is None:
E          ^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/path/path.py", line 374, in extents
E       return np.ptp(self.bounds, axis=0)
E                     ^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/caching.py", line 139, in get_cached
E       value = function(*args, **kwargs)
E               ^^^^^^^^^^^^^^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/trimesh/path/path.py", line 349, in bounds
E       return np.array([points.min(axis=0), points.max(axis=0)], dtype=np.float64)
E                        ^^^^^^^^^^^^^^^^^^
E     File "/home/developer/.local/lib/python3.12/site-packages/numpy/_core/_methods.py", line 45, in _amin
E       return umr_minimum(a, axis, None, out, keepdims, initial, where)
E              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   ValueError: zero-size array to reduction operation minimum which has no identity
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
==================== 8 failed, 2 passed, 4 errors in 12.60s ====================
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
