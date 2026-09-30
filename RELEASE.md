# Release candidate checklist

1. Start from a clean worktree and review every generated or recovery file.
2. Run `python -m pytest -m 'not live'` on every supported Python version.
3. Run `python VALIDATE_STUBS.py`.
4. Build with `python -m build` and install both wheel and sdist into clean
   virtual environments.
5. Verify `msxdbg --version`, `msxdbg --help`, and one offline `resolve` flow.
6. Run the opt-in live suite against the qualified openMSX version.
7. Capture benchmark JSON and compare it to the accepted baseline.
8. Confirm `CHANGELOG.md`, compatibility claims, package version, and JSON
   schema policy.
9. Tag only the reviewed commit; do not release from a dirty worktree.

