# Incident inc_0001

- **Rule:** `cart_person_distance`
- **Severity:** critical
- **Status:** closed
- **Run:** `INC-DIST-001`
- **Opened:** 2.0
- **Closed:** 2.0
- **Duration:** 0.0 s
- **Objects:** cart_01, human_proxy_01
- **Zones:** main

## Summary

cart_01, human_proxy_01 triggered cart_person_distance in main for 0.0s

## Evidence

- Alerts in this incident: 1
- Total alerts recorded: 1
- Session excerpt frames: 3

## Reproduce

```bash
./replay.sh
```

This re-runs incident detection over the bundled session excerpt and
verifies the incident reproduces and all checksums match.
