# PyCharm coverage shows 0% for all files — how to fix

If the PyCharm Coverage pane shows 0% for every file/folder even though your tests ran, it’s usually because two coverage engines are running at once (PyCharm’s coverage and pytest-cov) or because paths in the coverage data don’t map cleanly back to your project files.

This repo is configured to collect coverage for CLI runs via pytest-cov. For IDE coverage, use PyCharm’s coverage runner and disable pytest-cov for that run.

## Quick fix (recommended)

1) Use a dedicated PyCharm Run/Debug configuration for tests:
- Test type: Folder
- Folder: <project_root>/tests
- Working directory: <project_root>
- Additional Arguments: --ignore=tests/integration --no-cov --junitxml=.test-reports/pytests-no-integration.xml
- Interpreter: your project virtualenv
- Ensure “Add content roots to PYTHONPATH” and “Add source roots to PYTHONPATH” are checked

2) Run with Coverage from the IDE (Run ▶ Run with Coverage). When prompted, choose “Replace active suites”.

Result: The IDE Coverage pane should show non-zero coverage per file in app/.

## Why this works
This prevents double-instrumentation. PyCharm’s coverage runner gathers data that the IDE understands, while `--no-cov` disables pytest-cov for this run only. The `--junitxml` argument writes a durable test report without interfering with PyCharm's coverage collector.

Use `--no-cov` rather than `-p no:cov` in this repo. `pytest.ini` defines `--cov*` options globally, and disabling the plugin with `-p no:cov` makes those options unrecognized.

Do not add a `PYCHARM_HOSTED` hook in `tests/conftest.py` to strip coverage arguments. PyCharm sets that environment variable, and stripping `--no-cov` causes pytest-cov to become active again through `pytest.ini`, which leads back to empty or all-zero IDE coverage reports.

## Repo-side improvements included
- .coveragerc sets:
  - source = app
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

Keep `chainlit_app.py` out of the broad coverage run. It is a Chainlit
entrypoint with module-level decorators and framework wiring; tracing it during
PyCharm test instantiation can hang the run. Cover reusable behavior in
`app/services/chainlit/*`, and use `tests/test_chainlit_callbacks.py` as a
lightweight smoke test for the entrypoint callbacks.

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
    /workspace/AIMSBot/app
    /home/you/AIMSBot/app
```

This tells coverage to treat those locations as the same source tree so the IDE can map results.
