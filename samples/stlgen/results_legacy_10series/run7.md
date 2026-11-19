# Benchmark — Run 7

| Field | Value |
|-------|-------|
| Date | 2026-07-17 02:33 |
| Backend | gists |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (0 concepts) |
| Web search active | yes |
| Turn budget | 40 |
| Turns (main loop) | 0 |
| Turns (wrapup) | 0 |
| Task submitted | no (hit limit) |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Concepts captured this run | 0 |
| Elapsed | 393.2s |
| Tests passed | ❌ no |

## Test output

```

    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:299: in test_character_shapes_match_text
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
___________ TestCharacterShapes.test_character_shapes_not_truncated ____________
tests/test_text2stl_cli.py:349: in test_character_shapes_not_truncated
    text2stl("HELLO", "-o", str(out))
tests/test_text2stl_cli.py:22: in text2stl
    result = subprocess.run(
/usr/lib64/python3.11/subprocess.py:548: in run
    with Popen(*popenargs, **kwargs) as process:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
=========================== short test summary info ============================
FAILED tests/test_text2stl_cli.py::TestInvocation::test_single_char - FileNot...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_five_chars - FileNotF...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_max_length - FileNotF...
FAILED tests/test_text2stl_cli.py::TestInvocation::test_default_output_filename
FAILED tests/test_text2stl_cli.py::TestValidation::test_empty_string_rejected
FAILED tests/test_text2stl_cli.py::TestValidation::test_too_long_rejected - F...
FAILED tests/test_text2stl_cli.py::TestDimensions::test_width_scales_with_char_count
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_cross_section_is_nonempty
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_match_text
FAILED tests/test_text2stl_cli.py::TestCharacterShapes::test_character_shapes_not_truncated
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight - ...
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
========================= 10 failed, 4 errors in 1.37s =========================

```
