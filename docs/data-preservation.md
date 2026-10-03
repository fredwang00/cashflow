# Household finance data preservation

Last checked: September 23, 2026. This document records the first verified NAS backup and the intended long-term policy. Scheduled backups, offsite storage, and migration to the personal Mac mini are **not yet configured**.

## What exists today

| Location | Contents and status |
|---|---|
| Work MacBook Pro: `~/.cashflow/cashflow.db` | Current authoritative SQLite database. Continue edits here until a deliberate cutover. |
| Work MacBook Pro: `~/.cashflow/imports/` | Archived source exports, import audit records, and before/after import databases. These are on the same machine as the working database. |
| Synology DS1525+: `cashflow` share | Separate backup destination. Encryption, Btrfs data checksums, and Recycle Bin enabled in the setup screenshots. Mounted as `fwang` over SMB. |
| NAS: `backups/backup-20260923T215047Z/` | First completed backup: `cashflow.db`, `imports/`, `RESTORE.txt`, and `SHA256.json`. All 44 manifest-listed files were verified by checksum after copying. The database was copied back to a temporary local directory and passed SQLite integrity and foreign-key checks. |
| GitHub repository | Application code and documentation only. The database is outside the repository and `*.db` is ignored. GitHub is not a financial-data backup. |

Connect using Finder → Command-K → `smb://192.168.1.205/cashflow`. The verified mount was `/Volumes/cashflow`; verify the actual mount each time rather than assuming that path still points to the NAS. The address may change if it is not reserved in the router.

The first backup captures the database at the snapshot time, not subsequent categorization. It verified file recovery and database structure, not a full application restore on the personal mini. NAS drive redundancy/RAID configuration, scheduled NAS snapshots, recovery-key storage, and offsite backups have not been verified.

## Target: one working database, independent recovery copies

| Copy | Intended role | Failure it helps recover from |
|---|---|---|
| Personal Mac mini M4, internal SSD | Sole working database; local dated snapshots for quick rollback | Import or categorization mistakes; local snapshots do not cover loss of this Mac |
| Synology, versioned backup folders | Independent device containing completed database snapshots and source archives | Mac loss or SSD failure; older versions help reverse bad edits |
| Encrypted offsite backup | Versioned copy outside the home, preferably via Synology Hyper Backup to a supported cloud destination | Theft, fire, or loss of both Mac and NAS |
| Optional disconnected external drive | Periodic encrypted copy, disconnected afterward and preferably stored elsewhere | Additional recovery route if online copies or accounts are compromised |

