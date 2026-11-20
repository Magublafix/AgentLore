# Benchmark — Run 2

| Field | Value |
|-------|-------|
| Date | 2026-11-19 14:38 |
| Backend | selfhosted |
| Condition | agentlore |
| Context tokens supplied | 786 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (3 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 40 |
| Turns (wrapup) | 7 |
| Task submitted | no (hit limit) |
| Input tokens | 21,428 |
| Output tokens | 4,052 |
| Total tokens | 25,480 |
| Concepts captured this run | 2 |
| Noise concepts injected | 0 |
| Elapsed | 282.2s |
| Tests passed | ❌ no |

## Test output

```
loper/.local/bin/text2stl", line 5, in <module>
E       from text2stl.cli import main
E     File "/tmp/lore_stlgen_run1_2684o6_v/src/text2stl/cli.py", line 10, in <module>
E       from trimesh.creation import text as create_text_mesh
E   ImportError: cannot import name 'text' from 'trimesh.creation' (/home/developer/.local/lib/python3.12/site-packages/trimesh/creation.py)
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:29: in text2stl
    pytest.fail(
E   Failed: text2stl HELLO -o /tmp/pytest-of-developer/pytest-152/test_character_shapes_not_trun0/hello.stl exited 1
E   stdout: 
E   stderr: Traceback (most recent call last):
E     File "/home/developer/.local/bin/text2stl", line 5, in <module>
E       from text2stl.cli import main
E     File "/tmp/lore_stlgen_run1_2684o6_v/src/text2stl/cli.py", line 10, in <module>
E       from trimesh.creation import text as create_text_mesh
E   ImportError: cannot import name 'text' from 'trimesh.creation' (/home/developer/.local/lib/python3.12/site-packages/trimesh/creation.py)
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
==================== 8 failed, 2 passed, 4 errors in 11.19s ====================
/workspace/.venvs/lore/lib/python3.12/site-packages/pytest_asyncio/plugin.py:300: PytestDeprecationWarning: The configuration option "asyncio_default_fixture_loop_scope" is unset.
The event loop scope for asynchronous fixtures will default to the "fixture" caching scope. Future versions of pytest-asyncio will default the loop scope for asynchronous fixtures to "function" scope. Set the default fixture loop scope explicitly in order to avoid unexpected behavior in the future. Valid fixture loop scopes are: "function", "class", "module", "package", "session"

  warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))

```
