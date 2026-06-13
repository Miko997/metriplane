# Object Registry

The object registry maps raw marker IDs into named physical assets. It is the
bridge between camera-derived state and operator-readable incidents.

## Example

```yaml
objects:
  "1":
    object_id: cart_01
    type: cart
    label: Cart 01
    tags: [movable_asset]
  "2":
    object_id: worker_02
    type: human_proxy
    label: Worker proxy
    tags: [person_proxy]
```

## Runtime behavior

- Missing registry files are allowed only when the caller explicitly permits
  that mode.
- Unknown marker IDs stay valid and resolve to deterministic fallback IDs such
  as `marker_12`.
- Registry data is additive: it enriches object IDs, types, labels, and tags
  without changing the metric position produced by the perception pipeline.

## Related files

- `configs/objects.example.yaml`
- `metriplane/sentinel/registry.py`
- `tests/test_object_registry.py`
- `evidence/experiments/object_registry_001.md`
