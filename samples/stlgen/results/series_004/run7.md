# Benchmark — Run 7

| Field | Value |
|-------|-------|
| Date | 2026-06-29 20:48 |
| Model | unsloth/Qwen3.5-35B-A3B-GGUF:Q4_K_M |
| Lore search active | yes (24 concepts) |
| Web search active | yes |
| Turn budget | 36 |
| Turns (main loop) | 36 |
| Turns (capture) | 4 |
| Turns (wrapup) | 2 |
| Task submitted | no (hit limit) |
| Input tokens | 53,513 |
| Output tokens | 7,606 |
| Total tokens | 61,119 |
| Concepts captured this run | 2 |
| Elapsed | 873.6s |
| Tests passed | ❌ no |

## Test output

```
ocess:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
/usr/lib64/python3.11/subprocess.py:1026: in __init__
    self._execute_child(args, executable, preexec_fn, close_fds,
/usr/lib64/python3.11/subprocess.py:1955: in _execute_child
    raise child_exception_type(errno_num, err_msg, err_filename)
E   FileNotFoundError: [Errno 2] No such file or directory: 'text2stl'
______________ TestCharacterShapes.test_cross_section_is_nonempty ______________
tests/test_text2stl_cli.py:217: in test_cross_section_is_nonempty
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
_____________ TestCharacterShapes.test_character_shapes_match_text _____________
tests/test_text2stl_cli.py:234: in test_character_shapes_match_text
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
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_stl_loads_without_error
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_is_watertight - ...
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_mesh_has_positive_volume
ERROR tests/test_text2stl_cli.py::TestSTLValidity::test_no_degenerate_triangles
========================= 9 failed, 4 errors in 1.49s ==========================

```
