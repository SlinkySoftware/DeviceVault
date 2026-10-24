# Security policy

DeviceVault holds device credentials and configuration backups, so we take
security reports seriously.

## Reporting a vulnerability

**Do not open a public issue, discussion or pull request.** Report it privately
through GitHub: go to the repository's **Security** tab and choose
**Report a vulnerability**
([direct link](https://github.com/SlinkySoftware/DeviceVault/security/advisories/new)).

Please include:

- the affected version (`dv-orchestrator version`, or the version shown in the UI) and component;
- what an attacker can do, and what access they need first;
- steps or a proof of concept to reproduce it.

We aim to acknowledge reports within 5 business days. We'll keep you informed while
we work on a fix, agree a disclosure date with you, and credit you in the advisory
unless you prefer otherwise.

## Supported versions

DeviceVault is pre-1.0. Security fixes go into the next release only, so run the
latest release.

## Verifying images

Release images on `ghcr.io/slinkysoftware` are signed with cosign keyless signing
and carry an SBOM and build provenance; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#1-images).
