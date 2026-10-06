# Public single-server deployment

This is the first deployable shape of the Streamlit research UI: one persistent
server, Google sign-in, private per-user workspaces, and a mounted Docker volume.
It is **not** a Vercel Functions deployment and it does not expose the separate
FastAPI server. The local research mode remains unchanged when
`SYNTHEX_PUBLIC_MODE` is unset.

## Before launching

1. Provision a Linux server with Docker Compose, a persistent encrypted disk,
   public DNS for your domain, and inbound ports 80/443. Keep one Synthex app
   replica: its JSONL locks coordinate local processes, not distributed hosts.
2. Register a Google OAuth **web application** for that domain. Its authorized
   redirect URI must be exactly `https://YOUR_DOMAIN/oauth2callback`.
3. Copy `.env.example` to ignored `.env`. Set `SYNTHEX_DOMAIN`, an exact
   configured `GEMINI_MODEL`, and the provider keys you intend to fund. Review
   the conservative per-user and global daily action limits. A quota reserves
   an action before the external request; it is not a token or billing cap.
4. Copy `.streamlit/secrets.example.toml` to ignored
   `.streamlit/secrets.toml`. Set the same HTTPS redirect URI, Google OAuth
   client ID/secret, and a long randomly generated cookie secret. Never commit
   either secret file. Configure spending limits with the provider as well.
5. Arrange encrypted off-server backups and test a restore of `synthex_data`.
   Do not use `docker compose down -v`; `-v` removes the named data volume.

With the domain pointed to the server and secrets present:

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Caddy terminates HTTPS and proxies Streamlit's WebSocket connection. The app
itself is not published on a host port. Check
`https://YOUR_DOMAIN/_stcore/health`, then test Google login, upload, archive
save, logout/login, and a second account that cannot see the first account's
papers. Do not enable public traffic until those live checks pass. The OAuth
client registration, DNS, actual keys, and host backups must be supplied by
the operator; repository tests cannot verify them.

## Storage and isolation

The `synthex_data` volume is mounted at `/var/lib/synthex`. Each signed-in
Google account is assigned a directory under `users/` using SHA-256 of its
verified issuer and immutable subject—not email or a user-supplied path. Its
`archive/`, `jobs/`, visual sidecars, and discovery cache are separate. Job
source artifacts can contain uploaded PDFs and raw provider responses, so the
volume and backups are sensitive. A shared `usage/events.jsonl` enforces daily
per-user and deployment-wide extraction/search reservations atomically.
The container build excludes the benchmark corpus and all repository PDFs;
users supply their own papers after signing in. Never copy local research
archives or source/gold locks into the public volume.

The public build hides developer/operator pages even if a developer-mode
environment value is accidentally set. The FastAPI service and its operator
endpoints are **not** started by `compose.yaml`; do not expose that API publicly
without a separate authentication and authorization review. Search-assisted
enrichment inside extraction is disabled in public mode; explicit paper
discovery and gas-sensing search share the daily search allowance.

The defaults are 3 PDFs per batch, 25 MB per PDF, 3 extraction actions per
user/day and 30 globally, plus 10 search actions per user/day and 100 globally.
The limits are server-enforced and configurable through `.env`. They limit
requests, **not provider token spending**. A single-process JSONL volume is a
practical first release, not a multi-replica database. For multiple servers or
higher availability, migrate archive/job metadata to a transactional database
and PDFs/artifacts to private object storage with tenant-scoped access.

## Release boundary

Deploy the reviewed public `main` branch, starting at commit `878dc88`. It
contains the app runtime, deployment files, and research scripts/metadata, but
its new commits add no benchmark corpus PDFs or third-party source-data files.
The separate local `unpublished-corpus-history` and `release-link-only-rc`
branches contain publisher-formatted research material requiring a file-level
redistribution review; do not deploy or push them as a shortcut. Do not copy
benchmark files into the public data volume. Full source-byte benchmark replay
still requires independently obtained files matching the committed hashes.
