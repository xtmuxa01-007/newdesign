# Newdesign — independent source copy

Repository: `xtmuxa01-007/newdesign`, branch `main`.

This source snapshot was authorized on 2026-11-12. It is separate from
`xtmuxa01-007/marva` (TIN CRM — Marwa Company) and its production database.
Application source and tests are copied unchanged, with normal Git line endings.
The copy has additional ignore rules for private data and operational files.

Databases, environment secrets, SSH keys, uploads, integration settings,
personal Telegram recipient configuration, generated packages and preview
artifacts are excluded. Synthetic demo data can be generated using
`scripts/seed-local-demo.py`; see `docs/LOCAL_DESIGN_DEMO.md`.

The original production deployment workflows are intentionally excluded.
Historical documentation and manual release/Telegram configuration scripts
still describe the original Marva system: do not run them for this repository.
Uploading this code does not authorize deployment, releases or production data
access. Keep desktop and legacy sync disabled unless separately authorized.

No original project files, Git remotes, VPS services or databases were changed
to create this copy.
