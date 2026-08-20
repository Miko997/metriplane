# Bounded MassRobotics AMR offline-replay adapter

This isolated package converts one frozen, Metriplane-authored synthetic
MassRobotics-format scenario into External Source Contract v1 fixtures. It is
not a generic importer, live transport implementation, conformance claim, or
safety implementation.

The package accepts only the two included complete-snapshot variants. It uses
strict UTC timestamps, an operator-configured metre-to-metre identity binding,
one expected planar datum, exactly two current-location records per timestamp,
and no carry-forward, interpolation, resampling, prediction promotion, or
cross-datum transform. Upstream MassRobotics artifacts are reference-only and
are not packaged.

## Commands

From this directory:

```console
uv sync --frozen --extra test
uv run metriplane-massrobotics-amr inspect --source-root source/incident
uv run metriplane-massrobotics-amr convert \
  --source-root source/incident \
  --config config/frozen-config.json \
  --adapter-commit "$MET55_COMMIT" \
  --out /tmp/met55-incident-conversion
uv run metriplane-massrobotics-amr finalize-equivalence \
  --conversion-root /tmp/met55-incident-1 \
  --conversion-root /tmp/met55-incident-2 \
  --conversion-root /tmp/met55-incident-3 \
  --conversion-root /tmp/met55-control-1 \
  --conversion-root /tmp/met55-control-2 \
  --conversion-root /tmp/met55-control-3 \
  --out /tmp/met55-portable-fixtures
```

`convert` and `finalize-equivalence` are atomic and fail closed when the output
path already exists. The converter does not read expected outcomes and does not
access the network.

## Development

```console
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv build
```

The public mapping and reproduction notes live at
`docs/specs/massrobotics-amr-offline-replay-profile-v1.md` and
`proofs/massrobotics-amr-offline-replay-v1/REPRODUCE.md`.
