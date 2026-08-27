# Active test suite

This directory contains only tests accepted into the current reliability
baseline. The superseded suite is preserved unchanged in
`developer/old-tests/` as a source of behavior and fixtures; it is not
collected by pytest.

Run the current pre-push baseline from `floability-env`:

```bash
pytest tests -m "not release"
```

Run all currently implemented tests:

```bash
pytest tests
```

The future release suite will include explicitly marked real-network and local
backpack tests. It must remain opt-in during ordinary development. See
`.devdocs/testing-plan.md` for the staged design.
