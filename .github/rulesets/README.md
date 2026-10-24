# Repository rulesets

GitHub does not read these files. They record the repository's rulesets so changes
to them can be reviewed. Apply a ruleset with the `gh` CLI (repository admin only):

```bash
team_id=$(gh api orgs/SlinkySoftware/teams/devicevault-developers --jq .id)
for f in .github/rulesets/*.json; do
  jq --argjson team "$team_id" '(.bypass_actors[] | select(.actor_id == "DEVELOPERS_TEAM_ID") | .actor_id) = $team' "$f" \
    | gh api -X POST repos/SlinkySoftware/DeviceVault/rulesets --input -
done
```

To change an existing ruleset, `PUT repos/SlinkySoftware/DeviceVault/rulesets/<id>`
(list them with `gh api repos/SlinkySoftware/DeviceVault/rulesets`).

| Ruleset | Effect |
|---|---|
| `master` | No direct pushes, force pushes or deletion; changes arrive by pull request, which needs the **make check** CI status. Repository admins may bypass. |
| `branch creation` | Only the `devicevault-developers` team and repository admins create branches; everyone else forks. |
| `release tags` | Only repository admins create, move or delete `v*` tags, since pushing one publishes a release. |
