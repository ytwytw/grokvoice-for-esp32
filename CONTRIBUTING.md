# Contributing

Small fixes, clear docs and offline regression tests are welcome. Describe the
problem in an issue before proposing a large change. For a pull request, use a
branch, explain the behavior change and include the checks you ran.

Use Python 3.12 and the setup commands in [the gateway guide](docs/gateway.md).
Run `python -m unittest discover -s tests -v` and `python -m pip check`.
Keep changes small and follow the surrounding Python and YAML style. Add a test
for a behavior fix. Use fake devices and providers in tests.

Firmware changes need the separate environment, generated tones and
`esphome config firmware/voice-pe.yaml` described in
[the build guide](docs/build-and-run.md). Configuration validation does not prove
a firmware compile or a real conversation works. State which checks you skipped.

Keep credentials, account data, recordings, device identifiers and local network
details out of commits, screenshots and issues. See [SECURITY.md](SECURITY.md).
Preserve upstream notices. Contributions to the project's own code are under
[Apache-2.0](LICENSE).

Agent-assisted changes follow [AGENTS.md](AGENTS.md); `CLAUDE.md` links to it.
Review generated changes and verify commands before submitting them.
