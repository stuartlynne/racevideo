# Recording data used for the November 2026 OCR tests

The full verified import is the protected backup:

`data/imports/zbook9/2026-11-09/racevideo-20261109.sqlite3`

It is 175,081,676,800 bytes. Its SHA256 is
`46818cab16a6edeef2ced6d000bc9485a6dcd1eb9f315bf15fb729d85bf44140`.
The source snapshot passed SQLite quick_check, and the local full-file SHA256 and
all 97,535 stored-frame counts were verified. See the adjacent snapshot manifest
and `verified-local.json`. The backup database has write permission removed.

A separate full working copy is available at:

`data/field-tests/2026-11-08/racevideo.sqlite3`

The adjacent `working-copy.json` records successful copying, matching size/counts,
and a verified writable transaction. A second full SHA256 was not computed for
the writable clone. Tests that write OCR
jobs/results, migrate schema, change settings, delete clips or run VACUUM must use
that working copy, never the backup. Read-only diagnostics may read the backup
using SQLite `mode=ro`; keep their outputs in separate directories.

The 14-clip `field-sample.sqlite3` is a derived test fixture, not the complete backup.
The source database and snapshot on zbook9 are also retained. Do not automatically
remove any full backup as part of experiments or test cleanup.

## November 10 zbook9 cleanup recovery check

Following an accidental-cleanup concern, the zbook9 review GUI was stopped to
abort any possible pending transaction. The database was compared read-only with
the protected laptop export. No original capture IDs/metadata or source-frame
index/timestamp records were missing: all 877 captures and 97,535 frames remained.
There were no pending writer transactions and no free pages from a bulk deletion.
This verifies record presence/metadata, not a fresh full-file hash of JPEG bytes.

The current database's nine operator reviews were retained. An additional
consistent metadata-only recovery copy was saved at
`/home/sl/racevideo/data/recovery/20261110-000402/metadata-before-recovery.sqlite3`.
The full original video backup remains separate and protected. No database
replacement was necessary or performed. The last GUI snapshot had bib filter
`32` active; reopening without that filter restores the full date's thumbnail list.

The main-toolbar cleanup button has been removed. Permanent deletion now requires
the Maintenance menu, a concrete preview and exact typing of `DELETE DATE COUNT`
before the delete action is enabled. See REVIEW.md.
