# Runtime resources

Metriplane installs immutable dashboard assets, two bundled configuration examples, the existing camera-free Atlas demo inputs, and the six operator tool modules used by the local runner. Runtime code resolves these through `importlib.resources` or Python module execution; it does not discover them by walking back to a source checkout. Camera-backed `--live` startup requires an explicit `--config` path.

The dashboard serves immutable package assets separately from generated Atlas output under the resolved platform data directory. An alternate operator Python is accepted only when it can import the exact installed operator module it is asked to execute.

`docs/status/runtime-resource-registry.json` is the exact governed classification. Every tracked member of `web/dashboard`, `configs`, and `calib`, plus the bounded Atlas demo dataset, is recorded as one of:

- installed immutable data;
- an already-installed demo resource;
- explicit caller configuration;
- explicit site calibration input; or
- source-only documentation.

Regenerate the registry with:

```console
python tools/check_runtime_resources.py write --repository-root .
```

Check currentness without modifying the checkout with:

```console
python tools/check_runtime_resources.py check --repository-root .
```

Adding, removing, or changing a governed resource without updating its installed copy or explicit-input classification fails the check. Site calibration under `calib/` is never silently replaced by a packaged default.