The MacBook Air M4 should access the mini through SSH for CLI work. Do not maintain independently editable databases on both machines or open the live SQLite database over SMB. Synchronize completed backup files only. SQLite documents [network filesystem risks](https://www.sqlite.org/useovernet.html).

NAS disk redundancy keeps a system available through some disk failures; it does not preserve old versions or provide an offsite copy. Multiple folders, disks in one array, or snapshots on that same NAS still share a failure domain. The target is a working copy plus NAS and offsite backups, following the intent of [3-2-1 protection](https://global.download.synology.com/download/Document/Software/WhitePaper/Os/DSM/All/enu/backup_solution_guide_enu.pdf). An Air copy kept in the same home is useful but does not fulfill the offsite role.

## What to preserve

- **Entire SQLite database:** transactions, income, merchant rules, categories, annotations, reimbursements, relationships, and other application state. Reimporting CSVs alone cannot recover manual decisions.
- **Original exports and statements used for reconciliation:** preserve filenames, account distinctions, and file contents. Archive each new download batch before editing or importing it; the initial backup covers the archived `imports/` tree, not every financial file in Downloads.
- **Import evidence:** manifests, reconciliation notes, and before/after snapshots needed to explain corrections. Store personal transaction details in private backup storage, not repository documentation.
- **Recovery context:** application Git commit, snapshot timestamp in UTC, database schema version if available, file checksums, and restore instructions. Future automated backups should record these; the first backup has timestamp, checksums, and brief restore instructions but no dedicated application-version manifest. Application commit at backup creation: `1b967f9`.
- **Keys and credentials separately:** personal password manager plus a recoverable copy independent of the NAS. Do not add secrets or encryption keys to Git or the backup folder they unlock.

## Snapshot procedure

Here, a database snapshot means a consistent SQLite backup file. A Synology/Btrfs filesystem snapshot is an additional layer, not a substitute for this procedure.

1. Pause imports and categorization while assembling a recovery bundle, so its database and import records describe the same completed work. Use SQLite's [online backup API](https://www.sqlite.org/backup.html), such as Python's `Connection.backup()`, to write a new local database file. Do not copy a live database file with Finder or `cp`; transaction journals/WAL may contain required state.
2. Check the local snapshot with `PRAGMA integrity_check` (must return `ok`) and `PRAGMA foreign_key_check` (must return no rows). Archive source files and recovery context beside it. Generate a SHA-256 manifest covering every payload file.
3. Verify that the destination is the expected mounted NAS share. If it is missing, locked, or unreachable, retain the local snapshot and report failure. Never create a local `/Volumes/cashflow` directory as a fallback or report a local-only copy as NAS success.
4. Copy the bundle into a new `.incomplete-backup-<UTC timestamp>` folder on the NAS. Use a unique name and never overwrite an existing completed backup. Reread every destination file and verify its checksum against the local manifest; check for missing or unexpected payload files.
5. Copy the NAS database back to a fresh local temporary directory and repeat the integrity and foreign-key checks. Rename the NAS staging folder to `backup-<UTC timestamp>` only after verification. Consumers must ignore `.incomplete-*` folders.
6. Record destination, completion time, verification result, and source snapshot time. Only then consider retention cleanup. A failed run must leave prior good backups intact.

The September 23 backup followed the SQLite backup, checksum, local restore-check, and staged-publication steps. The temporary script used for it is not an installed backup command; repeatable automation remains to be implemented.

## Schedule and retention policy to implement

| Trigger or tier | Proposed retention |
|---|---|
| Before each import, reconciliation repair, migration, or bulk category/rule change | Keep for 90 days; pin snapshots associated with unresolved issues |
| After each completed finance session | Keep for 90 days; this protects manual categorization that happens after imports |
| Daily scheduled snapshot on the mini | Keep the latest successful backup for each of 30 days |
| Monthly close | Keep one verified snapshot per month for 24 months |
| Year-end close | Keep one verified snapshot per year indefinitely, reviewed annually |
| Original exports and reconciliation records | Preserve indefinitely for now; this is a household workflow choice, not a legal/tax retention determination |

Retention tiers overlap: keep a backup if any tier or explicit pin requires it. Never delete the last verified backup. Preserve independent version history offsite so deletion or corruption on the NAS does not immediately remove recovery options everywhere. Start with no automatic pruning until NAS and offsite restores have both been tested.

The intended recovery point is the latest completed finance session, or at most one day of work once daily automation is healthy. This is a target, not a current guarantee. During active use, flag a missing daily success after 24 hours, retry when connectivity returns, and show separate local, NAS, and offsite success times. A job exit code or an available NAS is not evidence of a successful backup.

## Offsite protection, access, and power loss

Use a versioned Hyper Backup task for the `cashflow` share with client-side encryption and a separate destination account. Choose the destination after checking current support and cost; no provider or subscription has been selected. Hyper Backup supports multiple destinations and versioned recovery; its multi-version archives require Hyper Backup, Hyper Backup Explorer, or Hyper Backup Vault to restore. Include that recovery tool in the restore drill. See [Synology's specifications](https://www.synology.com/en-my/dsm/7.2/software_spec/hyper_backup).

Shared-folder encryption on the NAS and offsite backup encryption are separate settings. Do not assume copying files out of an unlocked encrypted share keeps them encrypted at the destination. Save both sets of recovery material outside the NAS; Synology describes [client-side backup encryption](https://blog.synology.com/hyper-backup-encryption-technologies-explained/).

Keep unrelated NAS users and services without access. When automating, use a dedicated backup account scoped to the required share. Encryption protects stored data but does not stop an authenticated writer from deleting it. Consider protected NAS snapshots and offsite immutability later, after verifying support for this encrypted share and testing retention settings.

After a NAS restart or power outage, verify that the encrypted share is unlocked, SMB is available, and backup jobs resume successfully. Decide and test the key-management/unlock policy before relying on unattended jobs. Consider a compatible UPS with graceful shutdown for the NAS and mini; it complements backups and does not replace them.

## Restore and migration procedure

1. Select a completed backup from before the problem. Keep the original backup untouched and verify its payload against `SHA256.json`. For offsite archives, first recover the bundle using the backup product and its independently stored key.
2. Restore into a new local directory on a personal Mac. Run the SQLite integrity and foreign-key checks there. Never test by opening the NAS copy as the working database.
3. Install the recorded application version and use `cashflow --db /absolute/path/to/restored/cashflow.db status` to inspect the restored copy. The CLI may initialize or migrate a database, so use a disposable verification copy when checking an older backup. Compare transaction/income counts, date coverage, and several known categories, tags, and reimbursements with the backup's recovery notes or known records.
4. Stop all cashflow CLI/dashboard writers on the old machine. Take a final snapshot. Preserve the complete existing `~/.cashflow` directory before replacement, including any journal/WAL files; do not mix an old journal with a restored database.
5. Place the verified database and import archive into a fresh `~/.cashflow` on the mini. Verify normal CLI/dashboard behavior and make a new NAS backup. From this point, the mini is the only writer; do not continue editing the old Mac's database.
6. Test recovery from the NAS and then from offsite on a separate machine. Record the backup used, date, result, and time required. Repeat quarterly and after storage, encryption, or application migration changes.
7. Only after successful cutover and recovery testing, remove household financial files from the work Mac according to employer policy. Include Downloads, temporary staging folders, and local archives in the inventory; copying the database alone does not remove those files.

## Next actions

- [x] Create a dedicated encrypted NAS share and verify the first backup and database restore check.
- [ ] Take another snapshot after the next categorization session.
- [ ] Migrate the sole working database to the personal mini and verify the application there.
- [ ] Implement the snapshot procedure with daily/session triggers, failure reporting, and retention safeguards.
- [ ] Configure an encrypted, versioned offsite destination and test recovery without access to the original NAS.
- [ ] Test restart/unlock behavior and decide whether to add a UPS and disconnected backup drive.

The monthly operating routine is in [household-sync.md](household-sync.md).
