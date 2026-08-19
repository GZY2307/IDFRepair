# Airport Occupancy V3.1 — Public Safety Audit

Status: `PASS_ALLOWLIST_AND_CONTENT_SCAN`

The review package is built from an explicit, sorted file allowlist. Every
member must be a regular file under the V3.1 documentation/report directories
or the generic Airport ABM source, script, test, and packaging directories.

The package builder rejects:

- OSM, IDF, EPW, SQL/database, EnergyPlus raw-output, drawing, key, archive,
  and compressed-agent suffixes;
- absolute user-home paths and Windows user paths;
- exact private room identifiers and the private source-model name;
- common private-key, GitHub/API token, cloud access-key, and credential
  assignment patterns;
- symlinks, traversal paths, duplicate members, non-regular members, and files
  absent from the allowlist.

The included reports contain aggregate People, sizing, EnergyPlus, AirLoop,
and function results only. AirLoop names use public aliases. The package does
not contain source or derived models, weather, raw SQL, raw agents, exact room
mapping, coordinates, drawings, server configuration, or credentials.

Private integration tests use explicit environment variables. A fresh clone
without private data runs the synthetic/public suite and skips only those
integration checks; supplying authorized local inputs enables them without
embedding a workstation path in public source.
