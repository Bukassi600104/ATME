# ATME MCP/Desktop project-view inconsistency

Status: Resolved in source; packaged acceptance pending

Observed: 2026-09-14 (Africa/Lagos)

## Summary

The running ATME desktop HTTP sidecar and the concurrently running stdio MCP sidecar returned different project lists. No project or media mutation was performed during this diagnosis.

## Shared configuration

- Executable: `C:\Users\USER\AppData\Local\ATME\atme-sidecar.exe`
- Intended database: `C:\Users\USER\AppData\Roaming\dev.atme.engine\jobs\jobs.db`
- Desktop process: `atme-app.exe` PID 28056
- Desktop HTTP sidecar: PID 28888, parent PID 28056, port 49276
- MCP stdio sidecar: PID 29964, launched with `mcp --database C:\Users\USER\AppData\Roaming\dev.atme.engine\jobs\jobs.db`

Process IDs and the desktop port are observational and will change between launches.

## Conflicting results

The stdio MCP `atme_list_projects` call succeeded but returned an empty list.

The authenticated desktop HTTP endpoint `GET /projects?limit=100` returned:

- Project ID: 1
- Title: `Test`
- Project revision: 6
- Profile: `LONG_FORM_16_9`
- Status: `draft`
- Source timeline revision: 3
- Latest timeline operation: `move_position`

The desktop endpoint `GET /projects/1/media` returned:

- Media ID: `95c7f7fd93e94caaab614a404e7d68ff`
- Name: `Untitled_Video.mp4`
- Kind/format: video/MP4
- Duration: 284,757 ms
- Bytes: 322,256,804
- SHA-256: `a9de01070c30913e474dc8282710e41d8360879063486bd8772002c1cb88be15`

A separate read-only SQLite connection to the intended `jobs.db` saw zero rows in `project_state`, `project_source_media`, and the legacy `jobs` table at the time of diagnosis. This agrees with the MCP result but conflicts with the running desktop sidecar response.

## Root cause

The copied stdio configuration embedded an absolute database path while the installed
desktop independently resolved the installer-selected project directory. Reinstalling or
changing that directory left valid but stale MCP configurations pointing at another store.
Connection status was also inferred from heartbeat rows in that store, so it could not
prove contact with the running desktop instance.

The packaged MCP command now omits the database path and resolves the current Windows ATME
configuration at launch. A separate authenticated loopback bridge reports connect,
initialize identity, heartbeat, tool activity and disconnect directly to the running desktop.
Database activity alone is explicitly tested not to produce a connected status.

## Follow-up acceptance checks

1. Add a read-only diagnostics response to both HTTP and MCP that reports the resolved database path, canonical file identity where available, journal mode, schema/version marker, and a non-sensitive instance/session ID.
2. Compare those diagnostics while both sidecars are running.
3. Verify database, WAL, and SHM file identities and modification times without restarting either process.
4. Create a disposable project through MCP and confirm the open desktop lists it automatically.
5. Create a disposable project through the desktop and confirm MCP lists it immediately.
6. Repeat after restarting each sidecar independently.
7. Confirm that fixing synchronization does not merge or overwrite divergent project stores silently.
