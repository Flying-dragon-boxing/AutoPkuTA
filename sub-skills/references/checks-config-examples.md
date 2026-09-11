# Code Checks Config Examples

`run_code_checks.py` reads a JSON config per assignment. The goal is to capture facts for grading, not to encode the final rubric.

## Basic Inspection

Use this when first probing a new code assignment:

```json
{
  "extract_zip": true,
  "commands": [
    {"name": "list", "cmd": "find . -maxdepth 4 -type f | sort", "timeout": 5},
    {"name": "file_types", "cmd": "find . -maxdepth 4 -type f -print0 | xargs -0 file", "timeout": 10}
  ]
}
```

## Single C++ File

Use when the assignment expects one `main_<student_id>.cpp`:

```json
{
  "extract_zip": true,
  "commands": [
    {"name": "list", "cmd": "find . -maxdepth 4 -type f | sort", "timeout": 5},
    {"name": "compile_cpp17", "cmd": "g++ -std=c++17 -O2 -Wall -Wextra *.cpp -o main", "timeout": 20},
    {"name": "smoke", "cmd": "./main", "timeout": 10}
  ]
}
```

## Makefile Project

```json
{
  "extract_zip": true,
  "commands": [
    {"name": "list", "cmd": "find . -maxdepth 5 -type f | sort", "timeout": 5},
    {"name": "make", "cmd": "make", "timeout": 60},
    {"name": "test", "cmd": "make test", "timeout": 60}
  ]
}
```

If a command is expected to fail for partial submissions, keep it in the config. The grader should use the log as evidence and still assign partial credit from source and report content.
