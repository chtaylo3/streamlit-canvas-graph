# Contributing

This project currently accepts pull requests only from approved repository
collaborators. Everyone is welcome to open an issue to report a bug or propose a
change. Please avoid including credentials, private repository names, manifests,
dependency snapshots, or other confidential data.

Approved contributors should create a focused branch and run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
cd frontend
npm test
npm run build
npm audit --audit-level=high
```

All contributions are provided under the Apache License 2.0 and must pass the
required repository checks and maintainer review policy.

