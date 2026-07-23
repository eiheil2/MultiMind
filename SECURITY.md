# Security Policy

## Supported Versions

The MultiMind project is actively maintained on the latest released version.
Security fixes are backported to the most recent minor release line when
feasible. The table below summarises which versions currently receive
security updates:

| Version | Supported          | Notes                                   |
|---------|--------------------|-----------------------------------------|
| 0.1.x   | :white_check_mark: | Current development / initial release   |
| < 0.1   | :x:                | Pre-release, not supported              |

A new minor version is considered supported until **two** newer minor
versions have been released, or for **6 months**, whichever is longer.

---

## Reporting a Vulnerability

The MultiMind maintainers take security bugs seriously. We appreciate your
efforts to responsibly disclose your findings, and we will make every effort
to acknowledge your contributions.

### How to report

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report vulnerabilities privately using **one** of the following
methods, in order of preference:

1. **GitHub Security Advisories (preferred)**
   Navigate to the repository's **Security** tab and select
   **Report a vulnerability**. This creates a private advisory visible only
   to repository maintainers.

2. **Email**
   Send a description of the vulnerability to the security team at
   **security@multimind.dev** (PGP key fingerprint published in the
   repository's `.well-known/` directory). Please encrypt sensitive
   details if possible.

### What to include

To help us triage and reproduce the issue quickly, please include:

- A clear description of the vulnerability and its potential impact.
- The affected version(s) and the environment (OS, Python version).
- Step-by-step instructions or a minimal proof-of-concept to reproduce.
- Any relevant logs, stack traces, or screenshots (redact secrets first).
- Your suggested mitigation or fix, if you have one.

### Response timeline

We aim to acknowledge all reports within **48 hours** and to provide an
initial assessment within **5 business days**. The general process is:

1. **Acknowledgement** — We confirm receipt and assign a tracking ID.
2. **Triage** — We assess the severity and scope of the issue.
3. **Investigation & Fix** — We develop and verify a patch.
4. **Coordinated Disclosure** — We publish a Security Advisory and a patched
   release, crediting the reporter unless they prefer to remain anonymous.

Reporters are kept informed at each stage and may be invited to review the
fix before public release. We kindly request that you do not disclose the
vulnerability publicly until a fix has been released.

---

## Sensitive File Handling

MultiMind integrates with multiple AI providers and may handle credentials,
API keys, session tokens, and conversation history. The following rules
govern sensitive data within the project and its runtime.

### Secrets in the codebase

- **Never commit secrets.** API keys, tokens, passwords, and `.env` files
  are excluded via `.gitignore` and must never appear in source code,
  tests, or documentation.
- **Environment variables** are the preferred mechanism for providing
  credentials at runtime. Load them through `python-dotenv` or the host
  environment — never hard-code them.
- **Example/template files** (e.g. `env.example`) must contain only
  placeholder values such as `your-api-key-here`.

### Runtime data

- The `.multimind/` directory stores local state (memory, cache, logs, and
  session data). It is **git-ignored** and must never be committed.
- Conversation history and memory contents may contain user-supplied
  sensitive information. MultiMind does not transmit this data beyond the
  configured AI providers.
- Browser-login channels store authentication cookies locally. Treat these
  files as sensitive credentials and ensure appropriate filesystem
  permissions (`0600`).

### Reporting leaked secrets

If you discover that a secret has been accidentally committed to the
repository:

1. **Do not open a public issue.** Use the private reporting channels above.
2. Assume the secret is compromised — rotate or revoke it immediately.
3. Provide the commit hash or file path so maintainers can purge it from
   history.

Maintainers will remove the secret from the current tree and, where
appropriate, rewrite public history using `git filter-repo`. Even after
removal, **any secret exposed in a public commit must be considered
compromised and rotated**.

---

## Scope

This policy applies to the MultiMind core project and its officially
maintained adapters. Third-party plugins, forks, or community-maintained
integrations are out of scope unless they are hosted within the
`multimind` GitHub organisation.

The following are **out of scope** for vulnerability reports:

- Vulnerabilities in upstream dependencies (report them upstream).
- Self-XSS or issues requiring the user to attack themselves.
- Theoretical issues without a concrete attack vector.
- Social engineering or physical attacks.
- Issues in third-party AI providers' own services.

---

## Acknowledgements

We thank all security researchers and community members who responsibly
disclose vulnerabilities. Confirmed reporters are acknowledged (with
consent) in our release notes and Security Advisories.
