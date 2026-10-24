<!--
Title: a Conventional Commit, e.g. "feat(worker): add Juniper Junos driver" or "fix(api): ...".
See CONTRIBUTING.md.
-->

## What and why

<!-- What this changes and why. Link the issue: "Closes #123". -->

## How it was tested

## Checklist

- [ ] `make check` passes locally
- [ ] Tests added or updated for the change
- [ ] New `DV_*` variables are documented in `docs/DEPLOYMENT.md` and the relevant `*.env.example`
- [ ] Model changes have generated migrations (`makemigrations`)
- [ ] API changes keep `api/serializers.py`, `api/views.py` and `frontend/src/api/types.ts` / `endpoints.ts` in step
- [ ] Docs (`README.md`, `docs/`) updated where behaviour changed
