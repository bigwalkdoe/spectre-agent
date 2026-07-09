# Prepare a Production Release

## Steps

1. Ensure `main` is up to date and all CI passes
2. Create a release branch: `release/vX.Y.Z`
3. Update version numbers in `pyproject.toml`, `package.json`, etc.
4. Update `CHANGELOG.md` with release notes
5. Create a GitHub Release with release notes
6. Build and tag container images: `podman build -t modelink/service:X.Y.Z .`
7. Push images to container registry
8. Deploy to staging and run smoke tests
9. If successful, deploy to production
10. Tag the release in git: `git tag vX.Y.Z && git push --tags`
