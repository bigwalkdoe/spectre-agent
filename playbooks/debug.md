# Debug Runtime Failures

## Steps

1. Reproduce the failure — get exact error message and stack trace
2. Check recent commits — `git log --oneline -10`
3. Check `git diff` for uncommitted changes
4. Inspect the failing file(s) — read the relevant functions
5. Check logs (service logs, Docker logs, system logs)
6. Check environment variables are set correctly
7. Isolate the issue — is it a code bug, config issue, infrastructure, or dependency?
8. Write a failing test that reproduces the bug
9. Fix the code
10. Verify the test passes
11. Run full test suite to check for regressions
