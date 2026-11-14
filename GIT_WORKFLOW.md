# Git workflow between whiskey and zbook9

Source is maintained on `develop`. Runtime environments, recordings, database
backups, models and credentials remain machine-local and are excluded from Git.
The implementation and its tests are committed together; field notes and selected
small validation reports are versioned as evidence, not runtime inputs.

## Locations

- Whiskey checkout: `/home/sl/work26/sprinttimer/racevideo`
- Whiskey bare origin: `/home/sl/work26/sprinttimer/racevideo.git`
- Laptop checkout: `/home/sl/racevideo`
- Whiskey's `zbook9` remote: `sl@zbook9:/home/sl/racevideo`
- Laptop's `origin`: `sl@whiskey:/home/sl/work26/sprinttimer/racevideo.git`

Git SSH must disable X11 forwarding (`git -c core.sshCommand="ssh -x" ...`).
The laptop origin requires laptop-to-whiskey SSH access. Fetching the laptop from
whiskey works independently of that reverse connection.

## Bring laptop changes home

On zbook9, inspect the diff and explicitly stage only intended source changes:

```sh
cd ~/racevideo
git status --short
git diff
git add path/to/changed-file.py CODEX_HANDOFF.md
git commit -m "Describe the concrete fix and resulting behavior"
```

Then on whiskey:

```sh
cd /home/sl/work26/sprinttimer/racevideo
git -c core.sshCommand="ssh -x" fetch zbook9
git log --oneline develop..zbook9/develop
git diff develop...zbook9/develop
git merge --ff-only zbook9/develop
git push origin develop
```

If branches diverge, review and merge/rebase deliberately; do not force-reset
away laptop edits. Laptop commits can also be pushed to a separate branch of
origin when reverse SSH is available. Do not push directly to the laptop's
checked-out `develop` branch.

## Deploy a committed archive

Run tests in `.venv`, commit, and push origin before making an archive:

```sh
git archive --format=tar --output=/tmp/racevideo-source.tar HEAD
git bundle create /tmp/racevideo-history.bundle develop
sha256sum /tmp/racevideo-source.tar
```

Transfer the tar and bundle to a versioned deployment directory on zbook9. Before
extracting, compare against the previous deployed revision, preserve any laptop
changes, and retain a source-only backup. Fetch the bundle to obtain the exact
commit/history. Extract only the archive's source files into the checkout and
set the index/branch to that same commit; verify `git status` is clean afterward.
The first deployment initializes Git metadata without replacing the checkout,
so existing environments and local data remain in place.

An archive intentionally contains no `.git` directory. The paired bundle supplies
history for the laptop checkout; an archive alone cannot support committing and
fetching changes back. Never extract an unreviewed archive over dirty source.
Never archive runtime data or delete destination extras to make the source match.

GUI, recorder and service processes are not automatically restarted by deploying.
Check active capture before any restart. Validation of source and unit tests does
not establish physical camera/OCR/timing accuracy during a race.
