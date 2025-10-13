# PyCharm coverage shows 0% for all files — how to fix

If the PyCharm Coverage pane shows 0% for every file/folder even though your tests ran, it’s usually because two coverage engines are running at once (PyCharm’s coverage and pytest-cov) or because paths in the coverage data don’t map cleanly back to your project files.

This repo is configured to collect coverage for CLI runs via pytest-cov. For IDE coverage, use PyCharm’s coverage runner and disable pytest-cov for that run.

## Quick fix (recommended)

1) Use a dedicated PyCharm Run/Debug configuration for tests:
- Test type: Folder
- Folder: <project_root>/tests
- Working directory: <project_root>
- Additional Arguments: -q -p no:cov
- Interpreter: your project virtualenv
- Ensure “Add content roots to PYTHONPATH” and “Add source roots to PYTHONPATH” are checked

2) Run with Coverage from the IDE (Run ▶ Run with Coverage). When prompted, choose “Replace active suites”.

Result: The IDE Coverage pane should show non-zero coverage per file in app/.

## Why this works
This prevents double-instrumentation. PyCharm’s coverage runner gathers data that the IDE understands, while -p no:cov disables pytest-cov (which is already enabled by default in pytest.ini for CLI use).

## Repo-side improvements included
- .coveragerc sets:
  - source = app (only measure the backend package)
  - branch = True (branch coverage)
  - relative_files = True (helps map files correctly regardless of working dir)

You can run CLI coverage any time with:

```
pytest
```

The pytest.ini already includes:

```
--cov=app --cov-report=term-missing --cov-config=.coveragerc
```

## If you still see 0%
- Verify the interpreter in your Run Configuration matches your CLI venv
- Mark the app/ directory as “Sources Root” (Right-click app/ ▶ Mark Directory As ▶ Sources Root)
- Clear old coverage data (coverage erase) and choose “Replace active suites” in the prompt
- Preferences ▶ Build, Execution, Deployment ▶ Coverage ▶ Coverage runner: Python
- In Coverage tool window, clear any filters (gear icon ▶ Packages/classes to show)

## Advanced: Path mappings for remote/Docker/WSL
If you run tests remotely (Docker/WSL), you may need coverage path mappings. Add a [paths] section in .coveragerc to normalize different absolute paths, for example:

```
[paths]
source =
    app
    /workspace/JaigBot/app
    /home/you/JaigBot/app
```

This tells coverage to treat those locations as the same source tree so the IDE can map results.
