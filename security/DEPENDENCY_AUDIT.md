# Dependency and supply-chain audit

## Detected stack

Backend: Python 3, FastAPI, Starlette, Uvicorn, Pydantic, Argon2, PyYAML, psutil, multipart parser, SQLite from Python standard library. Frontend: React 19, TypeScript, Vite 7, highlight.js and Recharts. No container/base image, Rust/Go app, or native application package was found. Tailscale and system packages are host dependencies.

Python versions are pinned in `requirements.lock.txt`; ranges are in `requirements.txt`. Frontend direct and transitive versions are pinned by npm lockfile. Full `npm audit --prefix frontend --json` on 2026-10-24 reported 0 vulnerabilities across 112 resolved dependencies (including development and optional packages); the production-only audit also reported zero. The raw full report is in [npm-audit-report.json](npm-audit-report.json). No upgrades were performed.

Python advisory scanning (`pip-audit`), SBOM, license/provenance scan, Semgrep/Bandit, Gitleaks and OS package advisory checks were not available or run. No secrets were intentionally printed; repository ignores `.env`, venv, data and build artifacts. This is not a formal secret scan. Tailscale host version 1.104.2 was observed; update availability was not compared to vendor release channel. Debian/custom kernel update provenance was not verified.

Recommended: run `pip-audit -r requirements.lock.txt` and a secret scanner in CI; generate CycloneDX SBOMs for npm/Python; pin direct dependencies and review lockfile changes; verify Debian and Tailscale updates through signed vendor repositories before maintenance windows.
