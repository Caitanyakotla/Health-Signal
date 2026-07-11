# HealthSignal CI Pipeline Reference

One workflow: `.github/workflows/deploy.yml` — **"Security Scan Only"**.

Triggers: push to `main` / `dev`, pull requests to `main`, and manual
`workflow_dispatch`.

## Jobs

| Job id | Display name | Tool | Purpose |
|---|---|---|---|
| `secret-scan` | Secret Scanning (Gitleaks) | `gitleaks/gitleaks-action@v2` | Detect committed secrets |
| `sast-scan` | SAST Code Scan (Bandit) | Bandit via pip | Python static security analysis; uploads `bandit-security-report` artifact |
| `container-scan` | Container Scan (Trivy) | `aquasecurity/trivy-action` | Builds the Docker image locally, scans it for vulnerabilities; uploads `trivy-container-report` artifact |
| `sbom-generate` | SBOM Generation (Syft) | Syft | Builds the Docker image, generates SPDX and CycloneDX SBOMs |

## Usual failure classes

- **secret-scan**: a real or false-positive secret in the diff. Never rewrite
  git history to fix it. Remove/rotate the secret in a new commit, or add a
  documented Gitleaks allowlist entry for a confirmed false positive.
- **sast-scan**: Bandit findings in changed Python code. Fix the flagged
  code; use a targeted `# nosec` comment with a justification only for a
  confirmed false positive.
- **container-scan / sbom-generate**: usually a broken `Dockerfile` (bad base
  image tag, failing build step) or a vulnerable base image. Both jobs build
  the image first, so a Dockerfile error fails both at once.
- **Any job**: pinned action version problems (`uses: ...@vN`) after
  upstream changes, or runner/network flakes — flakes are transient, so
  recommend a rerun instead of a code change.
