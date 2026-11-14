# Repository settings: the protected `main`

`main` is protected by one repository ruleset, `protect-main`, kept in
`.github/rulesets/protect-main.json`. Nothing reaches `main` except a squash-merged pull request whose
required checks are green. `agent/tests/test_repository_ruleset.py` fails if the file's required checks
stop matching the job names in `.github/workflows/ci.yml`.

The repository is public, so rulesets are available on the free plan.

## The rules

| Rule | Setting | Why |
| --- | --- | --- |
| Target | the default branch (`~DEFAULT_BRANCH`) | follows `main`, even if it is renamed |
| Enforcement | Active | enforced as soon as it is created |
| Bypass list | empty | the owner and the automation follow the same path |
| Restrict deletions | on | `main` cannot be deleted |
| Block force pushes | on | history on `main` cannot be rewritten |
| Require linear history | on | no merge commits on `main`; easy to revert one story |
| Require a pull request | 0 approvals, conversations resolved, squash only | every change has a pull request; see below for why 0 |
| Require status checks | `check`, `docker` and `allowlist-review`, branch up to date | CI must be green on the code as it will land |

**Why 0 approvals.** Every pull request, including the ones the automation opens, is authored under the
owner's account, and the author of a pull request cannot approve it. One required approval would block every
merge unless the owner had a bypass, and the automation acts as the owner, so it would get the same bypass.

## Rules not used, and why

- **Require signed commits:** commits made in Claude sessions are unsigned, and unsigned commits on a head
  branch block a squash merge even though GitHub signs the squash commit.
- **Push rulesets** (file path, extension, size): only for private or internal repositories on GitHub Team.
- **Required reviewers by team:** not available on user-owned repositories, which have no teams.
- **Commit metadata rules and the Evaluate mode:** documented for GitHub Enterprise.
- **Code scanning, code quality, secret scanning, deployments, merge queue:** not set up for this project.

## Import the ruleset (once)

1. Open the repository on GitHub, then **Settings**.
2. In the sidebar, under "Code, planning, and automation", click **Rules**, then **Rulesets**.
3. Open the **New ruleset** menu, then click **Import a ruleset**.
4. Choose `.github/rulesets/protect-main.json`, review the rules, then click **Create**.

Optional: in the ruleset, under the required checks, you can pick **GitHub Actions** as the source of
`check`, `docker` and `allowlist-review`, so a status set by anything else does not count.

When this file changes, edit the ruleset in Settings to match, or delete it and import the file again. If you
imported it before `allowlist-review` was added, add that check to the ruleset.

## Verify

1. `https://github.com/AmitBisht14/Chat2Cart/rules` lists `protect-main` as active on `main`.
2. Only once step 1 shows the ruleset active (otherwise the push lands on `main`), check that a direct
   push to `main` is refused:

```bash
git commit --allow-empty -m "test: direct push" && git push origin HEAD:main
```

   Then drop the test commit locally with `git reset --hard origin/main`.
3. `git push --force origin HEAD:main` and deleting `main` are refused.
4. A pull request cannot be merged while `check`, `docker` or `allowlist-review` is red, missing or running, or while the branch
   is behind `main` (GitHub shows **Update branch**).

## How changes reach `main`

1. Work on a branch, push it, and open a pull request.
2. Wait for `check`, `docker` and `allowlist-review` to pass. If `main` has moved, click **Update branch** (or
   `gh pr update-branch`) and wait again.
3. Resolve every review conversation, then **Squash and merge**.

`scripts/story-runner.sh` follows the same path: after opening the pull request it waits for the checks,
runs `gh pr update-branch` when the pull request is behind `main` (at most 3 times), and then squash-merges.
A failing check stops the runner and leaves the pull request open.

## Allowlist changes

`agent/src/chat2cart/swiggy/allowlist.py` is the list of Swiggy tools the code may call, and every change to
it needs the owner's review. GitHub cannot require a reviewer for one file here: team-based required
reviewers are not available on user-owned repositories, a pull request's author cannot approve it, and push
rulesets need a private Team repository. Instead the `allowlist-review` CI job fails on any pull request that
changes the file, until the owner adds the label `allowlist-approved`. Adding or removing the label re-runs
the job.

Only the owner adds the label, after reading the diff. The automation acts under the owner's account, so
GitHub cannot tell who added it; the rule lives in `CLAUDE.md` and the story runner instructions. A gate
GitHub enforces by identity needs the automation to run as a separate GitHub account with no bypass.

The first time it is needed, create the label under Issues > Labels > New label.

## Emergency switch

To get past the ruleset in an emergency, set its enforcement to **Disabled** in Settings (it is kept, not
deleted), make the change, and set it back to **Active**.

## Troubleshooting

- **A required check stays "Expected".** GitHub names a workflow check after its job name. Renaming a job in
  `ci.yml`, or skipping a job on some pull requests (for example with path filters), leaves the check
  missing and blocks the merge. Keep both jobs running on every pull request.
- **Merge blocked with no red check.** The branch is behind `main`, or a review conversation is open.
- **Which rules apply?** Anyone with read access can see them at `/rules`, or in the merge box of the
  pull request.
- **Who was blocked or bypassed?** Settings > Rules > Insights lists passed, failed and bypassed actions.
