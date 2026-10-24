# Contributing to DeviceVault

Thanks for helping. This page explains how changes get into DeviceVault.

## Ground rules

- **All changes arrive as pull requests to `master`.** Nobody pushes to `master` directly.
- **Fork first, unless you're a SlinkySoftware developer.** Only members of the
  `@SlinkySoftware/developers` team can create branches in this repository. Everyone
  else works in a fork.
- **Every pull request must pass CI** (`make check`) before it can merge.
- By contributing, you agree that your contribution is licensed under the
  [GNU GPL v3.0 or later](LICENSE.md), the project's license.
- Be respectful. Harassment or abuse gets you removed from the project.
- **Security issues are never reported in public.** See [SECURITY.md](SECURITY.md).

## Before you start

- **Bugs**: open an issue with the *Bug report* template, unless one already exists.
- **Features**: open an issue with the *Feature request* template and wait for a
  maintainer's response before investing heavily, so we can agree the approach.
  Small fixes (typos, obvious bugs) can go straight to a pull request.
- **Questions**: use [Discussions](https://github.com/SlinkySoftware/DeviceVault/discussions), not issues.
- Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): it is the agreed design, and
  changes should move the code toward it. [CLAUDE.md](CLAUDE.md) lists the
  conventions (it is written for coding agents, but applies to everyone).

## Workflow

### External contributors (fork)

1. Fork `SlinkySoftware/DeviceVault` on GitHub.
2. Clone your fork and add the upstream remote:
   ```bash
   git clone https://github.com/<you>/DeviceVault.git
   cd DeviceVault
   git remote add upstream https://github.com/SlinkySoftware/DeviceVault.git
   ```
3. Branch from an up-to-date `master`:
   ```bash
   git fetch upstream
   git switch -c feat/my-change upstream/master
   ```
4. Make your change, commit, and push to your fork (`git push -u origin feat/my-change`).
5. Open a pull request from your fork's branch to `SlinkySoftware/DeviceVault:master`.
   Leave **Allow edits by maintainers** ticked.

CI on a first-time contributor's pull request waits for a maintainer to approve it.

### SlinkySoftware developers

Clone the main repository, branch from `master`, push the branch, and open a pull request.

### Branch names

`<type>/<short-description>`, using the same types as commits: `feat/push-tftp`,
`fix/scheduler-drift`, `docs/readme-refresh`.

## Development environment

Everything runs in Docker. You need only Docker and `make`, not a host Python or
Node.js. See the README's *Development* section; in short:

```bash
make dev-up      # full stack on one host, source bind-mounted, hot reload
make dev-seed    # demo data
make check       # what CI runs: lint, tests, type checks, frontend build
make fmt         # fix formatting
```

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <summary in the imperative, lower case, no full stop>

<optional body: what and why, wrapped at 72 columns>

<optional footer: "Closes #123", "BREAKING CHANGE: ...">
```

| Type | For |
|---|---|
| `feat` | a new feature |
| `fix` | a bug fix |
| `docs` | documentation only |
| `refactor` | a code change that neither fixes a bug nor adds a feature |
| `perf` | a performance improvement |
| `test` | adding or fixing tests |
| `build` | Docker, dependencies, the Makefile |
| `ci` | GitHub Actions workflows |
| `chore` | anything else that doesn't touch shipped code |

Typical scopes are the components: `orchestrator`, `api`, `worker`, `receiver`,
`protocol`, `frontend`, `deploy`. Examples:

```
feat(worker): add Juniper Junos collector driver
fix(api): hide storage targets from non-admins in job details
docs: explain DV_VERSION pinning
```

The pull request title follows the same format.

## Pull requests

- Keep each pull request to one change. Split unrelated work.
- Fill in the template's checklist.
- Add or update tests. Python tests live in `<package>/tests/` (pytest), frontend
  tests next to the code (`*.spec.ts`, Vitest).
- Document new `DV_*` environment variables in `docs/DEPLOYMENT.md` and the relevant
  `deploy/*/*.env.example`.
- Model changes need generated migrations. Dependency changes need `make lock` (Python)
  or an updated `frontend/package-lock.json`.
- A developer reviews every pull request (CODEOWNERS requests them automatically).
  Address the feedback by pushing more commits; don't force-push once review has started.

## Releases (maintainers)

The version lives in the root `VERSION` file and follows [Semantic Versioning](https://semver.org/).

1. On a branch, run `make set-version V=X.Y.Z`. It updates `VERSION`, every
   `pyproject.toml`, `frontend/package.json` and the lockfiles. Commit the change
   (`chore: release X.Y.Z`), open a pull request and merge it.
2. Tag the merge commit on `master` and push the tag:
   ```bash
   git switch master && git pull
   git tag -a vX.Y.Z -m "DeviceVault X.Y.Z"
   git push origin vX.Y.Z
   ```
3. The *Release* workflow checks the tag matches `VERSION`, runs `make check`,
   publishes signed `linux/amd64` and `linux/arm64` images to
   `ghcr.io/slinkysoftware/devicevault-{orchestrator,web,worker,receiver}`, and creates
   the GitHub Release with generated notes.

Only maintainers can push `v*` tags. A tag with a suffix (`v0.2.0-rc.1`) makes a
pre-release, which gets no `latest` tag.
