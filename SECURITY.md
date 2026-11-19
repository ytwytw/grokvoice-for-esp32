# Security

## Report a vulnerability privately

Use the repository's **Security → Advisories → Report a vulnerability**
option. Do not post exploit details, credentials or account data in a public
issue.

Include the affected version, impact and a minimal reproduction with synthetic
values.

## What never to commit or share

- Wi-Fi passwords, API encryption keys, OAuth tokens, cookies or auth stores.
- `.env`, `firmware/secrets.yaml`, generated firmware or build directories.
- Personal names/emails, device addresses, private hostnames or environment dumps.
- Microphone recordings, raw provider payloads or screenshots containing secrets.

Use placeholders in examples and synthetic fixtures in tests. Before a pull
request, inspect `git diff --cached` and run `gitleaks dir --redact` on a clean
source tree. If a real credential leaks, revoke it promptly; deleting a file
does not remove it from Git history.

The gateway's reply server is plaintext HTTP with temporary random URLs. Keep
it and the device API on a trusted LAN, off the public internet. See
[the gateway guide](docs/gateway.md) for network and account boundaries.
