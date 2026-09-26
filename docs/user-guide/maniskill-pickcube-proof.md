<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube proof

The repository contains a bounded, versioned proof candidate for one frozen
ManiSkill PickCube episode. It separates the pinned source and adapter
derivation from Metriplane's owner-configured planar rule, incident evaluation,
evidence bundle, and generated regression.

Start with the
[proof landing page](https://github.com/Miko997/metriplane/blob/agent/maniskill-pickcube-proof-v1/proofs/maniskill-pickcube-v1/README.md).
The branch link is a review-time location, not a stable publication URL. The
landing page remains `NOT READY` until explicit owner approval, merge, proposed
tag creation, and final URL verification.

For an outside evaluation, use the proof's `REPRODUCE.md` and `EVALUATOR.md`.
The fast path evaluates the checked-in portable fixtures from an installed
wheel without ManiSkill or simulator dependencies. The advanced path audits
the frozen source conversion on its recorded Linux environment.

The proof is limited to one position-only episode, one adapter, one rule set,
and exact software identities. It does not establish official PickCube task
success, physical accuracy, simulator realism, sim-to-real validity, safety,
production readiness, ManiSkill endorsement, or general ManiSkill support.

The historical proof always checks out the exact candidate source, including its
recorded adapter dependency lock. The portable proof builds the recorded root
candidate wheel and replays candidate-bound normalized fixtures; it does not install
the adapter lock. The current adapter source, configuration, fixtures, and proof
documents remain byte-bound to that candidate. Only the current checkout's
`adapters/maniskill_pickcube/uv.lock` is excluded from the cross-commit identity
comparison so security-only dependency maintenance can advance without rewriting the
retained proof. The proof workflow still runs for every lock change, and the current
lock remains subject to the repository's fail-closed supply-chain scanners.
