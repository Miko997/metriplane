# Object Registry — Phase 01 Evidence

- phase: 01
- feature: object_registry
- module: metriplane/sentinel/registry.py
- command: `metriplane objects validate configs/objects.example.yaml`
- expected: PASS: objects.yaml valid
- command: `metriplane objects list --config configs/objects.example.yaml`
- expected: three lines, one per object (cart_01, pallet_01, human_proxy_01)
- command: `metriplane objects resolve --config configs/objects.example.yaml 7`
- expected: cart_01
- tests: tests/test_object_registry.py
- limitations: config-time catalog only; does not modify live tracking pipeline
