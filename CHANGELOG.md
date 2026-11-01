# Changelog

All notable changes to Corax are recorded in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-11-01

First public release.

### Added

- **Policy:** Generic Rego policy with JWT checks, route matching, ABAC and ReBAC rules, and an `allowed_objects` query for filtered catalogs.
- **AI risk check:** Heterogeneous GraphSAGE model with training, evaluation, hard negative mining and risk threshold calibration. The Corax service exposes the score at `/risk`, and OPA allows a request only when the rules allow it and the risk is not high.
- **Appeals:** Similar case search, candidate rules from narrowest to broadest, blast-radius tiers with configurable limits, Rego validation, live reload in OPA and one-click revoke. Appeal endpoints require an administrator JWT.
- **Access review:** Plain-language rules, who gained access and how it was used, suggested access, and an audit log of every approval, rule and revoke.
- **Deployment:** Docker Compose stack with Envoy, OPA, the Corax service and the demo app, usable as a sidecar or as a policy decision point.
- **Demo:** A document application in React and Tailwind for a company of 180 employees, with employee and administrator views.
- **Scripts:** Dataset converters for CSV, Amazon Access Samples and Xu and Stoller policies, evaluation scripts and demo scripts that run without Docker.
- **Documentation:** Getting started, demo walkthrough, architecture, AI model and evaluation, scripts and references, also published on GitBook.

[Unreleased]: https://github.com/AgileOrc/Corax/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/AgileOrc/Corax/releases/tag/v1.0.0
