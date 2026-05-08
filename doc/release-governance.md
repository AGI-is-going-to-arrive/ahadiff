# Release Governance

## License

AhaDiff is released under the [MIT License](../LICENSE).

## Versioning

Follows [Semantic Versioning 2.0.0](https://semver.org/):
- **MAJOR**: breaking API/contract changes
- **MINOR**: new features, backward-compatible
- **PATCH**: bug fixes

Pre-release versions use PEP 440 suffixes: `0.1.0a0` (alpha), `0.1.0b1` (beta), `0.1.0rc1` (release candidate).

## Release Process

1. All CI gates must pass (`release.yml`):
   - Backend: pytest with `--cov-fail-under=85`, ruff, pyright
   - Graphify performance benchmark
   - Wheel build + install smoke (clean venv)
   - CLI smoke (`--version`, `doctor`, `learn --help`)
   - Windows runtime guard
2. Tag `v{VERSION}` on main branch
3. `release.yml` publishes wheel to PyPI via OIDC

## Commercial Stance

AhaDiff is a **personal, local-first learning tool**. It is free and open-source under MIT.

- No SaaS offering planned
- No telemetry, no data collection
- BYOK (Bring Your Own Key) model — users provide their own LLM API keys
- Per-repo data stays in `.ahadiff/` under user control

## Contribution

Contributions welcome via GitHub pull requests. All contributions fall under the MIT License.

### Code Quality Gates

- Python: ruff + pyright strict, line width 100
- Frontend: TypeScript strict, Vitest + Playwright
- Coverage minimum: 85%
- i18n: en/zh-CN parity enforced

### Multi-Model Review

Production changes require cross-model review (Claude + Codex). Stage gates:
- **GO**: 0 Critical + 0 High
- **CONDITIONAL GO**: 0 Critical + ≤3 High (fix then verify)
- **NO GO**: ≥1 Critical or >3 High

## Security

- Vulnerabilities: report via GitHub Issues (private disclosure preferred)
- Safety model: 7-category UNTRUSTED_DIFF boundary, 3-tier privacy, loopback-only serve
- No secrets in committed artifacts
