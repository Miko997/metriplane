# SPDX-FileCopyrightText: 2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Freeze and verify the audited Metriplane v0.3.0 truth baseline."""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import errno
import fnmatch
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tomllib
import unicodedata
import zlib
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn, cast
from urllib.parse import urlsplit

SCHEMA_VERSION = "metriplane.baseline-snapshot.v1"
SCHEMA_DRAFT_URI = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://metriplane.com/schemas/metriplane.baseline-snapshot.v1.schema.json"
EXPECTED_SCHEMA_BYTES = 17_897
EXPECTED_SCHEMA_SHA256 = "97dede4dfad68bca21a46458fa1dadc7b51d1834184d5763b6a76866e3d633b2"
BASELINE_EVIDENCE_VERSION = "metriplane.mp2-000.pre-edit-baseline.v1"
TASK_ID = "MP2-000"
OBLIGATION_IDS = (
    "MP2-000.OBL.PREEDIT_BASELINE",
    "MP2-000.OBL.CAPTURE_VALID",
    "MP2-000.OBL.CAPTURE_NEGATIVE_BOUNDARY_PARSER",
    "MP2-000.OBL.THREE_RUN_DETERMINISM",
    "MP2-000.OBL.INSTALLED_HELP_AND_RESOURCES",
    "MP2-000.OBL.SCHEMA_AND_CHECKSUM",
    "MP2-000.OBL.DOCS_PARITY",
    "MP2-000.OBL.FINAL_CLEAN_TREE",
)
REPOSITORY = "Miko997/metriplane"
AUDITED_BASE_SHA = "14c1befff886215d928f1c3f6b412b843b902671"
AUDITED_BASE_TREE = "38dcd26db9a467c850c75d4af0e6c932c3d0ecd7"
AUDITED_VERSION = "0.3.0"
EXPECTED_MATERIALIZATION_ID = "f72ad822f4bc4bd8ebd02a8a41e2662161a634b3246832bfb099e1b150e20478"
EXPECTED_WORK_ORDER_MANIFEST_BYTES = 22_526
EXPECTED_WORK_ORDER_MANIFEST_SHA256 = (
    "d94cb3b4cbdc896a95ffab8e40d5268dda1e372fb18ece31476072d525a8eaaa"
)
EXPECTED_WORK_ORDER_VALIDATION_BYTES = 4_698
EXPECTED_WORK_ORDER_VALIDATION_SHA256 = (
    "2b475791f0d3b4cdec7ea2f1265de5afddc746b21880b295b096d277fd943d55"
)
EXPECTED_PREEDIT_BASELINE_SHA256 = (
    "90d7afa45338d61121c09ad5b3b8fa5b342f14f2988c507147b35ab083403eb6"
)
EXPECTED_AUTHORITY_SHA256 = "40f105fd42388945af2f1885ce8abcbff22764531ccb2661afe98fbf5459b0cf"
EXPECTED_RESOLVED_AUTHORITY_SHA256 = (
    "c8aab5496882c3a01553d604b1ad8437d0dafa73287d135a668342cf9de4f378"
)
EXPECTED_VALIDATION_CHECK_IDS = (
    "CANONICAL_MATERIALIZATION_INPUT",
    "MATERIALIZATION_ID_MATCH",
    "ENVIRONMENT_OBSERVATION_CANONICAL",
    "ENVIRONMENT_ROW_BINDING",
    "GITHUB_REMOTE_COLLISION_PROOF_COMPLETE",
    "CREATE_SET_REMOTE_COLLISION_FREE",
    "REPOSITORY_INSTRUCTION_DISCOVERY",
    "PR_CONTRACT_PHASE_SELECTION",
    "PREEDIT_REMOTE_REDISCOVERY_NO_DRIFT",
    "PREEDIT_REDISCOVERY_NO_DRIFT",
    "INSTANCE_NO_OVERWRITE",
)
EXPECTED_WORK_ORDER_MANIFEST_FIELDS = frozenset(
    {
        "assignment_actor_and_authority",
        "base_sha",
        "canonical_materialization_input_digest",
        "clean_tree",
        "compatibility_and_non_goals",
        "consumed_contract_digests",
        "criterion_to_test_obligation_mapping",
        "environment_profile_rows",
        "evidence_and_downstream_handoff",
        "exact_command_ids_argv_expected_exits_outputs",
        "exact_dependency_ids_and_merged_artifact_proof",
        "exact_existing_and_CREATE_paths",
        "exact_symbols_routes_workflows_schemas",
        "linear_issue",
        "linear_issue_snapshot_digest_and_event_cursor",
        "manual_and_irreversible_actions",
        "materialization_id",
        "ordered_pr_outcomes",
        "people_permissions_secrets_services_hardware",
        "produced_contract_paths_schemas_producers_validators_consumers",
        "repository_instruction_state_and_pr_contract_phase",
        "schema_version",
        "signed_assignment_or_delegation_record_digest",
        "stop_conditions",
        "task_id",
    }
)
EXPECTED_MANIFEST_ONLY_PROJECTION_SHA256 = {
    "clean_tree": "d71bbec5b3db1754278000bfa0b1acdc2a9303832310e5aebe4e6d18c1c2d3f9",
    "compatibility_and_non_goals": (
        "ccd2a84c61c9d7b147ff4c042df87deabee2b82ad6db0d70572df00e6b7d7eb2"
    ),
    "evidence_and_downstream_handoff": (
        "b56eb93adf6948afe503ef06d4de45c73bc0c04e8689926aa986de1f36d79144"
    ),
    "stop_conditions": "a16c0e51af6a5db44a3612a5308ca3ed218238818c3b99859b24cd7b61ab96c7",
}
CANONICAL_INPUT_SCHEMA_SHA256 = "b3a6b640384a449f6e250b6e630b05f2e287df3779e752ddf9f8f6992a2717c8"
EXPECTED_CATALOG_SHA256 = "f04a69658ae8c0c11c1ad96cb666b03d92cdf2d0a59a7520580487a61a43c161"
EXPECTED_TASK_ROW_SHA256 = "7637789f9430f3d99fa2dba4aff7c15cde68f694fbadaaac31b6f14921e90501"
EXPECTED_ISSUE_SHA256 = "ed1898cceee84957ced7a1973bdacaf879971951c519b9376c625752bb3f1a7f"
EXPECTED_ASSIGNMENT_PROOF_SHA256 = (
    "7d0f9da663e3fc5b9f1e9ad188e802ee64eb6272a47f02a0cd9c92a1b7cfdbd2"
)
EXPECTED_RESOLVED_ANCHORS_SHA256 = (
    "db692c1e6b37fc887e777faa75f0085d778f99ab2bb46c2af02d8962dfaa4588"
)
EXPECTED_COMMITTED_SNAPSHOT_SHA256 = (
    "0753e370d8f61df201de98ac838cec9cb9e279f616bd10eab547a6f9511575b3"
)
EXPECTED_GITHUB_ACTOR = {
    "database_id": 141_511_110,
    "login": "Miko997",
    "permission": "admin",
}
EXPECTED_CANONICAL_PROJECTION_SHA256 = {
    "repository_instruction": "20eadd406136169fc1fe44095c818b95ab34ddb016eed948ae8c4437316ae120",
    "resolved_obligations": "6390534dbd2df86d08d1861dd78e69121983f5fb7d1bda8d6f1d6e23dfc2adb3",
    "criterion_mapping": "2218b807889895a8fd1e0c60b2b5b54129aeb76b5a063cc82989d439f21d0e9b",
    "ordered_outcomes": "80c1da20d787b3473e62811c99158b39468cda57d9b2d41ad3b358ce725b1fd5",
    "produced_contracts": "8d6efca9fde5ad7749409922eb1a59a5d41f0b1c74443a5db23e23c5df03b8b7",
    "typed_resource_static": "0ce68da7882fa75700e4ce4cb1382b4eb64f155b894f41d80679f3afd921ae66",
    "manual_actions": "e966855bda100281d5c20a371f377490366ae45d188e7a01c426f5ade8639ed9",
    "command_static": "7b04707c62dd0c7d68d38b0bd23b0d01c6864713aa3280604ebe5e206656afb1",
}
EXPECTED_CREATE_PATHS = (
    "tools/baseline_snapshot.py",
    "tests/test_baseline_snapshot.py",
    "schemas/metriplane.baseline-snapshot.v1.schema.json",
    "docs/status/baseline-snapshot.v1.json",
    "docs/status/baseline-snapshot.v1.sha256",
    "docs/status/baseline-snapshot.md",
)
# Canonical authority schema compressed into the self-contained capture tool.
_CANONICAL_INPUT_SCHEMA_ZLIB_BASE64 = (
    "eNqtWVtv2zYU/iuClrdJ8QVdgOatGIptQAsUQ98KT6CkY4stRWok5cQL+t93SF1CybJFuX2JbYk8l+9850LmJbzL"
    "Ya/Cx5eQ1LoQkupTojJRgXmUCa60fceYeII8fPwSQk51FGhQ+FeCJpQHcKQ58AyiIBNlSXVAeB5UtSoCwdkp0AUE"
    "8EwyHXz8tI3X63WgifoWpJLwrAijEJXxQMigrnKiYWJ5VTOGuv6tUamVzYAcIUBFNS9BHtCwXRTCc8bqvDHSPkUr"
    "ySHC3SmjqsAvUmjINOSBliT7BtJ8ckU1Fdz4Ugn8LuQpUKA15QfV6EKbZFBShsoFBxXuvn+PQkY5EJmglUImKPgr"
    "CkYxFqs8tyIJ+yTRNakpbnrcE6YgCivn0UuYU1Uxcko4KS3eJeUfgB90ET5uolCfTBRCpSUaE6JSmvssUsYqenQD"
    "qGUN+MpTDdpoAiodAeEH629oXDeBoLLBuV9qjWs1REO/XJN2vTqRGshcdQlRih44gMFT7BdC2W/2AslwHbimGQY3"
    "b6N488Zh+O8koO3hLyubWKtLRJmVlaiCbH97mBDZvmgljFJ2tHa8whJE1ZBktVTChngvZElMjE32xZrakE3Qyuzy"
    "ZGCz1Pi2p0MefXz/OX54O8cyQ7IuGxN4hqw22ByoLuo0YeJAuYcZUyIG0fByRmUFlCQ5glRtgDtjS8BFSHMO950v"
    "ccfC2FL4/rg5y5iRvMhNoRly+TLmIr2jQZb4IeQRCoccE8EfEe6ctFM1AT3ZGKwrorH6IuzhP1/W8VsS73cvb9bf"
    "76YY+povU7se3kztwm13hgZhoXWlHlcrJ6jYy1ZNtNQqFULjHlK5C/qHcWl6BCWM/kdMIGLKq1pj9O+b/fdflQ3f"
    "XfPTUWdexO0iIQ+rXJK9Xm3X23W82bbaDWRL62CJ8CcYpxwYHKxNNxXVUuRuG3FK9ZBgLavatG7UjArRpSrfbZkv"
    "d6NEsraNNnfqpyiVEgVm3bSGjVmSES44+sQSM6AkUjwtxAvhIJgTiVfRKKtt/CTkt1hIUzpw6LD1InqVMt8AWhOx"
    "hrm2bSbcx5WLIb7gzpmFA+mNUVMRyAEHPTMoYiFpJ0ZjC9VQKk8v2gdESnIK7Rh2xGJj64vipFKF0AkObYkE1rD+"
    "tc0tCCMcTfrc1CF//tTypVOB0xXOwTh+Yj3QmmSFSXI1QHCBZq/mp6lmPhNjLdlictlu0SgYCNjNhR1Xc4pngb8a"
    "r9vZNgeVYWb5Tk5+g8xghHG6ipliTGfZ/TrZiRhJgakxt68CPe9gfwLxm1vascBvcZcuP8Cm25DqFNus43VpiJEy"
    "gYezPEkNEvaHCtuV+FSL5gDmUqmXMgjZjURSmuha+R7J2tXN8/kwAymTn5t59syMLVj7FqqpNByMa11OTmTUqwcD"
    "go3IOcRwiNF4BHXs7/NmWN9cdk6FtK3+8yl/27F20AtG2rqaP2VWSXiNg4RpRlRKsL0zZWAPwm2ijZuZM2hTNE/W"
    "7VSP8IEVVMkEDTeXFzqpCpxnfHs/KMGOBmWe4eitElFrHFBVL21puhv46hIF9ubk9IAEmHTL3uXg0YEqc6liHfn9"
    "7/fvPr9PsE4UV7aoU5kKpnAOqzWoxMxKeyaeVDuPTO5EO/M6cy2zSrotSfseMTjiuI7cM3C07sgLUSkF4p8Jxqjq"
    "B+mbK6Uxx2Vgc5KKGy1xr6U9QNqDwwXu/kH1n3U6PPn4tV6H3tacXsI0kZ/bArkxec5ff5wjNaKZzwDb7ekPU4lz"
    "Plzol4+wy2ZeDvU8h70pG13JnR9m7+5a7purWbRbWeNFyujhteUvSX0EE8+6CI4WibkFdmQlJakq02SasnSZKQ1Y"
    "rUXYCNAoeTgivpW9nzVA675KzUqz5yew5RG3oFS4kMgtEiPnr8rWQrCsIBTLMOi66lEcbtyON46IOWXhBYMiP4Sv"
    "WLYU3qusAX6kUjT3CUiEvenzS09T5yLM0bqB0Lu4iFSBPP7YlDquvY5lsSO/r7qL6+pPK6Zj/rjOR5cRnbxK87mL"
    "mL/K6qZnJDGIChUiriWOP8YkZGAmQZtPeaQZFr6CyPyJSDjPw7nr0Ik7GOfu5qYhyf+aIJq7Ppu+xPCasHxK8Vzi"
    "3RSC+Vl01583wo89J4JKQmz/A7d5CPqoBCN+BJYf4Rnv/geymSQi"
)

BOOTSTRAP_ENVIRONMENT_SCHEMA_ID = "https://metriplane.com/schemas/bootstrap/metriplane.bootstrap-environment-observation.v1.schema.json"
BOOTSTRAP_ENVIRONMENT_SCHEMA_BYTES = 13931
BOOTSTRAP_ENVIRONMENT_SCHEMA_SHA256 = (
    "2999357b82a3bc205b705d75bf492bbb6e8a486fc81139d80ea7447d24dff13c"
)
_BOOTSTRAP_ENVIRONMENT_SCHEMA_ZLIB_BASE64 = (
    "eNrtW+1v2jgY/1emXD/ctqRQtlW7StOUQTpyCwkiobqu6lmGmJI1L8wxdN2O//3svGFCgHBD207yJxT78fPm389+Eptv0omLJrF0"
    "8U0aR0EAQxdgFM99wlqg63rEi0Lo93E0Q5h4iEpOoB8jWZpxTVQU3y3Yr0dQkDSQxxmSLqSYYC+8k5ayFHihnnaeyXkvxBg+ss7c"
    "tueysVTUQOEdmfKyK03jh0RqBglBOKRdfzekCjEULjwchQEKdwRT4WjWEI0+oTFJFH3xCBhHLkp8g1+8YB5IF61Xr5Kg0qdmMc4L"
    "CbpDmA2MiYswBiMYo/OXJZd/f3txoyofofK1qfzxvHH77eXy6bONxtbyzZt/1pteLN88fXtSFXBmLp7C1qtzZu4EowmV+K2RzHEj"
    "60glozn5kY4xc3sdo6IYfZ57GNEJvuFBIacAS+d+fWr5+SlHVp6CsivlnN1WzD7tOiul6IZGDJUJTU1zWR1wEWnVqPOXVaPosBMG"
    "f2lKyCy+aDQCRHtmPgzRKc1EIx5PUQDjxiiKCB0DZ7xA0ahwqVGiUYzwAjLUny7OTlMNp5/iKKTmT9JHziDrUDKhCN81XAwnpNFq"
    "tprKWSuzz2ai/qrA0s5yWz3nZyxVhecgjuZ4jACmDXXo7aKxDylSQC2eV7pntIFqGOnaF8Z0tNQ+HTqXymumv3/taLYDOrqtvjM0"
    "0DeG73UTqEPHMiy1ww86y8S7ltlV7a6taWvdTdbtfOSbhk6bNQ6vQFttdzVqZFAnZCrfH1h/am0HaOaVPrDMnmY6+0eWeLVmdqvW"
    "vRnYiDmJUs6zWsUlyjVvgdyD95bxlO4rYzLHqMb2MMLRA8U9t7aHc99nPRPPR/FjTHehUs5Svl7sYSivAEyjAIExpKQ4NBrfjx58"
    "jyr5Huh2rZ62ivAm91FOY71liOv1M1htlykDcKfkFuhtH/NX532mfr+3iaxlXurvawp3VEetKWo7qrPfhxJJEvFNvzaiKnuzYbKY"
    "Cbkm8aqIwwEPhXSrY57vZ0IUgxAGdThDuTAFMZpBDEmEaw6I1wq+A8DrooU3Rvxk5EUTN3N0V48JX6HRncJHMGTWvRi4Hq7uu/dC"
    "t2YAu6GDEXThyEfVZh6wR7b1lqCUeJRZLOIqguAMcVrlPElVaFiV0i82S2kKE0CLAjKJcLA3DyVPq2C2glFJ9wZq5K1rW46XqmCm"
    "ELsPEKOK9dqjuyVVSZW5HvN4NGcA+8+wq8mFkAYHfe8rNZuP4Ku4tOC9fU5LYqV4ePqscr9YIBxT3w6dhrIHspT95Pp2g6Li/eqe"
    "eo/8GsH70fi+zhsExQRGFO1xrdUFRwxZfAW0KliZRSUrDBRW/CnxnM5uMu6RTGtkT5bmi0NTzPlfZEderzQK+4n+9dRsx+a2ImGt"
    "+lilZFWucEyoml6ulgfrb+p5VWHRmbqhWKVT5n3JoJA88xxYf9Eu6lFTpTtV+VU3620uafLq6UkLQnClDWzdMo+h0FCdS2vQO4Iq"
    "ywYDzdBU+xiB0q37eEEaVvsDsLtqRq3v1KabtPgwDK3DCndnoL8bOtRN+wiaL3VDs69tR+sllU1ay+zSe7ukSM5W6mxFDmAOzdf8"
    "kvVa3sCt+Pj0//74VP/Lx8//HnXQV5pf7hOV4IrgiuCK4IrgiuCK4IrgiuCK4IrgiuCK4IrgiuCK4IrgiuCK4IrgiuCK4EqGkdtN"
    "RGM0i2KPRPix9hW89Eog4E6586OiA68mJsoQmc+Of7TZH2h9daAB2xoO2hpoG5Z5jAPAdldrf7CGTq733XHOFa+0gX55nSvVO5rp"
    "6M710RW3DU09xsmlfW22weXA+qiZwKSJ7egOuyp4vFNMYNNE91RwpRp6R3WsAejru88y+TPHjfsLpSvuS/488pxf8c9/nfPIfUD+"
    "qZtLkXixd4g668dxYdvqK7gguPCz6ygC4/sSXHv9ltJsNjciKNVPq7Hy6p8Tm4XZtv9MbPlLxLbKaveVstVdfRaiR9jtPalXVHVP"
    "CheecLaecBqljVz9C1kEEgM="
)
GITHUB_REMOTE_SCHEMA_ID = "https://metriplane.com/schemas/bootstrap/metriplane.github-remote-collision-proof.v1.schema.json"
GITHUB_REMOTE_SCHEMA_BYTES = 9512
GITHUB_REMOTE_SCHEMA_SHA256 = "e9ec2893f12975390147540c5606eb4e8f123cd48b94cfdfa8c9ad0aeea028a3"
_GITHUB_REMOTE_SCHEMA_ZLIB_BASE64 = (
    "eNrNWelv2zYU/1cyLR/m1fKRpdkSoCiKIOsCOAfS7Mtcl6At2manqyTlJkvyv++ROkyJ1OEs61YEaSQ98t2/9x754Ox7ZMmdkwdn"
    "RQVaREGAQw8xwhNfyLfY86igUYj9axbFhAlKgHqJfU76Tqy9AlK22sj/qSCBeiHuY+KcOFwwGq6cp74T0PA8/Tju518xY/hefsx5"
    "U0+ujbEQhIVA8OmHtyfwM/mAbm/Ozh7f35xd99B05B5jdzl7OBw9PU7fuX/AM5q96u07fZPt4mt1y6GNjIQbyqIwIKHSfBGFXP3x"
    "/vwW3Z7dXJxfvpug65uri+tbWDeCLSan6N1kAg+ng99vf3V/cZ7kNnfKkB6RawN8R4MkcE4OXr9W+qdPo4I9DQVZESb5c+ERxtAc"
    "c3J0aNpAaondv0DRV0PQ+6n3o/Hy4OnNm8fyq5+e3vTeWq2SseNrfPD6SLLbZ2QJFN8PVUgMsw8pZZSIbymYZNcqGJAy8iWhjIB7"
    "p3r89NNYTD1fdqzun6pmVRdURanabFYIH80/k4WQwoNp1oaJvhv24NdA2uXT47D38eMAfuBh+Ljf6w1eWa3AyILQuD0Hse9fgXWm"
    "Dw6BZ8W6lJUxQ2ESzCHEthkZJr4P9gMudGmuWES+D9pEagUJZbxOnWARI2W1O4TjmCMEcLFO5mhJxGKNYgYq1JH4lAugQIs1DlfE"
    "Q0vqkxAHwGymZBBrErbIXSTO2Ewc+DezQFEi3c27hPdO+q6IAHSMowZ9JUnCCUN+tKJhC6HcC0kJ8DxiGIRAoEZAOQd/NyzlBDNl"
    "d95A9A9902/zwbRwQj8NqZmKW1k6npG9uRN0tn3Tk1UOtiSET+NKEuoFw446hcC2VUeHtlWwbF+WK2ctRMxPhsOAwJfYxyEZABwN"
    "+WJNAsyH8ygSsAbHOkHqAZeRIBLElfpT6XQXIjlaDjbjQbp68JmrSNhPHzVm8oObEUVsNfQYXorhwehg5I4PMt7Sgt3Qw4YEG8I8"
    "utCroXN5hU6vJpPzD+dXl05D+uJEvhd0gQWEFc7Tq5Lj21DXUu8rgw5CxiyG8MIqg7AH0ZfBRWEpnhXYrKUYpT1E7BNBQsK5RSbf"
    "R2uCPY5oyGOIFeJpqgmWENhiznAIWZPFI7BB+aYmbRhB7kQbCkUBQeam+eYxuhQmLQgSqkzrsnFOzIhIWAgGXERJ2pUUDcXxscqg"
    "OOIUbHuPNmCTuW/sJS22hiSXJGsqLDYrbJHaptTBle1H7sCPSFa4mq04RJz0OYgLwBCKNrLardLaxCNfRY+yqylO5imAF4BDgQBM"
    "sG+aEkAHS7jIqKWOKamq8vWmV4QN+yYh3mAKsO2TreHKOsBmX0PC+JrGCBIfe1jgOnXNEmZPoB36cclO6ph11E01tO+ktSolm5Bw"
    "JbuYsQUm7SnLwAASHhnFK5m6TSlcxv28RurClrjY8F0RAmDby8tYK+ppmoWAvYudxxlpciSiSHd+16K/BZLKVJSx2nr/UB+LDqUQ"
    "ZEnzj9PWqWUrmc+zWlJ667ppcOrvIkaVjDNzCMvAQJotyEaYfNUS6u7azZPSnWNG3DQztazxaUB18BuPRtrXrsbUuptSyO3kjcbO"
    "Km1uPEhK6nfetein0tWyV+KdF9d3WmUc31VFo5Oq7tXXI9m0ZsU7VVcadqqqXg50M4Js+aslZzbmlMtOJafzUeipJVW2zUztBo2z"
    "TneT9xvHqpnk8y2EKQPO/0KkDln33wpZwZZGcaoAKas+/ZKQLOSyTqDckBZB3FJIO21c7mZ3KV72VjdjCvOIT7BepWq6UpO+ueU1"
    "6Vva3voFMXQSLeXE0h03HrDZu+WqCPVwmi9qtFqzyrXCWxXvW/3Y6AQb3Jonu41wazkILiHvkdk2VCeMYusdQlaypKKlrcuP1yqf"
    "1WvbgWC2YbbQZpwOedg0Ie2goGV8qnNBqk8n4dI5pdFotWPZC2KVfaZ7Af14lLAFkVPeTiLXXzXY2FQip7BpmX3fcKFV7zqDt0af"
    "debdIcDqBmITZNuH4npgNgdjk9Y6HNcFQx6mZVtUXGLVrVaoVg1tItr80zDAv2Dy5GCu9y/vqfgtmadlS051iIc45utIPCsoyLNR"
    "qwO+yDGm1RAVf6o1Gnp1SY7U2dCdIbkT4c+vNfJwJcpb53YXqvMGpXs30mZzzSPv/ptdpilmXS5BsrFUwthLQbc6kLYDhPJ7N4t2"
    "CcBOF0XwhopSz1cXm8Xlgx4m+fKyA8sWznXWFOzr1aQIJC1QqrbvkgnbpvTfPBMsY2hpuMLUVkeavbSUmZtjRb7TBf0zOj7+WbsY"
    "UZmuTqhQwkpHIfnFRzrJqRsWc7m8VzE8Wj5d3Api6GhVqSSP6Z7agaEYFAh3rOhlc3UF7Tvdz6urHrSBSpWdyxZ+6n7dVGoUGYTA"
    "nb6RNJ5PQzJ10d4sl+3x4vrAHY1Gjxdnt+7RsQpUzOQpQIEi2fqpI8+K+DDfplBvEEsrCWmNofyNaijymzRNoZzSLSiNOzMvWoCd"
    "BBbJlnWJvCvdNr0bKQNPXYFq12b5AXnp2qzv6H+fX55eXVxPzm7PzNPxime1TqEEILa7goovDOfaj8jNbqM2Iu3HePZp02hszaGq"
    "MkTWt16lA5fKIcnW9rMC7Z2LImb2iovYvbS92kt12yt23FPp4Bh5+TebGBsO"
)

SNAPSHOT_LEAF = "baseline-snapshot.v1.json"
CHECKSUM_LEAF = "baseline-snapshot.v1.sha256"
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_SCHEMA_BYTES = 1024 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_GIT_BLOB_BYTES = 16 * 1024 * 1024

GIT_READ_ONLY_ENVIRONMENT = {
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C.UTF-8",
}

EXPECTED_TRACKED_COUNT = 1469
EXPECTED_TEST_COUNT = 1194
EXPECTED_TRACKED_ROWS_SHA256 = "39c5f21f491926d6c45d4a8090ecc8ec16893000f5637020a199b7bc6cd0b03f"
EXPECTED_MODE_COUNTS = {"100644": 1429, "100755": 37, "120000": 3}
EXPECTED_SCHEMA_COUNT = 6
EXPECTED_SCHEMA_ROWS_SHA256 = "68069c30fce592538fe7b181396df64deac35abd48751bdaf5b1a5242bbfbaf6"
EXPECTED_WORKFLOW_COUNT = 15
EXPECTED_WORKFLOW_ROWS_SHA256 = "76a647b24cba2203386722406fdd6626757fabcb79390dc1afb8fc20f36bc93c"
EXPECTED_RESOURCE_COUNTS = {
    "repository_seed": 250,
    "setuptools_package_data": 6,
    "merged_unique_rows": 256,
}
EXPECTED_RESOURCE_PATH_DIGESTS = {
    "repository_seed": "3ac908ab77d8e31e6b760ab1a598f69ff614ed2ce10dcd44b9524eb80a0c9477",
    "setuptools_package_data": "51e103bed72e65a6913af2762544bb67645c4b440f494b8353e03a93ff6a60d1",
    "merged_unique_rows": "fc3bbd56c48c54bedddc92caee716a97bd95718228ff2eb7d34826c4dbc32033",
}
EXPECTED_RESOURCE_ROWS_SHA256 = "c165504cf119027624e11a39a3c0f969a0975d51585f590f740b2fa8b15d7d94"
EXPECTED_ROUTE_COUNT = 48
EXPECTED_ROUTE_ROWS_SHA256 = "c278c306fe36d7251da0a04d710fe02d8d90758c911c325e4c827a0b41e7abaf"
EXPECTED_TEST_NODE_IDS_SHA256 = "ba68bcaa580c7e392a435ddedd254a6487d8032db3e1e23ad0e6793c5e2a4469"
EXPECTED_HELP_IDENTITIES = {
    "metriplane": (
        "metriplane.cli:main",
        1034,
        "11ca5ddd640693091a77ef825007b7c9f9be5a993e482ab3fa16aa543dadbefd",
    ),
    "metriplane-run": (
        "metriplane.run:main",
        587,
        "16ecd4bf8f45f14aba40d5cb9859914ad75c1c18504ff0a283254591c7c572ef",
    ),
}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
BASE64 = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")
_DESCRIPTOR_DIR_FD_FUNCTIONS = (os.open, os.stat, os.unlink, os.link)
_DESCRIPTOR_FOLLOW_FUNCTIONS = (os.stat, os.link)

ROUTE_SOURCE_ALLOWLIST = (
    "metriplane/_local_http.py",
    "metriplane/metrics.py",
    "metriplane/run.py",
    "metriplane/runner/service.py",
    "metriplane/runner/operator_api.py",
    "metriplane/streaming/ws_server.py",
)
OPERATOR_GET = (
    (249, "/env"),
    (251, "/cameras"),
    (253, "/profiles"),
    (255, "/configs"),
    (257, "/latest-run"),
    (259, "/runner-status"),
    (262, "/live-summary"),
    (264, "/objects"),
    (266, "/incidents"),
    (268, "/traces"),
    (270, "/camera-trust"),
    (272, "/frames"),
)
OPERATOR_POST = (
    (275, "/create-profile"),
    (277, "/write-zones"),
    (279, "/save-config"),
    (281, "/start-fusion"),
    (283, "/calibrate"),
    (285, "/validate-alignment"),
    (287, "/validate-alignment-full"),
    (289, "/generate-report"),
    (291, "/checksum"),
    (293, "/live-summary"),
    (295, "/objects"),
    (297, "/incidents"),
    (299, "/traces"),
    (301, "/camera-trust"),
    (303, "/frames"),
    (305, "/ask"),
)


class SnapshotError(Exception):
    """A typed fail-closed domain error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _SchemaViolation(Exception):
    """Internal exact-schema validation failure with a stable instance path."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def _fail(code: str, message: str) -> NoReturn:
    raise SnapshotError(code, message)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _nfc(value: str, *, require_already_nfc: bool = False) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        _fail("INVALID_UNICODE", "lone Unicode surrogate is prohibited")
    normalized = unicodedata.normalize("NFC", value)
    if require_already_nfc and normalized != value:
        _fail("NON_NFC_VALUE", "value must already be Unicode NFC")
    return normalized


def _normalize_json(value: Any, *, integers_only: bool = True) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if integers_only:
            _fail("NON_INTEGER_NUMBER", "JSON floating-point values are prohibited")
        if not math.isfinite(value):
            _fail("NONFINITE_NUMBER", "non-finite JSON number is prohibited")
        return value
    if isinstance(value, str):
        return _nfc(value)
    if isinstance(value, list):
        return [_normalize_json(item, integers_only=integers_only) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                _fail("NON_STRING_KEY", "JSON object keys must be strings")
            key = _nfc(raw_key)
            if key in result:
                _fail(
                    "DUPLICATE_KEY",
                    f"duplicate JSON key after NFC normalization: {key!r}",
                )
            result[key] = _normalize_json(raw_value, integers_only=integers_only)
        return result
    _fail("NON_JSON_VALUE", f"unsupported JSON value type: {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    normalized = _normalize_json(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _strict_json(data: bytes, *, require_canonical: bool, integers_only: bool = True) -> Any:
    if data.startswith(b"\xef\xbb\xbf"):
        _fail("JSON_BOM", "UTF-8 BOM is prohibited")
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        _fail("INVALID_UTF8", f"invalid UTF-8 JSON at byte {exc.start}")

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for raw_key, raw_value in pairs:
            key = _nfc(raw_key)
            if key in result:
                _fail(
                    "DUPLICATE_KEY",
                    f"duplicate JSON key after NFC normalization: {key!r}",
                )
            result[key] = raw_value
        return result

    def parse_int(token: str) -> int:
        if token == "-0":
            _fail("NEGATIVE_ZERO", "negative zero is prohibited")
        return int(token)

    def parse_float(token: str) -> float:
        if integers_only:
            _fail(
                "NON_INTEGER_NUMBER",
                f"floating-point JSON token is prohibited: {token}",
            )
        value = float(token)
        if not math.isfinite(value):
            _fail("NONFINITE_NUMBER", "non-finite JSON number is prohibited")
        return value

    def parse_constant(token: str) -> NoReturn:
        _fail("NONFINITE_NUMBER", f"non-finite JSON token is prohibited: {token}")

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_int=parse_int,
            parse_float=parse_float,
            parse_constant=parse_constant,
        )
    except SnapshotError:
        raise
    except json.JSONDecodeError as exc:
        _fail("MALFORMED_JSON", f"malformed JSON at line {exc.lineno} column {exc.colno}")
    normalized = _normalize_json(value, integers_only=integers_only)
    if require_canonical and data != _canonical_bytes(normalized):
        _fail(
            "NON_CANONICAL_JSON",
            "JSON bytes do not use the required canonical serialization",
        )
    return normalized


def _require_descriptor_capabilities() -> None:
    required_constants = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    supports_dir_fd: set[Any] | frozenset[Any] = getattr(os, "supports_dir_fd", frozenset())
    supports_follow: set[Any] | frozenset[Any] = getattr(
        os, "supports_follow_symlinks", frozenset()
    )
    if any(not isinstance(getattr(os, name, None), int) for name in required_constants) or any(
        function not in supports_dir_fd for function in _DESCRIPTOR_DIR_FD_FUNCTIONS
    ):
        _fail(
            "PATH_SAFETY_UNAVAILABLE",
            "descriptor-relative no-follow path safety is unavailable",
        )
    if any(function not in supports_follow for function in _DESCRIPTOR_FOLLOW_FUNCTIONS):
        _fail(
            "PATH_SAFETY_UNAVAILABLE",
            "no-follow stat/link path safety is unavailable",
        )


def _open_directory_nofollow(path: Path, *, code: str, label: str) -> tuple[Path, int]:
    _require_descriptor_capabilities()
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(absolute.anchor, flags)
        for component in absolute.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            try:
                info = os.fstat(child)
                if not stat.S_ISDIR(info.st_mode):
                    _fail(code, f"{label} component is not a directory: {component}")
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return absolute, descriptor
    except SnapshotError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _fail(code, f"cannot open {label} without following symlinks: {exc}")


def _read_regular(path: Path, maximum: int, *, exact_size: int | None = None) -> bytes:
    _require_descriptor_capabilities()
    absolute = Path(os.path.abspath(path))
    if not absolute.name:
        _fail("NOT_REGULAR_FILE", f"required path is not a regular file: {path}")
    _, parent_fd = _open_directory_nofollow(
        absolute.parent, code="READ_FAILED", label="input parent"
    )
    try:
        inspected = os.stat(absolute.name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        os.close(parent_fd)
        _fail(
            "READ_FAILED",
            f"cannot inspect {path}: {exc.strerror or type(exc).__name__}",
        )
    if not stat.S_ISREG(inspected.st_mode):
        os.close(parent_fd)
        _fail(
            "NOT_REGULAR_FILE",
            f"required path is not a regular non-symlink file: {path}",
        )
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(absolute.name, flags, dir_fd=parent_fd)
    except OSError as exc:
        os.close(parent_fd)
        if exc.errno in {errno.ELOOP, errno.EISDIR}:
            _fail(
                "NOT_REGULAR_FILE",
                f"required path is not a regular non-symlink file: {path}",
            )
        _fail(
            "READ_FAILED",
            f"cannot open {path}: {exc.strerror or type(exc).__name__}",
        )
    os.close(parent_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or (
            before.st_dev,
            before.st_ino,
        ) != (
            inspected.st_dev,
            inspected.st_ino,
        ):
            _fail(
                "READ_RACE",
                f"required path changed between inspection and open: {path}",
            )
        if exact_size is not None and before.st_size != exact_size:
            _fail("INVALID_SIZE", f"file must be exactly {exact_size} bytes: {path}")
        if before.st_size > maximum:
            _fail("SIZE_LIMIT", f"file exceeds {maximum}-byte limit: {path}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if len(data) > maximum or len(data) != before.st_size or identity_before != identity_after:
            _fail("READ_RACE", f"file changed while reading: {path}")
        return data
    except SnapshotError:
        raise
    except OSError as exc:
        _fail("READ_FAILED", f"cannot read {path}: {exc.strerror or type(exc).__name__}")
    finally:
        os.close(descriptor)


def _require_safe_relative_posix(path: Any, *, code: str, label: str) -> str:
    if not isinstance(path, str):
        _fail(code, f"{label} is not a string")
    _nfc(path, require_already_nfc=True)
    if (
        not path
        or path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or "\x00" in path
        or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in path)
    ):
        _fail(code, f"unsafe relative POSIX {label}: {path!r}")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or str(PurePosixPath(path)) != path:
        _fail(code, f"unsafe relative POSIX {label}: {path!r}")
    return path


def _require_normalized_absolute_posix(path: Any, *, code: str, label: str) -> str | None:
    if path is None:
        return None
    if not isinstance(path, str):
        _fail(code, f"{label} is not a string or null")
    _nfc(path, require_already_nfc=True)
    if (
        not path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in path)
    ):
        _fail(code, f"unsafe absolute POSIX {label}: {path!r}")
    if path != "/":
        parts = path[1:].split("/")
        if (
            path.endswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or str(PurePosixPath(path)) != path
        ):
            _fail(code, f"unsafe absolute POSIX {label}: {path!r}")
    return path


def _safe_git_path(raw: bytes) -> str:
    try:
        path = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        _fail("UNSAFE_GIT_PATH", "Git path is not valid UTF-8")
    return _require_safe_relative_posix(path, code="UNSAFE_GIT_PATH", label="Git path")


def _git_read_only_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(GIT_READ_ONLY_ENVIRONMENT)
    return environment


class GitObjects:
    def __init__(self, repo: Path, base_sha: str) -> None:
        self.repo = repo
        self.git = shutil.which("git")
        if self.git is None:
            _fail("GIT_UNAVAILABLE", "git executable is unavailable")
        if base_sha != AUDITED_BASE_SHA:
            _fail("BASE_MISMATCH", f"base SHA must equal audited base {AUDITED_BASE_SHA}")
        self.base_sha = base_sha
        root = self.run("rev-parse", "--show-toplevel").decode("utf-8", "strict").rstrip("\n")
        if Path(root).resolve() != repo.resolve():
            _fail("REPOSITORY_MISMATCH", "--repo is not the resolved repository root")
        commit = self.run("rev-parse", f"{base_sha}^{{commit}}").decode().strip()
        tree = self.run("rev-parse", f"{base_sha}^{{tree}}").decode().strip()
        if commit != AUDITED_BASE_SHA or tree != AUDITED_BASE_TREE:
            _fail(
                "BASE_IDENTITY_MISMATCH",
                "audited base commit/tree identity is unavailable",
            )
        self.tree_sha = tree
        self.entries = self._read_tree()
        self.blobs = self._read_blobs()

    def run(self, *args: str, input_bytes: bytes | None = None) -> bytes:
        result = subprocess.run(
            [self.git or "git", "-C", str(self.repo), *args],
            input=input_bytes,
            capture_output=True,
            check=False,
            env=_git_read_only_environment(),
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            _fail("GIT_FAILED", f"git {' '.join(args)} failed: {detail}")
        return result.stdout

    def _read_tree(self) -> list[dict[str, str]]:
        raw = self.run("ls-tree", "-r", "-z", "--full-tree", self.base_sha)
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for record in raw.split(b"\x00"):
            if not record:
                continue
            try:
                header, raw_path = record.split(b"\t", 1)
                mode_b, type_b, oid_b = header.split(b" ", 2)
                mode = mode_b.decode("ascii")
                object_type = type_b.decode("ascii")
                oid = oid_b.decode("ascii")
            except (ValueError, UnicodeDecodeError):
                _fail("MALFORMED_GIT_TREE", "git ls-tree returned a malformed record")
            path = _safe_git_path(raw_path)
            if path in seen:
                _fail("DUPLICATE_GIT_PATH", f"duplicate Git path: {path}")
            seen.add(path)
            if (
                object_type != "blob"
                or mode not in {"100644", "100755", "120000"}
                or not HEX40.fullmatch(oid)
            ):
                _fail("UNSUPPORTED_GIT_ENTRY", f"unsupported Git entry: {path}")
            rows.append({"path": path, "mode": mode, "blob_oid": oid})
        rows.sort(key=lambda row: row["path"].encode("utf-8"))
        return rows

    def _read_blobs(self) -> dict[str, bytes]:
        oids = sorted({row["blob_oid"] for row in self.entries})
        result = subprocess.run(
            [self.git or "git", "-C", str(self.repo), "cat-file", "--batch"],
            input=b"".join(oid.encode("ascii") + b"\n" for oid in oids),
            capture_output=True,
            check=False,
            env=_git_read_only_environment(),
        )
        if result.returncode != 0 or result.stderr:
            _fail("CAT_FILE_FAILED", "git cat-file batch did not complete cleanly")

        output = result.stdout
        offset = 0
        blobs: dict[str, bytes] = {}
        for expected_oid in oids:
            header_end = output.find(b"\n", offset)
            if header_end < 0:
                _fail("MALFORMED_CAT_FILE", "git cat-file returned a malformed header")
            header = output[offset:header_end]
            offset = header_end + 1
            try:
                oid_b, type_b, size_b = header.split(b" ")
                oid = oid_b.decode("ascii")
                object_type = type_b.decode("ascii")
                size = int(size_b)
            except (ValueError, UnicodeDecodeError):
                _fail("MALFORMED_CAT_FILE", "git cat-file returned a malformed header")
            if (
                oid != expected_oid
                or object_type != "blob"
                or size < 0
                or size > MAX_GIT_BLOB_BYTES
            ):
                _fail(
                    "INVALID_CAT_FILE",
                    f"invalid Git blob identity or size: {expected_oid}",
                )
            data_end = offset + size
            if data_end >= len(output) or output[data_end : data_end + 1] != b"\n":
                _fail("TRUNCATED_CAT_FILE", f"truncated Git blob: {expected_oid}")
            data = output[offset:data_end]
            offset = data_end + 1
            blobs[oid] = data
        if offset != len(output):
            _fail("MALFORMED_CAT_FILE", "git cat-file returned unexpected trailing output")
        return blobs

    def blob(self, path: str) -> bytes:
        matches = [row for row in self.entries if row["path"] == path]
        if len(matches) != 1:
            _fail("MISSING_BASE_PATH", f"exact-base blob is missing or duplicate: {path}")
        return self.blobs[matches[0]["blob_oid"]]


def _tracked_tree(objects: GitObjects) -> dict[str, Any]:
    rows = objects.entries
    mode_counts = {mode: sum(row["mode"] == mode for row in rows) for mode in EXPECTED_MODE_COUNTS}
    digest = _sha(_canonical_bytes(rows))
    if len(rows) != EXPECTED_TRACKED_COUNT or mode_counts != EXPECTED_MODE_COUNTS:
        _fail("TRACKED_TREE_COUNT_MISMATCH", "exact-base tracked tree counts changed")
    if digest != EXPECTED_TRACKED_ROWS_SHA256:
        _fail("TRACKED_TREE_DIGEST_MISMATCH", "exact-base tracked tree digest changed")
    return {
        "entry_count": len(rows),
        "mode_counts": mode_counts,
        "canonical_entries_sha256": digest,
        "entries": rows,
    }


def _path_array_digest(paths: Sequence[str]) -> str:
    return _sha(_canonical_bytes(list(paths)))


def _glob_segments(path: str, pattern: str) -> bool:
    path_parts = path.split("/") if path else []
    pattern_parts = pattern.split("/") if pattern else []

    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        token = pattern_parts[pattern_index]
        if token == "**":
            return match(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], token)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def _resources(objects: GitObjects) -> dict[str, Any]:
    identities = {row["path"]: row for row in objects.entries}
    repository_hits: dict[str, set[str]] = {}
    for path in identities:
        kinds: set[str] = set()
        if path == "config.example.yaml" or path.startswith(
            (
                "configs/",
                "adapters/maniskill_pickcube/config/",
                "adapters/massrobotics_amr/config/",
                "adapters/robomimic_lowdim/config/",
                "adapters/ros2_mcap/config/",
            )
        ):
            kinds.add("config")
        if path.startswith("examples/"):
            kinds.add("example")
        if path.startswith("proofs/"):
            kinds.add("proof")
        if kinds:
            repository_hits[path] = kinds

    pyproject = tomllib.loads(objects.blob("pyproject.toml").decode("utf-8", "strict"))
    package_table = pyproject.get("tool", {}).get("setuptools", {}).get("package-data")
    if not isinstance(package_table, dict):
        _fail(
            "PACKAGE_DATA_MISSING",
            "exact-base setuptools package-data table is missing",
        )
    package_hits: dict[str, list[dict[str, str]]] = {}
    for package, patterns in package_table.items():
        if not isinstance(package, str) or not isinstance(patterns, list):
            _fail(
                "PACKAGE_DATA_INVALID",
                "setuptools package-data declaration is malformed",
            )
        package_dir = package.replace(".", "/")
        for pattern in patterns:
            if not isinstance(pattern, str) or pattern.startswith("/") or "\\" in pattern:
                _fail("PACKAGE_DATA_INVALID", "setuptools package-data pattern is unsafe")
            declaration = {"package": _nfc(package), "pattern": _nfc(pattern)}
            matched: list[str] = []
            prefix = package_dir + "/"
            for path in identities:
                if path.startswith(prefix) and _glob_segments(path[len(prefix) :], pattern):
                    package_hits.setdefault(path, []).append(declaration)
                    matched.append(path)
            if not matched:
                _fail(
                    "PACKAGE_DATA_UNMATCHED",
                    f"package-data declaration matches no blob: {package}:{pattern}",
                )

    repository_paths = sorted(repository_hits, key=lambda value: value.encode("utf-8"))
    package_paths = sorted(package_hits, key=lambda value: value.encode("utf-8"))
    merged_paths = sorted(
        set(repository_paths) | set(package_paths),
        key=lambda value: value.encode("utf-8"),
    )
    counts = {
        "repository_seed": len(repository_paths),
        "setuptools_package_data": len(package_paths),
        "merged_unique_rows": len(merged_paths),
    }
    digests = {
        "repository_seed": _path_array_digest(repository_paths),
        "setuptools_package_data": _path_array_digest(package_paths),
        "merged_unique_rows": _path_array_digest(merged_paths),
    }
    if counts != EXPECTED_RESOURCE_COUNTS or digests != EXPECTED_RESOURCE_PATH_DIGESTS:
        _fail(
            "RESOURCE_CENSUS_MISMATCH",
            "exact-base resource selector counts or path digests changed",
        )
    kind_order = ("package_data", "config", "example", "proof")
    rows: list[dict[str, Any]] = []
    for path in merged_paths:
        identity = identities[path]
        kinds = set(repository_hits.get(path, set()))
        if path in package_hits:
            kinds.add("package_data")
        declarations: list[dict[str, str]] = []
        for item in package_hits.get(path, []):
            if item not in declarations:
                declarations.append(item)
        rows.append(
            {
                "path": path,
                "mode": identity["mode"],
                "blob_oid": identity["blob_oid"],
                "sha256": _sha(objects.blobs[identity["blob_oid"]]),
                "kinds": [kind for kind in kind_order if kind in kinds],
                "package_data_declarations": declarations,
            }
        )
    return {
        "count": len(rows),
        "repository_seed_path_array_sha256": digests["repository_seed"],
        "package_data_path_array_sha256": digests["setuptools_package_data"],
        "canonical_path_array_sha256": digests["merged_unique_rows"],
        "canonical_rows_sha256": _sha(_canonical_bytes(rows)),
        "entries": rows,
    }


def _schemas(objects: GitObjects) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for identity in objects.entries:
        path = identity["path"]
        if not path.endswith(".schema.json"):
            continue
        raw = objects.blobs[identity["blob_oid"]]
        parsed = _strict_json(raw, require_canonical=False, integers_only=False)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("$id"), str):
            _fail("SCHEMA_ID_MISSING", f"tracked schema has no string $id: {path}")
        rows.append({"path": path, "schema_id": parsed["$id"], "sha256": _sha(raw)})
    rows.sort(key=lambda row: row["path"].encode("utf-8"))
    digest = _sha(_canonical_bytes(rows))
    if len(rows) != EXPECTED_SCHEMA_COUNT or digest != EXPECTED_SCHEMA_ROWS_SHA256:
        _fail("SCHEMA_CENSUS_MISMATCH", "exact-base tracked schema count changed")
    return {
        "count": len(rows),
        "canonical_rows_sha256": digest,
        "entries": rows,
    }


def _workflow_load(raw: bytes, path: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        _fail("YAML_UNAVAILABLE", "PyYAML is required to census exact-base workflows")

    class WorkflowLoader(yaml.SafeLoader):
        pass

    WorkflowLoader.yaml_implicit_resolvers = {
        key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    bool_tag = "tag:yaml.org,2002:bool"
    for key, resolvers in list(WorkflowLoader.yaml_implicit_resolvers.items()):
        WorkflowLoader.yaml_implicit_resolvers[key] = [
            resolver for resolver in resolvers if resolver[0] != bool_tag
        ]
    WorkflowLoader.add_implicit_resolver(  # type: ignore[no-untyped-call]
        bool_tag,
        re.compile(r"^(?:true|false)$", re.IGNORECASE),
        list("tTfF"),
    )
    try:
        text = raw.decode("utf-8", "strict")
        loaded = yaml.load(text, Loader=WorkflowLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        _fail("WORKFLOW_PARSE_FAILED", f"cannot parse exact-base workflow {path}: {exc}")
    normalized = _normalize_json(loaded)
    if not isinstance(normalized, dict):
        _fail("WORKFLOW_INVALID", f"workflow root must be an object: {path}")
    return normalized


def _workflows(objects: GitObjects) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for identity in objects.entries:
        path = identity["path"]
        if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
            continue
        raw = objects.blobs[identity["blob_oid"]]
        workflow = _workflow_load(raw, path)
        name = workflow.get("name")
        triggers = workflow.get("on")
        jobs = workflow.get("jobs")
        if not isinstance(name, str) or triggers is None or not isinstance(jobs, dict) or not jobs:
            _fail("WORKFLOW_INVALID", f"workflow name, on, or jobs is missing: {path}")
        job_ids = list(jobs)
        if any(not isinstance(item, str) or not item for item in job_ids):
            _fail("WORKFLOW_INVALID", f"workflow job IDs must be nonempty strings: {path}")
        rows.append(
            {
                "path": path,
                "name": name,
                "triggers": triggers,
                "job_ids": job_ids,
                "sha256": _sha(raw),
            }
        )
    rows.sort(key=lambda row: row["path"].encode("utf-8"))
    if len(rows) != EXPECTED_WORKFLOW_COUNT:
        _fail("WORKFLOW_CENSUS_MISMATCH", "exact-base workflow count changed")
    digest = _sha(_canonical_bytes(rows))
    if digest != EXPECTED_WORKFLOW_ROWS_SHA256:
        _fail("WORKFLOW_CENSUS_MISMATCH", "exact-base workflow rows digest changed")
    return {
        "count": len(rows),
        "canonical_rows_sha256": digest,
        "entries": rows,
    }


def _ast_tree(objects: GitObjects, path: str) -> ast.Module:
    raw = objects.blob(path)
    try:
        text = raw.decode("utf-8", "strict")
        _nfc(text, require_already_nfc=True)
        return ast.parse(text, filename=path)
    except (UnicodeDecodeError, SyntaxError) as exc:
        _fail("ROUTE_AST_FAILED", f"cannot AST-parse exact-base source {path}: {exc}")


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        parts = [call.func.attr]
        value = call.func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
            return ".".join(reversed(parts))
    return None


def _route_candidate(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "do_GET",
            "do_POST",
            "do_HEAD",
            "do_OPTIONS",
        }:
            return True
        if isinstance(node, ast.Call) and _call_name(node) in {
            "HTTPServer",
            "ThreadingHTTPServer",
            "LocalHTTPServer",
            "websockets.serve",
        }:
            return True
    for function in [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        comparisons = [node for node in ast.walk(function) if isinstance(node, ast.Compare)]
        has_method = any(
            isinstance(node.left, ast.Name)
            and node.left.id == "method"
            and any(
                isinstance(item, ast.Constant) and item.value in {"GET", "POST", "HEAD", "OPTIONS"}
                for item in node.comparators
            )
            for node in comparisons
        )
        has_path = any(
            isinstance(node.left, ast.Name)
            and node.left.id in {"path", "sub"}
            and any(
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and item.value.startswith("/")
                for item in node.comparators
            )
            for node in comparisons
        )
        if has_method and has_path:
            return True
    return False


def _literal_compare_rows(tree: ast.Module, name: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Compare)
            or not isinstance(node.left, ast.Name)
            or node.left.id != name
        ):
            continue
        if len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq) and len(node.comparators) == 1:
            value = node.comparators[0]
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.startswith("/")
            ):
                rows.append((node.lineno, value.value))
    return sorted(rows)


def _method_lines(tree: ast.Module, name: str) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _string_method_calls(tree: ast.AST, receiver: str, method: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == receiver
            and node.func.attr == method
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            rows.append((node.lineno, node.args[0].value))
    return sorted(rows)


def _operator_branch_literals(
    tree: ast.Module,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    route_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "route"
    ]
    if len(route_functions) != 1:
        _fail(
            "ROUTE_DECLARATION_MISMATCH",
            "OperatorAPI route function is missing or ambiguous",
        )
    method_if: ast.If | None = None
    for node in ast.walk(route_functions[0]):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if (
            isinstance(test.left, ast.Name)
            and test.left.id == "method"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "GET"
            and node.lineno == 248
        ):
            method_if = node
    if (
        method_if is None
        or len(method_if.orelse) != 1
        or not isinstance(method_if.orelse[0], ast.If)
    ):
        _fail("ROUTE_DECLARATION_MISMATCH", "OperatorAPI GET/POST method branch changed")
    post_if = method_if.orelse[0]
    post_test = post_if.test
    if not (
        isinstance(post_test, ast.Compare)
        and isinstance(post_test.left, ast.Name)
        and post_test.left.id == "method"
        and len(post_test.ops) == 1
        and isinstance(post_test.ops[0], ast.Eq)
        and len(post_test.comparators) == 1
        and isinstance(post_test.comparators[0], ast.Constant)
        and post_test.comparators[0].value == "POST"
        and post_if.lineno == 274
    ):
        _fail("ROUTE_DECLARATION_MISMATCH", "OperatorAPI POST method branch changed")

    def literals(nodes: list[ast.stmt]) -> list[tuple[int, str]]:
        module = ast.Module(body=nodes, type_ignores=[])
        return _literal_compare_rows(module, "sub")

    return literals(method_if.body), literals(post_if.body)


def _route_row(
    source_path: str,
    line: int,
    protocol: str,
    method: str,
    declaration_kind: str,
    normalized_path: str,
    condition: str,
    forwarded_by: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_path": source_path,
        "line": line,
        "protocol": protocol,
        "method": method,
        "declaration_kind": declaration_kind,
        "normalized_path": normalized_path,
        "condition": condition,
        "forwarded_by": forwarded_by,
    }


def _http_routes(objects: GitObjects) -> dict[str, Any]:
    production_paths = [
        row["path"]
        for row in objects.entries
        if row["path"].startswith("metriplane/") and row["path"].endswith(".py")
    ]
    parsed = {path: _ast_tree(objects, path) for path in production_paths}
    candidates = sorted(path for path, tree in parsed.items() if _route_candidate(tree))
    if candidates != sorted(ROUTE_SOURCE_ALLOWLIST):
        _fail(
            "ROUTE_ALLOWLIST_MISMATCH",
            f"route declaration candidates differ: {candidates!r}",
        )

    metrics = parsed["metriplane/metrics.py"]
    run = parsed["metriplane/run.py"]
    service = parsed["metriplane/runner/service.py"]
    operator = parsed["metriplane/runner/operator_api.py"]
    local = parsed["metriplane/_local_http.py"]
    websocket = parsed["metriplane/streaming/ws_server.py"]

    def require_membership(tree: ast.Module, line: int, values: tuple[str, str]) -> None:
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or node.lineno != line:
                continue
            if (
                len(node.ops) != 1
                or not isinstance(node.ops[0], ast.In)
                or len(node.comparators) != 1
            ):
                continue
            comparator = node.comparators[0]
            if isinstance(comparator, (ast.Tuple, ast.List)):
                actual = tuple(
                    item.value
                    for item in comparator.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
                found = actual == values
        if not found:
            _fail(
                "ROUTE_DECLARATION_MISMATCH",
                f"expected literal membership at line {line}",
            )

    require_membership(metrics, 252, ("/metrics", "/metrics/"))
    require_membership(metrics, 275, ("/health", "/health/"))
    require_membership(run, 284, ("/metrics", "/metrics/"))
    require_membership(run, 296, ("/health", "/health/"))
    if _method_lines(metrics, "do_OPTIONS") != [302] or _method_lines(run, "do_OPTIONS") != [315]:
        _fail(
            "ROUTE_DECLARATION_MISMATCH",
            "native or fallback OPTIONS declaration changed",
        )
    if _method_lines(service, "do_OPTIONS") != [118]:
        _fail("ROUTE_DECLARATION_MISMATCH", "runner OPTIONS declaration changed")
    if _literal_compare_rows(service, "path") != [
        (187, "/status"),
        (189, "/commands"),
        (191, "/jobs"),
        (224, "/execute"),
    ]:
        _fail("ROUTE_DECLARATION_MISMATCH", "runner service exact literals changed")
    starts = _string_method_calls(service, "path", "startswith")
    ends = _string_method_calls(service, "path", "endswith")
    if starts != [
        (182, "/operator/"),
        (194, "/jobs/"),
        (219, "/operator/"),
        (226, "/jobs/"),
    ]:
        _fail(
            "ROUTE_DECLARATION_MISMATCH",
            "runner forwarding/template prefix predicates changed",
        )
    if ends != [(226, "/cancel")]:
        _fail("ROUTE_DECLARATION_MISMATCH", "runner cancel suffix predicate changed")
    operator_get, operator_post = _operator_branch_literals(operator)
    if operator_get != list(OPERATOR_GET) or operator_post != list(OPERATOR_POST):
        _fail("ROUTE_DECLARATION_MISMATCH", "OperatorAPI literal leaves changed")
    local_calls = {
        (node.lineno, _call_name(node)) for node in ast.walk(local) if isinstance(node, ast.Call)
    }
    ws_calls = {
        (node.lineno, _call_name(node))
        for node in ast.walk(websocket)
        if isinstance(node, ast.Call)
    }
    if (32, "partial") not in local_calls or (33, "LocalHTTPServer") not in local_calls:
        _fail("ROUTE_DECLARATION_MISMATCH", "local static handler binding changed")
    if (49, "websockets.serve") not in ws_calls:
        _fail("ROUTE_DECLARATION_MISMATCH", "WebSocket server declaration changed")

    rows: list[dict[str, Any]] = []
    for source_path, line_metrics, line_health, condition in (
        ("metriplane/metrics.py", 252, 275, "always"),
        ("metriplane/run.py", 284, 296, "fallback_if_native_get_health_unsupported"),
    ):
        rows.extend(
            [
                _route_row(
                    source_path,
                    line_metrics,
                    "http",
                    "GET",
                    "literal",
                    "/metrics",
                    condition,
                ),
                _route_row(
                    source_path,
                    line_metrics,
                    "http",
                    "GET",
                    "literal_alias",
                    "/metrics/",
                    condition,
                ),
                _route_row(
                    source_path,
                    line_health,
                    "http",
                    "GET",
                    "literal",
                    "/health",
                    "get_health_is_not_none" if source_path.endswith("metrics.py") else condition,
                ),
                _route_row(
                    source_path,
                    line_health,
                    "http",
                    "GET",
                    "literal_alias",
                    "/health/",
                    "get_health_is_not_none" if source_path.endswith("metrics.py") else condition,
                ),
                _route_row(
                    source_path,
                    302 if source_path.endswith("metrics.py") else 315,
                    "http",
                    "OPTIONS",
                    "all_paths",
                    "/{path*}",
                    condition,
                ),
            ]
        )
    rows.extend(
        [
            _route_row(
                "metriplane/runner/service.py",
                118,
                "http",
                "OPTIONS",
                "all_paths",
                "/{path*}",
                "always",
            ),
            _route_row(
                "metriplane/runner/service.py",
                187,
                "http",
                "GET",
                "literal",
                "/status",
                "always",
            ),
            _route_row(
                "metriplane/runner/service.py",
                189,
                "http",
                "GET",
                "literal",
                "/commands",
                "always",
            ),
            _route_row(
                "metriplane/runner/service.py",
                191,
                "http",
                "GET",
                "literal",
                "/jobs",
                "always",
            ),
            _route_row(
                "metriplane/runner/service.py",
                194,
                "http",
                "GET",
                "dynamic_template",
                "/jobs/{job_id}",
                "always",
            ),
            _route_row(
                "metriplane/runner/service.py",
                224,
                "http",
                "POST",
                "literal",
                "/execute",
                "always",
            ),
            _route_row(
                "metriplane/runner/service.py",
                226,
                "http",
                "POST",
                "dynamic_template",
                "/jobs/{job_id}/cancel",
                "always",
            ),
        ]
    )
    for method, leaves, forward_line in (
        ("GET", OPERATOR_GET, 182),
        ("POST", OPERATOR_POST, 219),
    ):
        forwarding = {
            "source_path": "metriplane/runner/service.py",
            "line": forward_line,
            "match_prefix": "/operator/",
        }
        for line, suffix in leaves:
            rows.append(
                _route_row(
                    "metriplane/runner/operator_api.py",
                    line,
                    "http",
                    method,
                    "flattened_operator_leaf",
                    "/operator" + suffix,
                    "always",
                    forwarding,
                )
            )
    rows.extend(
        [
            _route_row(
                "metriplane/_local_http.py",
                32,
                "http",
                "GET",
                "inherited_all_paths",
                "/{path*}",
                "local_dashboard_server_active",
            ),
            _route_row(
                "metriplane/_local_http.py",
                32,
                "http",
                "HEAD",
                "inherited_all_paths",
                "/{path*}",
                "local_dashboard_server_active",
            ),
            _route_row(
                "metriplane/streaming/ws_server.py",
                49,
                "websocket",
                "GET",
                "websocket_all_paths",
                "/{path*}",
                "websocket_server_active",
            ),
        ]
    )
    rows.sort(
        key=lambda row: (
            row["protocol"].encode("utf-8"),
            row["normalized_path"].encode("utf-8"),
            row["method"].encode("utf-8"),
            row["source_path"].encode("utf-8"),
            row["line"],
            row["declaration_kind"].encode("utf-8"),
        )
    )
    digest = _sha(_canonical_bytes(rows))
    if len(rows) != EXPECTED_ROUTE_COUNT or digest != EXPECTED_ROUTE_ROWS_SHA256:
        _fail("ROUTE_CENSUS_MISMATCH", "exact-base terminal route count or digest changed")
    return {"count": len(rows), "canonical_rows_sha256": digest, "entries": rows}


COMMAND_RECORD_KEYS = {
    "command_id",
    "argv",
    "cwd",
    "environment",
    "exit_code",
    "stdout_base64",
    "stderr_base64",
    "stdout_sha256",
    "stderr_sha256",
}


def _decode_canonical_base64(encoded: Any, *, label: str) -> bytes:
    if not isinstance(encoded, str) or not BASE64.fullmatch(encoded):
        _fail("COMMAND_RECORD_INVALID", f"invalid canonical Base64: {label}")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error):
        _fail("COMMAND_RECORD_INVALID", f"invalid canonical Base64: {label}")
    if base64.b64encode(raw).decode("ascii") != encoded:
        _fail("COMMAND_RECORD_INVALID", f"non-canonical Base64: {label}")
    return raw


def _decode_command_stream(record: dict[str, Any], stream: str) -> bytes:
    encoded = record.get(f"{stream}_base64")
    digest = record.get(f"{stream}_sha256")
    if not isinstance(encoded, str) or not BASE64.fullmatch(encoded) or not isinstance(digest, str):
        _fail("COMMAND_RECORD_INVALID", f"invalid {stream} Base64/digest fields")
    raw = _decode_canonical_base64(encoded, label=f"command {stream}")
    if _sha(raw) != digest:
        _fail("COMMAND_RECORD_DIGEST_MISMATCH", f"{stream} Base64/digest parity failed")
    return raw


def _validate_command_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != COMMAND_RECORD_KEYS:
        _fail("COMMAND_RECORD_INVALID", "command record has missing or extra fields")
    if not isinstance(record["command_id"], str) or not isinstance(record["argv"], list):
        _fail("COMMAND_RECORD_INVALID", "command identity fields are malformed")
    if any(not isinstance(value, str) for value in record["argv"]):
        _fail("COMMAND_RECORD_INVALID", "command argv must contain only strings")
    if not isinstance(record["cwd"], str) or not isinstance(record["environment"], dict):
        _fail("COMMAND_RECORD_INVALID", "command cwd/environment is malformed")
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in record["environment"].items()
    ):
        _fail("COMMAND_RECORD_INVALID", "command environment must map strings to strings")
    if not isinstance(record["exit_code"], int) or isinstance(record["exit_code"], bool):
        _fail("COMMAND_RECORD_INVALID", "command exit code must be an integer")
    _decode_command_stream(record, "stdout")
    _decode_command_stream(record, "stderr")
    return record


def _strict_command_text(raw: bytes, label: str) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail("COMMAND_OUTPUT_INVALID", f"{label} has a UTF-8 BOM")
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        _fail("COMMAND_OUTPUT_INVALID", f"{label} is not strict UTF-8")
    if unicodedata.normalize("NFC", value) != value:
        _fail("COMMAND_OUTPUT_INVALID", f"{label} is not Unicode NFC")
    return value


def _parse_pytest_summary(text: str) -> dict[str, int]:
    names = {
        "passed": "passed_count",
        "failed": "failed_count",
        "error": "error_count",
        "errors": "error_count",
        "skipped": "skipped_count",
        "xfailed": "xfailed_count",
        "xpassed": "xpassed_count",
        "warning": "warning_count",
        "warnings": "warning_count",
        "deselected": "deselected_count",
        "rerun": "retry_count",
        "reruns": "retry_count",
    }
    counts = {
        "passed_count": 0,
        "failed_count": 0,
        "error_count": 0,
        "skipped_count": 0,
        "xfailed_count": 0,
        "xpassed_count": 0,
        "warning_count": 0,
        "deselected_count": 0,
        "retry_count": 0,
    }
    category = (
        r"passed|failed|errors?|skipped|xfailed|xpassed|warnings?|"
        r"deselected|reruns?"
    )
    summary_pattern = re.compile(
        rf"^(?P<body>\d+ (?:{category})(?:, \d+ (?:{category}))*) "
        r"in \d+(?:\.\d+)?s(?: \([^\r\n()]+\))?$"
    )
    lines = text.splitlines()
    candidates = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := summary_pattern.fullmatch(line)) is not None
    ]
    nonempty_indices = [index for index, line in enumerate(lines) if line]
    if len(candidates) != 1 or not nonempty_indices or candidates[0][0] != nonempty_indices[-1]:
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest execution summary is absent, ambiguous, or nonterminal",
        )
    body = candidates[0][1].group("body")
    matches = list(re.finditer(rf"(\d+) ({category})(?:, |$)", body))
    mapped_names = [names[match.group(2)] for match in matches]
    if len(mapped_names) != len(set(mapped_names)):
        _fail("PREEDIT_EVIDENCE_INVALID", "pytest summary repeats a category")
    summary_like = re.compile(rf"(?<![A-Za-z0-9_])\d+ (?:{category})(?![A-Za-z0-9_])")
    if any(
        summary_like.search(line) for index, line in enumerate(lines) if index != candidates[0][0]
    ):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest output contains an ambiguous embedded outcome summary",
        )
    for match in matches:
        counts[names[match.group(2)]] = int(match.group(1))
    return counts


def _parse_pytest_collection(text: str) -> tuple[list[str], int, int]:
    lines = text.splitlines()
    summary_pattern = re.compile(r"^(\d+) tests? collected in \d+(?:\.\d+)?s(?: \([^\r\n()]+\))?$")
    summaries = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := summary_pattern.fullmatch(line)) is not None
    ]
    nonempty_indices = [index for index, line in enumerate(lines) if line]
    if len(summaries) != 1 or not nonempty_indices or summaries[0][0] != nonempty_indices[-1]:
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest collection summary is absent, ambiguous, or nonterminal",
        )
    summary_index, summary_match = summaries[0]
    node_ids = [line for line in lines[:summary_index] if line]
    if not node_ids or len(node_ids) != len(set(node_ids)):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest collection node IDs are empty or duplicate",
        )
    if any("::" not in line or line.startswith((" ", "<")) for line in node_ids):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest collection contains non-node output",
        )
    count = int(summary_match.group(1))
    if count != len(node_ids):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest collection summary differs from its node IDs",
        )
    return node_ids, count, 0


def _parse_pytest_failures(text: str) -> list[str]:
    return sorted(
        {match.group(1) for match in re.finditer(r"^FAILED\s+(\S+)", text, flags=re.MULTILINE)},
        key=lambda value: value.encode("utf-8"),
    )


def _canonical_input_schema() -> dict[str, Any]:
    try:
        compressed = base64.b64decode(
            _CANONICAL_INPUT_SCHEMA_ZLIB_BASE64.encode("ascii"), validate=True
        )
        raw = zlib.decompress(compressed)
    except (binascii.Error, UnicodeEncodeError, zlib.error):
        _fail("READY_INSTANCE_INVALID", "embedded canonical-input schema is corrupt")
    if _sha(raw) != CANONICAL_INPUT_SCHEMA_SHA256:
        _fail("READY_INSTANCE_INVALID", "embedded canonical-input schema digest differs")
    schema = _strict_json(raw, require_canonical=True)
    if not isinstance(schema, dict) or (
        schema.get("$schema") != SCHEMA_DRAFT_URI
        or schema.get("$id")
        != "https://metriplane.com/schemas/bootstrap/"
        "metriplane.bootstrap-materialization-input.v1.schema.json"
    ):
        _fail("READY_INSTANCE_INVALID", "embedded canonical-input schema identity differs")
    return schema


def _embedded_authority_schema(
    encoded: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    expected_id: str,
    label: str,
) -> dict[str, Any]:
    try:
        compressed = base64.b64decode(encoded.encode("ascii"), validate=True)
        raw = zlib.decompress(compressed)
    except (binascii.Error, UnicodeEncodeError, zlib.error):
        _fail("READY_INSTANCE_INVALID", f"embedded {label} schema is corrupt")
    if len(raw) != expected_bytes or _sha(raw) != expected_sha256:
        _fail("READY_INSTANCE_INVALID", f"embedded {label} schema digest differs")
    schema = _strict_json(raw, require_canonical=True)
    if not isinstance(schema, dict) or (
        schema.get("$schema") != SCHEMA_DRAFT_URI or schema.get("$id") != expected_id
    ):
        _fail("READY_INSTANCE_INVALID", f"embedded {label} schema identity differs")
    return schema


def _validate_pinned_authority_schema(
    value: dict[str, Any],
    *,
    encoded: str,
    expected_bytes: int,
    expected_sha256: str,
    expected_id: str,
    label: str,
) -> None:
    """Validate bootstrap evidence with the pinned or exact internal engine."""
    schema = _embedded_authority_schema(
        encoded,
        expected_bytes=expected_bytes,
        expected_sha256=expected_sha256,
        expected_id=expected_id,
        label=label,
    )
    try:
        _validate_with_available_engine(value, schema)
    except SnapshotError as exc:
        if exc.code != "SCHEMA_VALIDATION_FAILED":
            raise
        _fail(
            "READY_INSTANCE_INVALID",
            f"{label} authority-schema validation failed: {exc.message}",
        )


def _validate_canonical_materialization(
    canonical_input: Any,
    *,
    instance: Path,
    core_digests: dict[str, str],
    anchors_digest: str,
    authority_digest: str,
    environment: dict[str, Any],
    remote_proof: dict[str, Any],
    actor_permission_digest: str,
    manifest: dict[str, Any],
) -> None:
    if not isinstance(canonical_input, dict):
        _fail("READY_INSTANCE_INVALID", "canonical materialization root is not an object")
    try:
        _internal_validate(canonical_input, _canonical_input_schema())
    except SnapshotError as exc:
        _fail(
            "READY_INSTANCE_INVALID",
            f"canonical materialization schema validation failed: {exc.message}",
        )
    if (
        canonical_input.get("schema_version") != "metriplane.bootstrap-materialization-input.v1"
        or canonical_input.get("base_sha") != AUDITED_BASE_SHA
        or _sha(_canonical_bytes(canonical_input)) != instance.name
    ):
        _fail("READY_INSTANCE_INVALID", "canonical materialization identity differs")

    task = canonical_input.get("canonical_task_row")
    if not isinstance(task, dict) or not isinstance(task.get("row"), dict):
        _fail("READY_INSTANCE_INVALID", "canonical task row is missing")
    task_row = task["row"]
    if (
        task.get("catalog_schema_version") != "metriplane.mp2-work-order-set.v1"
        or task.get("catalog_sha256") != EXPECTED_CATALOG_SHA256
        or task.get("row_sha256") != EXPECTED_TASK_ROW_SHA256
        or _sha(_canonical_bytes(task_row)) != EXPECTED_TASK_ROW_SHA256
        or task_row.get("task_id") != TASK_ID
        or task_row.get("linear_issue") != "MET-69"
        or task_row.get("linear_milestone_id") != "cbefcf4c-5177-41d7-9ce0-6499e5af9d3c"
        or task_row.get("role") != "implementation"
        or task_row.get("authoritative_blocked_by") != []
    ):
        _fail("READY_INSTANCE_INVALID", "canonical task/catalog identity differs")

    issue_projection = canonical_input.get("live_issue_snapshot_and_relation_cursor")
    if not isinstance(issue_projection, dict) or not isinstance(
        issue_projection.get("issue"), dict
    ):
        _fail("READY_INSTANCE_INVALID", "canonical live issue projection is missing")
    issue = issue_projection["issue"]
    if (
        issue_projection.get("provider") != "Linear"
        or issue_projection.get("issue_sha256") != EXPECTED_ISSUE_SHA256
        or _sha(_canonical_bytes(issue)) != EXPECTED_ISSUE_SHA256
        or issue_projection.get("event_cursor") != issue.get("updated_at")
        or issue.get("id") != "MET-69"
        or issue.get("identifier") != "MET-69"
        or issue.get("milestone_id") != "cbefcf4c-5177-41d7-9ce0-6499e5af9d3c"
    ):
        _fail("READY_INSTANCE_INVALID", "canonical live issue identity differs")

    assignment = canonical_input.get("assignment_or_delegation_proof")
    if not isinstance(assignment, dict) or not isinstance(assignment.get("proof"), dict):
        _fail("READY_INSTANCE_INVALID", "canonical assignment proof is missing")
    assignment_proof = assignment["proof"]
    if (
        assignment.get("mode") != "provider_authenticated_assignee"
        or assignment.get("proof_sha256") != EXPECTED_ASSIGNMENT_PROOF_SHA256
        or _sha(_canonical_bytes(assignment_proof)) != EXPECTED_ASSIGNMENT_PROOF_SHA256
        or assignment_proof.get("issue_id") != "MET-69"
        or assignment_proof.get("issue_identifier") != "MET-69"
        or assignment_proof.get("repository_executor_github_login") != "Miko997"
    ):
        _fail("READY_INSTANCE_INVALID", "canonical assignment identity differs")
    remote_actor = remote_proof.get("authenticated_actor")
    if (
        remote_actor != EXPECTED_GITHUB_ACTOR
        or assignment_proof.get("repository_executor_github_login") != remote_actor.get("login")
        or _sha(_canonical_bytes(remote_actor)) != actor_permission_digest
    ):
        _fail(
            "READY_INSTANCE_INVALID",
            "canonical assignment and GitHub actor/permission differ",
        )

    if canonical_input.get("dependency_evidence") != []:
        _fail("READY_INSTANCE_INVALID", "MP2-000 canonical dependencies are not empty")

    resolved_profiles = canonical_input.get("resolved_environment_profiles")
    if not isinstance(resolved_profiles, dict) or set(resolved_profiles) != {
        "observations",
        "environment_profile_rows",
    }:
        _fail("READY_INSTANCE_INVALID", "canonical environment profiles are malformed")
    environment_digest = core_digests["environment_observation_sha256"]
    if resolved_profiles.get("observations") != [
        {"path": "environment-observation.json", "sha256": environment_digest}
    ]:
        _fail("READY_INSTANCE_INVALID", "canonical environment observation is unbound")
    rows = resolved_profiles.get("environment_profile_rows")
    derived = environment.get("derived")
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or not isinstance(derived, dict)
    ):
        _fail("READY_INSTANCE_INVALID", "canonical environment row is malformed")
    environment_row = rows[0]
    derived_bindings = {
        "profile": "profile",
        "os_release": "os_release",
        "kernel": "kernel",
        "architecture": "architecture",
        "python": "python",
        "uv": "uv",
        "filesystem": "filesystem",
        "browser": "browser",
        "hardware": "hardware",
    }
    if (
        environment_row.get("observation_sha256") != environment_digest
        or environment_row.get("row_id") != f"BOOTSTRAP.MP2-000.{environment_digest[:16]}"
        or environment_row.get("support_disposition") != "not_measured"
        or environment_row.get("claim_level") != "bootstrap_execution_observation_only"
        or any(
            environment_row.get(row_key) != derived.get(derived_key)
            for row_key, derived_key in derived_bindings.items()
        )
    ):
        _fail("READY_INSTANCE_INVALID", "canonical environment row is unbound")

    anchors = canonical_input.get("resolved_anchors_outputs_contracts")
    if not isinstance(anchors, dict):
        _fail("READY_INSTANCE_INVALID", "canonical anchor projection is missing")
    remote_digest = core_digests["github_remote_collision_proof_sha256"]
    if (
        anchors_digest != EXPECTED_RESOLVED_ANCHORS_SHA256
        or anchors.get("resolved_anchors_sha256") != anchors_digest
        or anchors.get("resolved_bootstrap_authority_sha256") != authority_digest
        or anchors.get("remote_collision_proofs")
        != [
            {
                "path": "github-remote-collision-proof.json",
                "provider": "GitHub",
                "sha256": remote_digest,
            }
        ]
    ):
        _fail("READY_INSTANCE_INVALID", "canonical anchor/core digests are unbound")
    create_rows = anchors.get("exact_existing_and_CREATE_paths")
    if (
        not isinstance(create_rows, list)
        or [row.get("path") if isinstance(row, dict) else None for row in create_rows]
        != list(EXPECTED_CREATE_PATHS)
        or any(
            not isinstance(row, dict)
            or row.get("state") != "CREATE"
            or row.get("owner_task") != TASK_ID
            or row.get("absence_or_identity_proof_sha256") != anchors_digest
            for row in create_rows
        )
    ):
        _fail("READY_INSTANCE_INVALID", "canonical CREATE rows are unbound")
    produced = anchors.get("produced_contract_paths_schemas_producers_validators_consumers")
    if not isinstance(produced, list) or [
        row.get("path") if isinstance(row, dict) else None for row in produced
    ] != list(EXPECTED_CREATE_PATHS):
        _fail("READY_INSTANCE_INVALID", "canonical produced-contract rows differ")
    consumed = anchors.get("consumed_contract_digests")
    if consumed != [
        {
            "contract": "12_TASK_WORK_ORDERS.json",
            "sha256": EXPECTED_CATALOG_SHA256,
        },
        {
            "contract": "13_BOOTSTRAP_EXECUTION_AUTHORITY.json",
            "sha256": EXPECTED_AUTHORITY_SHA256,
        },
    ]:
        _fail("READY_INSTANCE_INVALID", "canonical consumed contracts differ")

    typed_resources = canonical_input.get("typed_people_permissions_secrets_services_hardware")
    if (
        not isinstance(typed_resources, list)
        or len(typed_resources) != 1
        or not isinstance(typed_resources[0], dict)
        or typed_resources[0].get("kind") != "github_repository_read_visibility"
        or typed_resources[0].get("status") != "AVAILABLE"
        or typed_resources[0].get("availability_evidence_sha256") != actor_permission_digest
    ):
        _fail("READY_INSTANCE_INVALID", "canonical GitHub capability is unbound")

    commands = canonical_input.get("resolved_commands_and_obligations")
    if not isinstance(commands, dict):
        _fail("READY_INSTANCE_INVALID", "canonical command/obligation set is missing")
    resolved_obligations = commands.get("resolved_obligations")
    exact_commands = commands.get("exact_command_ids_argv_expected_exits_outputs")
    setup_commands = commands.get("toolchain_setup_commands")
    if (
        not isinstance(resolved_obligations, list)
        or [
            row.get("obligation_id") if isinstance(row, dict) else None
            for row in resolved_obligations
        ]
        != list(OBLIGATION_IDS)
        or not isinstance(exact_commands, list)
        or not isinstance(setup_commands, list)
    ):
        _fail("READY_INSTANCE_INVALID", "canonical obligations or commands differ")
    command_ids = {
        row.get("command_id") for row in [*exact_commands, *setup_commands] if isinstance(row, dict)
    }
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("command_ids"), list)
        or any(command_id not in command_ids for command_id in row["command_ids"])
        for row in resolved_obligations
    ):
        _fail("READY_INSTANCE_INVALID", "canonical obligation command binding differs")
    setup_results = environment.get("setup_command_results")
    if (
        not isinstance(setup_results, list)
        or [
            {
                "command_id": row.get("command_id"),
                "argv": row.get("argv"),
                "cwd": row.get("cwd"),
            }
            for row in setup_results
            if isinstance(row, dict)
        ]
        != setup_commands
    ):
        _fail("READY_INSTANCE_INVALID", "canonical setup commands are unbound")

    command_static = [
        {key: row.get(key) for key in ("command_id", "expected_exit", "expected_outputs")}
        for row in exact_commands
        if isinstance(row, dict)
    ]
    typed_static = [
        {key: row.get(key) for key in ("kind", "owner_or_authority", "requirement", "status")}
        for row in typed_resources
        if isinstance(row, dict)
    ]
    fixed_projections = {
        "repository_instruction": canonical_input.get(
            "repository_instruction_state_and_pr_contract_phase"
        ),
        "resolved_obligations": resolved_obligations,
        "criterion_mapping": commands.get("criterion_to_test_obligation_mapping"),
        "ordered_outcomes": commands.get("ordered_pr_outcomes"),
        "produced_contracts": produced,
        "typed_resource_static": typed_static,
        "manual_actions": canonical_input.get("manual_and_irreversible_actions"),
        "command_static": command_static,
    }
    if anchors.get("exact_symbols_routes_workflows_schemas") != [] or any(
        _sha(_canonical_bytes(value)) != EXPECTED_CANONICAL_PROJECTION_SHA256[name]
        for name, value in fixed_projections.items()
    ):
        _fail(
            "READY_INSTANCE_INVALID",
            "canonical fixed task/authority projections differ",
        )

    assignment_actor = assignment_proof.get("authenticated_actor_id")
    expected_manifest_assignment = {
        "actor_id": assignment_actor,
        "authority": "Linear authenticated assignee at bound issue cursor",
        "authority_scope": assignment_proof.get("authority_scope"),
        "mode": assignment.get("mode"),
    }
    manifest_equalities = {
        "repository_instruction_state_and_pr_contract_phase": canonical_input.get(
            "repository_instruction_state_and_pr_contract_phase"
        ),
        "exact_dependency_ids_and_merged_artifact_proof": canonical_input.get(
            "dependency_evidence"
        ),
        "exact_existing_and_CREATE_paths": anchors.get("exact_existing_and_CREATE_paths"),
        "exact_symbols_routes_workflows_schemas": anchors.get(
            "exact_symbols_routes_workflows_schemas"
        ),
        "produced_contract_paths_schemas_producers_validators_consumers": produced,
        "consumed_contract_digests": consumed,
        "environment_profile_rows": rows,
        "exact_command_ids_argv_expected_exits_outputs": exact_commands,
        "criterion_to_test_obligation_mapping": commands.get(
            "criterion_to_test_obligation_mapping"
        ),
        "ordered_pr_outcomes": commands.get("ordered_pr_outcomes"),
        "people_permissions_secrets_services_hardware": typed_resources,
        "manual_and_irreversible_actions": canonical_input.get("manual_and_irreversible_actions"),
    }
    if (
        manifest.get("schema_version") != "metriplane.task-work-order.v1"
        or manifest.get("task_id") != TASK_ID
        or manifest.get("linear_issue") != "MET-69"
        or manifest.get("base_sha") != AUDITED_BASE_SHA
        or manifest.get("materialization_id") != instance.name
        or manifest.get("canonical_materialization_input_digest") != instance.name
        or manifest.get("signed_assignment_or_delegation_record_digest")
        != EXPECTED_ASSIGNMENT_PROOF_SHA256
        or manifest.get("assignment_actor_and_authority") != expected_manifest_assignment
        or manifest.get("linear_issue_snapshot_digest_and_event_cursor")
        != {
            "event_cursor": issue_projection.get("event_cursor"),
            "provider": issue_projection.get("provider"),
            "sha256": issue_projection.get("issue_sha256"),
        }
        or any(manifest.get(key) != value for key, value in manifest_equalities.items())
    ):
        _fail("READY_INSTANCE_INVALID", "manifest/canonical projections differ")


def _canonical_baseline_present(instance: Path) -> bool:
    _, instance_fd = _open_directory_nofollow(
        instance, code="PREEDIT_EVIDENCE_INVALID", label="materialization instance"
    )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    evidence_fd: int | None = None
    try:
        try:
            evidence_fd = os.open("evidence", flags, dir_fd=instance_fd)
        except FileNotFoundError:
            return False
        except OSError as exc:
            _fail(
                "PREEDIT_EVIDENCE_INVALID",
                f"cannot open pre-edit evidence directory without links: {exc}",
            )
        try:
            info = os.stat(
                "pre-edit-baseline.json",
                dir_fd=evidence_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        except OSError as exc:
            _fail(
                "PREEDIT_EVIDENCE_INVALID",
                f"cannot inspect pre-edit baseline evidence: {exc}",
            )
        if not stat.S_ISREG(info.st_mode):
            _fail(
                "PREEDIT_EVIDENCE_INVALID",
                "pre-edit baseline evidence is not a regular non-symlink file",
            )
        return True
    finally:
        if evidence_fd is not None:
            os.close(evidence_fd)
        os.close(instance_fd)


def _instance_core(
    repo: Path, base_sha: str
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not _evidence_base_present(repo):
        _fail(
            "READY_INSTANCE_UNAVAILABLE",
            "MP2-000 exact-base work-order evidence root is absent",
        )
    instance_root = repo / "build" / "work-orders" / TASK_ID / base_sha
    try:
        children = sorted(instance_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        _fail(
            "READY_INSTANCE_UNAVAILABLE",
            f"cannot discover READY work-order instance: {exc}",
        )
    candidates: list[Path] = []
    for child in children:
        if HEX64.fullmatch(child.name) is None:
            continue
        try:
            child_info = child.lstat()
        except OSError as exc:
            _fail(
                "READY_INSTANCE_INVALID",
                f"cannot inspect materialization instance: {exc}",
            )
        if not stat.S_ISDIR(child_info.st_mode):
            _fail(
                "READY_INSTANCE_INVALID",
                f"materialization instance is not a no-follow directory: {child.name}",
            )
        if not _canonical_baseline_present(child):
            # A materialization without the canonical baseline remains retained
            # history and is ineligible without trusting any of its core files.
            continue
        if child.name != EXPECTED_MATERIALIZATION_ID:
            _fail(
                "READY_INSTANCE_AMBIGUOUS",
                "a canonical baseline exists outside the reviewed materialization",
            )
        candidates.append(child)
    ready: list[tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for instance in candidates:
        validation_raw = _read_regular(instance / "work-order-validation.json", MAX_EVIDENCE_BYTES)
        if (
            len(validation_raw) != EXPECTED_WORK_ORDER_VALIDATION_BYTES
            or _sha(validation_raw) != EXPECTED_WORK_ORDER_VALIDATION_SHA256
        ):
            _fail(
                "READY_INSTANCE_DIGEST_MISMATCH",
                "READY work-order validation differs from the reviewed immutable record",
            )
        validation = _strict_json(validation_raw, require_canonical=True)
        if not isinstance(validation, dict):
            _fail("READY_INSTANCE_INVALID", "work-order validation root must be an object")
        if validation.get("verdict") != "READY" or validation.get("exit_code") != 0:
            continue
        required_validation = {
            "schema_version",
            "task_id",
            "base_sha",
            "materialization_id",
            "manifest_sha256",
            "canonical_input_sha256",
            "environment_observation_sha256",
            "github_remote_collision_proof_sha256",
            "github_actor_permission_sha256",
            "authority_sha256",
            "validated_at",
            "verdict",
            "exit_code",
            "checks",
            "review",
        }
        if set(validation) != required_validation:
            _fail("READY_INSTANCE_INVALID", "READY validation has missing or extra fields")
        if (
            validation.get("schema_version") != "metriplane.task-work-order-validation.v1"
            or validation.get("verdict") != "READY"
            or validation.get("exit_code") != 0
            or validation.get("task_id") != TASK_ID
            or validation.get("base_sha") != base_sha
            or validation.get("materialization_id") != instance.name
            or validation.get("canonical_input_sha256") != instance.name
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "READY validation identity does not match its path",
            )
        core_names = {
            "manifest_sha256": "work-order.json",
            "canonical_input_sha256": "canonical-materialization-input.json",
            "environment_observation_sha256": "environment-observation.json",
            "github_remote_collision_proof_sha256": "github-remote-collision-proof.json",
        }
        parsed_core: dict[str, Any] = {}
        core_digests: dict[str, str] = {}
        for digest_field, filename in core_names.items():
            raw = _read_regular(instance / filename, MAX_EVIDENCE_BYTES)
            digest = _sha(raw)
            if filename == "work-order.json" and (
                len(raw) != EXPECTED_WORK_ORDER_MANIFEST_BYTES
                or digest != EXPECTED_WORK_ORDER_MANIFEST_SHA256
            ):
                _fail(
                    "READY_INSTANCE_DIGEST_MISMATCH",
                    "READY work-order manifest differs from the reviewed immutable record",
                )
            if validation.get(digest_field) != digest:
                _fail(
                    "READY_INSTANCE_DIGEST_MISMATCH",
                    f"READY core digest mismatch: {filename}",
                )
            core_digests[digest_field] = digest
            parsed_core[filename] = _strict_json(raw, require_canonical=True)
        authority_raw = _read_regular(
            instance / "resolved-bootstrap-authority.json", MAX_EVIDENCE_BYTES
        )
        if (
            validation.get("authority_sha256") != EXPECTED_AUTHORITY_SHA256
            or _sha(authority_raw) != EXPECTED_RESOLVED_AUTHORITY_SHA256
        ):
            _fail(
                "READY_INSTANCE_DIGEST_MISMATCH",
                "READY source or resolved authority digest mismatch",
            )
        resolved_authority = _strict_json(authority_raw, require_canonical=True)
        expected_resolved_authority_fields = {
            "authority_path",
            "authority_sha256",
            "base_sha",
            "base_tree",
            "expected_sha256",
            "schema_checks",
            "schema_version",
            "verdict",
        }
        if not isinstance(resolved_authority, dict) or (
            set(resolved_authority) != expected_resolved_authority_fields
            or resolved_authority.get("authority_path") != "13_BOOTSTRAP_EXECUTION_AUTHORITY.json"
            or resolved_authority.get("authority_sha256") != EXPECTED_AUTHORITY_SHA256
            or resolved_authority.get("expected_sha256") != EXPECTED_AUTHORITY_SHA256
            or resolved_authority.get("base_sha") != base_sha
            or resolved_authority.get("base_tree") != AUDITED_BASE_TREE
            or resolved_authority.get("schema_version")
            != "metriplane.resolved-bootstrap-authority.v1"
            or resolved_authority.get("verdict") != "PASS"
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "resolved bootstrap authority identity is invalid",
            )
        parsed_core["resolved-bootstrap-authority.json"] = resolved_authority
        anchors_raw = _read_regular(instance / "resolved-anchors.json", MAX_EVIDENCE_BYTES)
        parsed_core["resolved-anchors.json"] = _strict_json(anchors_raw, require_canonical=True)
        manifest = parsed_core["work-order.json"]
        if not isinstance(manifest, dict) or (
            set(manifest) != EXPECTED_WORK_ORDER_MANIFEST_FIELDS
            or manifest.get("task_id") != TASK_ID
            or manifest.get("base_sha") != base_sha
            or manifest.get("materialization_id") != instance.name
            or manifest.get("canonical_materialization_input_digest") != instance.name
        ):
            _fail("READY_INSTANCE_INVALID", "READY work-order manifest identity mismatch")
        if any(
            _sha(_canonical_bytes(manifest[field])) != digest
            for field, digest in EXPECTED_MANIFEST_ONLY_PROJECTION_SHA256.items()
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "READY work-order manifest-only authority projection differs",
            )
        environment = parsed_core["environment-observation.json"]
        if not isinstance(environment, dict) or (
            environment.get("task_id") != TASK_ID
            or environment.get("base_sha") != base_sha
            or environment.get("repository_root") != str(Path(os.path.abspath(repo)))
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "READY environment observation identity mismatch",
            )
        _environment_projection(environment)
        remote_proof = parsed_core["github-remote-collision-proof.json"]
        if (
            not isinstance(remote_proof, dict)
            or not isinstance(remote_proof.get("authenticated_actor"), dict)
            or validation.get("github_actor_permission_sha256")
            != _sha(_canonical_bytes(remote_proof["authenticated_actor"]))
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "READY authenticated actor/permission binding is invalid",
            )
        _validate_remote_proof(remote_proof, cast(str, environment["repository_root"]))
        _validate_canonical_materialization(
            parsed_core["canonical-materialization-input.json"],
            instance=instance,
            core_digests=core_digests,
            anchors_digest=_sha(anchors_raw),
            authority_digest=_sha(authority_raw),
            environment=environment,
            remote_proof=remote_proof,
            actor_permission_digest=cast(str, validation["github_actor_permission_sha256"]),
            manifest=manifest,
        )
        checks = validation.get("checks")
        if (
            not isinstance(checks, list)
            or tuple(item.get("check_id") if isinstance(item, dict) else None for item in checks)
            != EXPECTED_VALIDATION_CHECK_IDS
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "READY validation check identities or order differ",
            )
        for item in checks:
            if (
                not isinstance(item, dict)
                or set(item) != {"check_id", "evidence", "verdict"}
                or item.get("verdict") != "PASS"
                or not isinstance(item.get("evidence"), str)
                or not item["evidence"]
            ):
                _fail(
                    "READY_INSTANCE_INVALID",
                    "READY validation check is not an exact PASS record",
                )
        review = validation.get("review")
        review_keys = {
            "method",
            "review_evidence",
            "review_evidence_sha256",
            "reviewed_manifest_sha256",
            "reviewer_identity",
            "verdict",
        }
        if not isinstance(review, dict) or set(review) != review_keys:
            _fail("READY_INSTANCE_INVALID", "independent review record is malformed")
        review_evidence = review.get("review_evidence")
        review_evidence_keys = {
            "findings",
            "method",
            "reviewed_authority_sha256",
            "reviewed_canonical_input_sha256",
            "reviewed_check_ids",
            "reviewed_environment_observation_sha256",
            "reviewed_github_remote_collision_proof_sha256",
            "reviewed_manifest_sha256",
            "reviewed_resolved_anchors_sha256",
            "reviewed_resolved_bootstrap_authority_sha256",
            "reviewer_identity",
            "schema_version",
            "verdict",
        }
        if not isinstance(review_evidence, dict) or set(review_evidence) != review_evidence_keys:
            _fail("READY_INSTANCE_INVALID", "independent review evidence is malformed")
        expected_review_hashes = {
            "reviewed_authority_sha256": EXPECTED_AUTHORITY_SHA256,
            "reviewed_canonical_input_sha256": core_digests["canonical_input_sha256"],
            "reviewed_environment_observation_sha256": core_digests[
                "environment_observation_sha256"
            ],
            "reviewed_github_remote_collision_proof_sha256": core_digests[
                "github_remote_collision_proof_sha256"
            ],
            "reviewed_manifest_sha256": core_digests["manifest_sha256"],
            "reviewed_resolved_anchors_sha256": _sha(anchors_raw),
            "reviewed_resolved_bootstrap_authority_sha256": _sha(authority_raw),
        }
        if (
            review.get("method") != "independent_agent_review"
            or review.get("verdict") != "APPROVED"
            or review.get("reviewed_manifest_sha256") != core_digests["manifest_sha256"]
            or not isinstance(review.get("reviewer_identity"), str)
            or not review["reviewer_identity"]
            or review.get("review_evidence_sha256") != _sha(_canonical_bytes(review_evidence))
            or review_evidence.get("schema_version")
            != "metriplane.independent-work-order-review.v1"
            or review_evidence.get("method") != "independent_agent_review"
            or review_evidence.get("verdict") != "APPROVED"
            or review_evidence.get("findings") != []
            or review_evidence.get("reviewer_identity") != review.get("reviewer_identity")
            or review_evidence.get("reviewed_check_ids") != list(EXPECTED_VALIDATION_CHECK_IDS)
            or any(
                review_evidence.get(field) != digest
                for field, digest in expected_review_hashes.items()
            )
        ):
            _fail(
                "READY_INSTANCE_INVALID",
                "independent review does not bind all reviewed READY inputs",
            )
        tests = _preedit_tests(instance, manifest, environment)
        ready.append((instance, manifest, environment, tests))
    if len(ready) != 1:
        _fail(
            "READY_INSTANCE_AMBIGUOUS",
            "expected exactly one READY MP2-000 instance with canonical "
            f"pre-edit evidence, found {len(ready)}",
        )
    return ready[0]


def _manifest_command_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    commands = manifest.get("exact_command_ids_argv_expected_exits_outputs")
    if not isinstance(commands, list):
        _fail("READY_INSTANCE_INVALID", "work-order manifest command list is missing")
    mapped: dict[str, dict[str, Any]] = {}
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("command_id"), str):
            _fail("READY_INSTANCE_INVALID", "work-order command is malformed")
        command_id = command["command_id"]
        if command_id in mapped:
            _fail("READY_INSTANCE_INVALID", f"duplicate work-order command: {command_id}")
        mapped[command_id] = command
    return mapped


def _preedit_tests(
    instance: Path, manifest: dict[str, Any], environment: dict[str, Any]
) -> dict[str, Any]:
    evidence_path = instance / "evidence" / "pre-edit-baseline.json"
    raw = _read_regular(evidence_path, MAX_EVIDENCE_BYTES)
    if _sha(raw) != EXPECTED_PREEDIT_BASELINE_SHA256:
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pre-edit baseline evidence differs from the reviewed immutable record",
        )
    evidence = _strict_json(raw, require_canonical=True)
    expected_top = {
        "schema_version",
        "task_id",
        "base_sha",
        "materialization_id",
        "commands",
        "tests",
    }
    if not isinstance(evidence, dict) or set(evidence) != expected_top:
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pre-edit baseline has missing or extra top-level fields",
        )
    if (
        evidence.get("schema_version") != BASELINE_EVIDENCE_VERSION
        or evidence.get("task_id") != TASK_ID
        or evidence.get("base_sha") != AUDITED_BASE_SHA
        or evidence.get("materialization_id") != instance.name
    ):
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit baseline identity mismatch")
    command_records = evidence.get("commands")
    required_ids = [
        "MP2-000.CMD.ROOT_BASELINE",
        "MP2-000.CMD.COLLECT_BASELINE",
        "MP2-000.CMD.STATUS_IDENTITY",
    ]
    if not isinstance(command_records, list) or len(command_records) != len(required_ids):
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit baseline command set is incomplete")
    manifest_commands = _manifest_command_map(manifest)
    declared_environment = cast(dict[str, str], environment["declared_environment"])
    repository_root = cast(str, environment["repository_root"])
    bootstrap_python = f"{declared_environment['UV_PROJECT_ENVIRONMENT']}/bin/python"
    setup_results = cast(list[dict[str, Any]], environment["setup_command_results"])
    git_binary = cast(list[str], setup_results[0]["argv"])[0]
    exact_preedit_commands = {
        "MP2-000.CMD.ROOT_BASELINE": [
            bootstrap_python,
            "-m",
            "pytest",
            "-q",
        ],
        "MP2-000.CMD.COLLECT_BASELINE": [
            bootstrap_python,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
        ],
        "MP2-000.CMD.STATUS_IDENTITY": [
            git_binary,
            "status",
            "--porcelain=v1",
        ],
    }
    records: dict[str, dict[str, Any]] = {}
    for expected_id, candidate in zip(required_ids, command_records):
        record = _validate_command_record(candidate)
        if record["command_id"] != expected_id:
            _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit baseline command order differs")
        expected = manifest_commands.get(expected_id)
        if expected is None or any(
            record[field] != expected[field] for field in ("argv", "cwd", "environment")
        ):
            _fail(
                "PREEDIT_EVIDENCE_INVALID",
                f"pre-edit command binding mismatch: {expected_id}",
            )
        if (
            record["argv"] != exact_preedit_commands[expected_id]
            or record["cwd"] != repository_root
            or record["environment"] != declared_environment
        ):
            _fail(
                "PREEDIT_EVIDENCE_INVALID",
                f"pre-edit command authority differs: {expected_id}",
            )
        if record["exit_code"] != expected["expected_exit"]:
            _fail(
                "PREEDIT_EVIDENCE_INVALID",
                f"pre-edit command exit mismatch: {expected_id}",
            )
        records[expected_id] = record

    tests = evidence.get("tests")
    if not isinstance(tests, dict) or set(tests) != {
        "collection",
        "execution",
        "status_identity",
    }:
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit tests projection is malformed")
    collection = tests.get("collection")
    execution = tests.get("execution")
    status_identity = tests.get("status_identity")
    collection_keys = {
        "exit_code",
        "count",
        "node_ids",
        "stdout_sha256",
        "stderr_sha256",
        "warning_count",
    }
    execution_keys = {
        "exit_code",
        "collected_count",
        "passed_count",
        "failed_count",
        "error_count",
        "skipped_count",
        "xfailed_count",
        "xpassed_count",
        "warning_count",
        "deselected_count",
        "retry_count",
        "failure_node_ids",
    }
    if not isinstance(collection, dict) or set(collection) != collection_keys:
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit collection projection is malformed")
    if not isinstance(execution, dict) or set(execution) != execution_keys:
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit execution projection is malformed")
    integers = [
        collection["exit_code"],
        collection["count"],
        collection["warning_count"],
        *[execution[key] for key in execution_keys if key.endswith("_count") or key == "exit_code"],
    ]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in integers
    ):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pre-edit test counts/exits must be nonnegative integers",
        )
    node_ids = collection["node_ids"]
    failure_ids = execution["failure_node_ids"]
    if not isinstance(node_ids, list) or any(
        not isinstance(node, str) or not node for node in node_ids
    ):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pre-edit ordered collection node IDs are invalid",
        )
    if len(node_ids) != collection["count"] or len(node_ids) != len(set(node_ids)):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pre-edit ordered collection node IDs are invalid",
        )
    if not isinstance(failure_ids, list) or any(not isinstance(node, str) for node in failure_ids):
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit failure node IDs are invalid")
    node_id_set = set(node_ids)
    if failure_ids != sorted(set(failure_ids), key=lambda value: value.encode("utf-8")) or any(
        node not in node_id_set for node in failure_ids
    ):
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit failure node IDs are invalid")
    root = records["MP2-000.CMD.ROOT_BASELINE"]
    collect = records["MP2-000.CMD.COLLECT_BASELINE"]
    status = records["MP2-000.CMD.STATUS_IDENTITY"]
    root_stdout_raw = _decode_command_stream(root, "stdout")
    root_stderr_raw = _decode_command_stream(root, "stderr")
    collect_stdout_raw = _decode_command_stream(collect, "stdout")
    collect_stderr_raw = _decode_command_stream(collect, "stderr")
    root_text = _strict_command_text(root_stdout_raw, "root pytest stdout")
    _strict_command_text(root_stderr_raw, "root pytest stderr")
    collect_text = _strict_command_text(collect_stdout_raw, "collection stdout")
    _strict_command_text(collect_stderr_raw, "collection stderr")
    parsed_nodes, parsed_count, parsed_collection_warnings = _parse_pytest_collection(collect_text)
    parsed_execution = _parse_pytest_summary(root_text)
    parsed_failures = _parse_pytest_failures(root_text)
    if parsed_execution["failed_count"] != len(parsed_failures):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pytest failed count differs from raw failure node records",
        )
    if (
        collection["exit_code"] != collect["exit_code"]
        or execution["exit_code"] != root["exit_code"]
    ):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "parsed test exits differ from retained commands",
        )
    if any(collection[key] != collect[key] for key in ("stdout_sha256", "stderr_sha256")):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "parsed test stream digests differ from retained commands",
        )
    if (
        collection["node_ids"] != parsed_nodes
        or collection["count"] != parsed_count
        or collection["warning_count"] != parsed_collection_warnings
        or execution["collected_count"] != parsed_count
        or execution["failure_node_ids"] != parsed_failures
        or any(execution[key] != value for key, value in parsed_execution.items())
    ):
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "parsed test evidence differs from retained pytest streams",
        )
    if (
        collection["count"] != EXPECTED_TEST_COUNT
        or execution["collected_count"] != collection["count"]
    ):
        _fail("PREEDIT_EVIDENCE_INVALID", "audited pytest collection count is not 1194")
    outcome_total = sum(
        execution[key]
        for key in (
            "passed_count",
            "failed_count",
            "error_count",
            "skipped_count",
            "xfailed_count",
            "xpassed_count",
            "deselected_count",
        )
    )
    if outcome_total != execution["collected_count"]:
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "root pytest outcome counts do not sum to collection",
        )
    if (
        status["exit_code"] != 0
        or _decode_command_stream(status, "stdout") != b""
        or _decode_command_stream(status, "stderr") != b""
    ):
        _fail("PREEDIT_EVIDENCE_INVALID", "pre-edit repository status was not clean")
    expected_status = {
        "exit_code": 0,
        "clean": True,
        "stdout_sha256": status["stdout_sha256"],
        "stderr_sha256": status["stderr_sha256"],
    }
    if status_identity != expected_status:
        _fail(
            "PREEDIT_EVIDENCE_INVALID",
            "pre-edit status projection differs from retained command",
        )
    execution_projection = dict(execution)
    execution_projection.update(
        {
            "stdout_sha256": root["stdout_sha256"],
            "stderr_sha256": root["stderr_sha256"],
        }
    )
    return {"collection": collection, "execution": execution_projection}


def _receipt(collector: str, pr_number: int | None, arguments: Any, result: Any) -> dict[str, Any]:
    return {
        "arguments_sha256": _sha(_canonical_bytes(arguments)),
        "collector": collector,
        "pr_number": pr_number,
        "result_sha256": _sha(_canonical_bytes(result)),
    }


def _validate_remote_proof(remote: dict[str, Any], repository_root: str) -> None:
    _validate_pinned_authority_schema(
        remote,
        encoded=_GITHUB_REMOTE_SCHEMA_ZLIB_BASE64,
        expected_bytes=GITHUB_REMOTE_SCHEMA_BYTES,
        expected_sha256=GITHUB_REMOTE_SCHEMA_SHA256,
        expected_id=GITHUB_REMOTE_SCHEMA_ID,
        label="GitHub remote collision proof",
    )
    actor = cast(dict[str, Any], remote["authenticated_actor"])
    snapshot = cast(dict[str, Any], remote["remote_snapshot"])
    repository = cast(dict[str, Any], snapshot["repository"])
    branches = cast(list[dict[str, Any]], snapshot["branches"])
    pull_requests = cast(list[dict[str, Any]], snapshot["open_pull_requests"])
    completeness = cast(dict[str, Any], remote["completeness"])
    isolated = cast(dict[str, Any], remote["isolated_fetch"])
    if (
        remote["base_sha"] != AUDITED_BASE_SHA
        or remote["provider"] != "GitHub"
        or remote["target_paths"] != list(EXPECTED_CREATE_PATHS)
        or remote["semantic_regex"] != "baseline[-_ ]snapshot|MP2-000|MET-69"
        or remote["verdict"] != "NO_COLLISION"
        or actor != EXPECTED_GITHUB_ACTOR
        or repository
        != {
            "database_id": repository["database_id"],
            "default_branch": "main",
            "default_branch_sha": AUDITED_BASE_SHA,
            "full_name": REPOSITORY,
            "origin_url": "https://github.com/Miko997/metriplane.git",
        }
        or repository["default_branch_sha"] != AUDITED_BASE_SHA
        or remote["remote_snapshot_sha256"] != _sha(_canonical_bytes(snapshot))
        or remote["collisions"] != []
        or remote["history_hits"] != []
        or remote["ownership_metadata_hits"] != []
        or isolated
        != {
            "branch_ref_set_equal": True,
            "default_branch_head_equal_base": True,
            "open_pr_head_set_equal": True,
            "unavailable_heads": [],
        }
        or completeness
        != {
            "all_heads_inspected": True,
            "branch_collection_complete": True,
            "no_provider_or_fetch_drift": True,
            "open_pr_collection_complete": True,
            "open_pr_page_limit": 100,
            "open_pr_returned_count": len(pull_requests),
            "repository_visible": True,
        }
        or len(pull_requests) >= 100
    ):
        _fail("REMOTE_PROOF_INVALID", "remote proof identity or completeness differs")

    branch_names = [cast(str, row["name"]) for row in branches]
    pr_numbers = [cast(int, row["number"]) for row in pull_requests]
    if (
        branch_names != sorted(branch_names, key=lambda value: value.encode("utf-8"))
        or len(branch_names) != len(set(branch_names))
        or pr_numbers != sorted(pr_numbers)
        or len(pr_numbers) != len(set(pr_numbers))
        or [row["head_sha"] for row in branches if row["name"] == "main"] != [AUDITED_BASE_SHA]
    ):
        _fail("REMOTE_PROOF_INVALID", "remote branch or pull-request census differs")
    semantic = re.compile(remote["semantic_regex"], re.IGNORECASE)
    expected_heads: dict[str, list[str]] = {}
    for row in branches:
        name = cast(str, row["name"])
        _nfc(name, require_already_nfc=True)
        if semantic.search(name):
            _fail("REMOTE_PROOF_COLLISION", "semantic branch collision is present")
        expected_heads.setdefault(cast(str, row["head_sha"]), []).append(f"refs/heads/{name}")

    expected_receipts = [
        _receipt(
            "mcp__codex_apps__github_get_repo",
            None,
            {"repository_full_name": REPOSITORY},
            repository,
        ),
        _receipt(
            "mcp__codex_apps__github_get_user_login",
            None,
            {},
            {"database_id": actor["database_id"], "login": actor["login"]},
        ),
        _receipt(
            "mcp__codex_apps__github_get_repo_collaborator_permission",
            None,
            {"repository_full_name": REPOSITORY, "username": actor["login"]},
            actor["permission"],
        ),
        _receipt(
            "mcp__codex_apps__github_search_prs",
            None,
            {
                "order": "asc",
                "query": "is:pr is:open",
                "repository_full_name": REPOSITORY,
                "sort": "created",
                "state": "open",
                "topn": 100,
            },
            pr_numbers,
        ),
    ]
    target_paths = set(EXPECTED_CREATE_PATHS)
    for row in pull_requests:
        number = cast(int, row["number"])
        body = _decode_canonical_base64(row["body_base64"], label="pull-request body")
        if _sha(body) != row["body_sha256"]:
            _fail("REMOTE_PROOF_INVALID", "pull-request body digest differs")
        body_text = _strict_command_text(body, "pull-request body")
        changed_paths = cast(list[str], row["changed_paths"])
        if changed_paths != sorted(changed_paths, key=lambda value: value.encode("utf-8")) or len(
            changed_paths
        ) != len(set(changed_paths)):
            _fail("REMOTE_PROOF_INVALID", "pull-request changed paths differ")
        for path in changed_paths:
            _require_safe_relative_posix(
                path, code="REMOTE_PROOF_INVALID", label="pull-request changed path"
            )
        semantic_values = [
            cast(str, row["author_login"]),
            cast(str, row["head_ref"]),
            cast(str, row["title"]),
            body_text,
            *changed_paths,
        ]
        if target_paths.intersection(changed_paths) or any(
            semantic.search(value) for value in semantic_values
        ):
            _fail("REMOTE_PROOF_COLLISION", "pull-request collision is present")
        expected_heads.setdefault(cast(str, row["head_sha"]), []).append(f"refs/pull/{number}/head")
        arguments = {"pr_number": number, "repo_full_name": REPOSITORY}
        metadata = {key: value for key, value in row.items() if key != "changed_paths"}
        expected_receipts.extend(
            [
                _receipt(
                    "mcp__codex_apps__github_fetch_pr",
                    number,
                    arguments,
                    metadata,
                ),
                _receipt(
                    "mcp__codex_apps__github_list_pr_changed_filenames",
                    number,
                    arguments,
                    changed_paths,
                ),
            ]
        )
    if remote["collection_receipts"] != expected_receipts:
        _fail("REMOTE_PROOF_INVALID", "remote provider receipts are incomplete")

    inspected = cast(list[dict[str, Any]], remote["inspected_heads"])
    expected_head_shas = sorted(expected_heads)
    if [row["head_sha"] for row in inspected] != expected_head_shas:
        _fail("REMOTE_PROOF_INVALID", "remote inspected-head set is incomplete")
    for row in inspected:
        sha = cast(str, row["head_sha"])
        expected_refs = sorted(expected_heads[sha], key=lambda value: value.encode("utf-8"))
        if (
            row["source_refs"] != expected_refs
            or row["exact_path_hits"] != []
            or row["semantic_path_hits"] != []
            or row["semantic_content_hits"] != []
        ):
            _fail("REMOTE_PROOF_INVALID", "remote head inspection differs")

    expected_git_ids = [
        "LS_REMOTE_HEADS",
        "INIT_BARE",
        "REMOTE_ADD",
        "FETCH_BRANCHES",
        *[f"FETCH_PR_{number}" for number in pr_numbers],
        "LIST_FETCHED_REFS",
        *[
            command_id
            for sha in expected_head_shas
            for command_id in (f"LS_TREE_{sha}", f"GREP_{sha}")
        ],
        "HISTORY_CREATE_PATHS",
    ]
    command_results = cast(list[dict[str, Any]], remote["git_command_results"])
    if [row["command_id"] for row in command_results] != expected_git_ids:
        _fail("REMOTE_PROOF_INVALID", "remote Git command coverage or order differs")
    git_environment = {"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"}
    for candidate in command_results:
        record = _validate_command_record(candidate)
        command_id = cast(str, record["command_id"])
        expected_exits = {0, 1} if command_id.startswith("GREP_") else {0}
        if record["environment"] != git_environment or record["exit_code"] not in expected_exits:
            _fail("REMOTE_PROOF_INVALID", f"remote Git record differs: {command_id}")
    contract = cast(dict[str, Any], remote["collection_contract"])
    if command_results[0]["argv"] != contract["branch_argv"]:
        _fail("REMOTE_PROOF_INVALID", "ls-remote command differs from contract")
    command_map = {cast(str, row["command_id"]): row for row in command_results}
    git_binary = cast(list[str], command_results[0]["argv"])[0]
    _require_normalized_absolute_posix(
        git_binary, code="REMOTE_PROOF_INVALID", label="remote Git executable"
    )
    if PurePosixPath(git_binary).name != "git":
        _fail("REMOTE_PROOF_INVALID", "remote Git executable identity differs")
    init_argv = cast(list[str], command_map["INIT_BARE"]["argv"])
    proof_parent = cast(str, command_map["INIT_BARE"]["cwd"])
    if len(init_argv) != 4:
        _fail("REMOTE_PROOF_INVALID", "remote bare repository command differs")
    proof_repository = init_argv[3]
    _require_normalized_absolute_posix(
        proof_parent, code="REMOTE_PROOF_INVALID", label="remote proof parent"
    )
    _require_normalized_absolute_posix(
        proof_repository,
        code="REMOTE_PROOF_INVALID",
        label="remote bare repository",
    )
    git_dir = f"--git-dir={proof_repository}"
    if PurePosixPath(proof_repository).parent != PurePosixPath(proof_parent):
        _fail("REMOTE_PROOF_INVALID", "remote bare repository root differs")
    expected_git_argv: dict[str, list[str]] = {
        "LS_REMOTE_HEADS": cast(list[str], contract["branch_argv"]),
        "INIT_BARE": [git_binary, "init", "--bare", proof_repository],
        "REMOTE_ADD": [
            git_binary,
            git_dir,
            "remote",
            "add",
            "origin",
            "https://github.com/Miko997/metriplane.git",
        ],
        "FETCH_BRANCHES": [
            git_binary,
            git_dir,
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
        ],
        "LIST_FETCHED_REFS": [
            git_binary,
            git_dir,
            "for-each-ref",
            "--sort=refname",
            "--format=%(objectname)%09%(refname)",
            "refs/remotes/origin/",
            "refs/remotes/pull/",
        ],
        "HISTORY_CREATE_PATHS": [
            git_binary,
            git_dir,
            "log",
            "--all",
            "--format=%H",
            "--name-only",
            "-z",
            "--",
            *EXPECTED_CREATE_PATHS,
        ],
    }
    for number in pr_numbers:
        expected_git_argv[f"FETCH_PR_{number}"] = [
            git_binary,
            git_dir,
            "fetch",
            "--no-tags",
            "origin",
            f"+refs/pull/{number}/head:refs/remotes/pull/{number}/head",
        ]
    for sha in expected_head_shas:
        expected_git_argv[f"LS_TREE_{sha}"] = [
            git_binary,
            git_dir,
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            sha,
        ]
        expected_git_argv[f"GREP_{sha}"] = [
            git_binary,
            git_dir,
            "grep",
            "-I",
            "-n",
            "-i",
            "-E",
            remote["semantic_regex"],
            sha,
            "--",
            ".",
        ]
    if any(
        command_map[command_id]["argv"] != expected_git_argv[command_id]
        or command_map[command_id]["cwd"]
        != (repository_root if command_id == "LS_REMOTE_HEADS" else proof_parent)
        for command_id in expected_git_ids
    ):
        _fail("REMOTE_PROOF_INVALID", "remote Git argv or cwd differs")

    ls_remote_rows = "".join(
        f"{row['head_sha']}\trefs/heads/{row['name']}\n" for row in branches
    ).encode("utf-8")
    if (
        _decode_command_stream(command_map["LS_REMOTE_HEADS"], "stdout") != ls_remote_rows
        or _decode_command_stream(command_map["LS_REMOTE_HEADS"], "stderr") != b""
    ):
        _fail("REMOTE_PROOF_INVALID", "ls-remote output differs from branches")
    fetched_refs = [(f"refs/remotes/origin/{row['name']}", row["head_sha"]) for row in branches] + [
        (f"refs/remotes/pull/{row['number']}/head", row["head_sha"]) for row in pull_requests
    ]
    fetched_refs.sort(key=lambda row: row[0].encode("utf-8"))
    expected_fetched_stdout = "".join(
        f"{sha}\t{reference}\n" for reference, sha in fetched_refs
    ).encode("utf-8")
    if (
        _decode_command_stream(command_map["LIST_FETCHED_REFS"], "stdout")
        != expected_fetched_stdout
        or _decode_command_stream(command_map["LIST_FETCHED_REFS"], "stderr") != b""
    ):
        _fail("REMOTE_PROOF_INVALID", "fetched ref readback differs")

    tree_row = re.compile(rb"^[0-7]{6} (?:blob|tree|commit) [0-9a-f]{40}\t(.+)$")
    for sha in expected_head_shas:
        tree_stdout = _decode_command_stream(command_map[f"LS_TREE_{sha}"], "stdout")
        if tree_stdout and not tree_stdout.endswith(b"\x00"):
            _fail("REMOTE_PROOF_INVALID", "remote ls-tree output is unterminated")
        for raw_row in tree_stdout.rstrip(b"\x00").split(b"\x00"):
            if not raw_row:
                continue
            match = tree_row.fullmatch(raw_row)
            if match is None:
                _fail("REMOTE_PROOF_INVALID", "remote ls-tree row is malformed")
            try:
                path = match.group(1).decode("utf-8", "strict")
            except UnicodeDecodeError:
                _fail("REMOTE_PROOF_INVALID", "remote ls-tree path is not UTF-8")
            _require_safe_relative_posix(
                path, code="REMOTE_PROOF_INVALID", label="remote tree path"
            )
            if path in target_paths or semantic.search(path):
                _fail("REMOTE_PROOF_COLLISION", "remote tree collision is present")
        grep = command_map[f"GREP_{sha}"]
        if (
            grep["exit_code"] != 1
            or _decode_command_stream(grep, "stdout") != b""
            or _decode_command_stream(grep, "stderr") != b""
        ):
            _fail("REMOTE_PROOF_COLLISION", "remote content collision is present")
    history = command_map["HISTORY_CREATE_PATHS"]
    if (
        _decode_command_stream(history, "stdout") != b""
        or _decode_command_stream(history, "stderr") != b""
    ):
        _fail("REMOTE_PROOF_COLLISION", "remote path history collision is present")


def _environment_projection(environment: dict[str, Any]) -> dict[str, Any]:
    _validate_pinned_authority_schema(
        environment,
        encoded=_BOOTSTRAP_ENVIRONMENT_SCHEMA_ZLIB_BASE64,
        expected_bytes=BOOTSTRAP_ENVIRONMENT_SCHEMA_BYTES,
        expected_sha256=BOOTSTRAP_ENVIRONMENT_SCHEMA_SHA256,
        expected_id=BOOTSTRAP_ENVIRONMENT_SCHEMA_ID,
        label="bootstrap environment observation",
    )
    expected_top = {
        "schema_version",
        "task_id",
        "base_sha",
        "repository_root",
        "bootstrap_source_root",
        "declared_environment",
        "setup_command_results",
        "observation_command_results",
        "derived",
    }
    derived = environment.get("derived")
    results = environment.get("observation_command_results")
    declared = environment.get("declared_environment")
    setup_results = environment.get("setup_command_results")
    if (
        set(environment) != expected_top
        or environment.get("schema_version") != "metriplane.bootstrap-environment-observation.v1"
        or environment.get("task_id") != TASK_ID
        or environment.get("base_sha") != AUDITED_BASE_SHA
        or not isinstance(derived, dict)
        or not isinstance(results, list)
        or not isinstance(declared, dict)
        or not isinstance(setup_results, list)
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "environment observation identity or shape differs",
        )
    repository_root = cast(str, environment["repository_root"])
    bootstrap_source_root = cast(str, environment["bootstrap_source_root"])
    _require_normalized_absolute_posix(
        repository_root,
        code="ENVIRONMENT_EVIDENCE_INVALID",
        label="environment repository root",
    )
    _require_normalized_absolute_posix(
        bootstrap_source_root,
        code="ENVIRONMENT_EVIDENCE_INVALID",
        label="bootstrap source root",
    )
    expected_declared_constants = {
        "LC_ALL": "C.UTF-8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
    }
    if (
        set(declared)
        != set(expected_declared_constants) | {"UV_CACHE_DIR", "UV_PROJECT_ENVIRONMENT"}
        or any(declared.get(key) != value for key, value in expected_declared_constants.items())
        or not isinstance(declared.get("UV_CACHE_DIR"), str)
        or not isinstance(declared.get("UV_PROJECT_ENVIRONMENT"), str)
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "declared bootstrap environment differs",
        )
    uv_cache = cast(str, declared["UV_CACHE_DIR"])
    uv_environment = cast(str, declared["UV_PROJECT_ENVIRONMENT"])
    _require_normalized_absolute_posix(
        uv_cache, code="ENVIRONMENT_EVIDENCE_INVALID", label="UV cache directory"
    )
    _require_normalized_absolute_posix(
        uv_environment,
        code="ENVIRONMENT_EVIDENCE_INVALID",
        label="UV project environment",
    )
    bootstrap_root = str(PurePosixPath(bootstrap_source_root).parent)
    if (
        PurePosixPath(bootstrap_source_root).name != "source"
        or PurePosixPath(uv_cache).parent != PurePosixPath(bootstrap_root)
        or PurePosixPath(uv_environment).parent != PurePosixPath(bootstrap_root)
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "bootstrap source/cache/environment roots are inconsistent",
        )

    setup_ids = (
        "PREPARE_SOURCE_CLONE",
        "CHECKOUT_SOURCE_BASE",
        "VERIFY_SOURCE_IDENTITY",
        "VERIFY_SOURCE_CLEAN",
        "SYNC_FROZEN_NONEDITABLE",
        "INSTALL_SCHEMA_VALIDATOR_PINS",
    )
    setup_records = [_validate_command_record(row) for row in setup_results]
    if tuple(row["command_id"] for row in setup_records) != setup_ids:
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "bootstrap setup command identities or order differ",
        )
    for record in setup_records:
        if record["environment"] != declared or record["exit_code"] != 0:
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"bootstrap setup record differs: {record['command_id']}",
            )
        _decode_command_stream(record, "stdout")
        _decode_command_stream(record, "stderr")
    git_binary = cast(list[str], setup_records[0]["argv"])[0]
    uv_binary = cast(list[str], setup_records[4]["argv"])[0]
    sync_python = cast(list[str], setup_records[4]["argv"])[5]
    for executable, label in (
        (git_binary, "Git"),
        (uv_binary, "uv"),
        (sync_python, "bootstrap Python"),
    ):
        _require_normalized_absolute_posix(
            executable,
            code="ENVIRONMENT_EVIDENCE_INVALID",
            label=f"{label} executable",
        )
    if (
        PurePosixPath(git_binary).name != "git"
        or PurePosixPath(uv_binary).name != "uv"
        or not PurePosixPath(sync_python).name.startswith("python3.12")
    ):
        _fail("ENVIRONMENT_EVIDENCE_INVALID", "bootstrap executable identity differs")
    venv_python = f"{uv_environment}/bin/python"
    expected_setup_argv = [
        [
            git_binary,
            "-c",
            "core.hooksPath=/dev/null",
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            repository_root,
            bootstrap_source_root,
        ],
        [
            git_binary,
            "-C",
            bootstrap_source_root,
            "-c",
            "core.hooksPath=/dev/null",
            "checkout",
            "--detach",
            AUDITED_BASE_SHA,
        ],
        [
            git_binary,
            "-C",
            bootstrap_source_root,
            "rev-parse",
            "HEAD",
            "HEAD^{tree}",
        ],
        [
            git_binary,
            "-C",
            bootstrap_source_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        [
            uv_binary,
            "--no-config",
            "--quiet",
            "sync",
            "--python",
            sync_python,
            "--frozen",
            "--all-groups",
            "--no-editable",
        ],
        [
            uv_binary,
            "--no-config",
            "--quiet",
            "pip",
            "install",
            "--python",
            venv_python,
            "jsonschema==4.25.1",
            "rfc3339-validator==0.1.4",
        ],
    ]
    expected_setup_cwds = [
        bootstrap_root,
        bootstrap_root,
        bootstrap_root,
        bootstrap_root,
        bootstrap_source_root,
        bootstrap_source_root,
    ]
    if (
        [record["argv"] for record in setup_records] != expected_setup_argv
        or [record["cwd"] for record in setup_records] != expected_setup_cwds
        or _decode_command_stream(setup_records[2], "stdout")
        != f"{AUDITED_BASE_SHA}\n{AUDITED_BASE_TREE}\n".encode("ascii")
        or _decode_command_stream(setup_records[2], "stderr") != b""
        or _decode_command_stream(setup_records[3], "stdout") != b""
        or _decode_command_stream(setup_records[3], "stderr") != b""
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "bootstrap setup argv/cwd/source proof differs",
        )
    expected_ids = (
        "UNAME",
        "PYTHON_VERSION",
        "PLATFORM",
        "OS_RELEASE",
        "UV_VERSION",
        "LOCK_SHA256",
        "INSTALLED_DISTRIBUTIONS",
        "FILESYSTEM_HOME_CACHE",
    )
    mapped: dict[str, dict[str, Any]] = {}
    observed_ids: list[str] = []
    for candidate in results:
        record = _validate_command_record(candidate)
        command_id = record["command_id"]
        if command_id in mapped:
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"duplicate environment command: {command_id}",
            )
        if record["exit_code"] != 0 or _decode_command_stream(record, "stderr"):
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"environment observation did not pass cleanly: {command_id}",
            )
        observed_ids.append(command_id)
        mapped[command_id] = record
    if tuple(observed_ids) != expected_ids:
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "environment observation command identities or order differ",
        )
    observation_records = [mapped[command_id] for command_id in expected_ids]
    for record in observation_records:
        if record["environment"] != declared:
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"environment command override differs: {record['command_id']}",
            )
    uname_binary = cast(list[str], mapped["UNAME"]["argv"])[0]
    observed_python = cast(list[str], mapped["PYTHON_VERSION"]["argv"])[0]
    observed_uv = cast(list[str], mapped["UV_VERSION"]["argv"])[0]
    if (
        observed_python != venv_python
        or observed_uv != uv_binary
        or PurePosixPath(uname_binary).name != "uname"
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "environment observation executable identity differs",
        )
    _require_normalized_absolute_posix(
        uname_binary,
        code="ENVIRONMENT_EVIDENCE_INVALID",
        label="uname executable",
    )
    platform_program = (
        "import platform,sys; print(platform.platform()); "
        "print(platform.machine()); print(sys.implementation.cache_tag)"
    )
    os_release_program = (
        "import json,platform; d=platform.freedesktop_os_release(); "
        "out={k:d.get(k) for k in ('PRETTY_NAME','ID','VERSION_ID')}; "
        "print(json.dumps(out,ensure_ascii=False,allow_nan=False,sort_keys=True,"
        "separators=(',',':')))"
    )
    lock_program = (
        "import hashlib,pathlib,sys; "
        "print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())"
    )
    installed_program = (
        "import importlib.metadata as m,json,re,unicodedata; "
        "rows=[{'name':unicodedata.normalize('NFC',d.metadata['Name']),"
        "'normalized_name':re.sub(r'[-_.]+','-',unicodedata.normalize('NFC',"
        "d.metadata['Name'])).lower(),'version':unicodedata.normalize('NFC',"
        "d.version)} for d in m.distributions() if d.metadata.get('Name')]; "
        "rows.sort(key=lambda r:r['normalized_name'].encode('utf-8')); "
        "assert len(rows)==len({r['normalized_name'] for r in rows}); "
        "print(json.dumps(rows,ensure_ascii=False,allow_nan=False,sort_keys=True,"
        "separators=(',',':')))"
    )
    filesystem_program = (
        "import json,os,pathlib,sys; "
        "keys=('HOME','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME',"
        "'XDG_STATE_HOME','TMPDIR','UV_CACHE_DIR','UV_PROJECT_ENVIRONMENT'); "
        "allow={k:os.environ.get(k) for k in keys}; "
        "kinds={'repository_root':sys.argv[1],'home':allow['HOME'],"
        "'uv_cache_dir':allow['UV_CACHE_DIR'],'uv_project_environment':"
        "allow['UV_PROJECT_ENVIRONMENT'],'temporary_root':allow['TMPDIR']}; "
        "rows=[]; [(lambda p,k: rows.append({'kind':k,'path':str(p) if p else "
        "None,'exists':bool(p and p.exists()),'is_dir':bool(p and p.is_dir()),"
        "'readable':bool(p and os.access(p,os.R_OK)),'writable':bool(p and "
        "os.access(p,os.W_OK)),'device':p.stat().st_dev if p and p.exists() else "
        "None}))(pathlib.Path(v).resolve() if v else None,k) for k,v in "
        "kinds.items()]; out={'filesystem_encoding':sys.getfilesystemencoding(),"
        "'os_name':os.name,'sys_platform':sys.platform,'path_separator':os.sep,"
        "'allowlisted_environment':allow,'paths':rows}; "
        "print(json.dumps(out,ensure_ascii=False,allow_nan=False,sort_keys=True,"
        "separators=(',',':')))"
    )
    expected_observation_argv = [
        [uname_binary, "-srm"],
        [venv_python, "-VV"],
        [venv_python, "-c", platform_program],
        [venv_python, "-c", os_release_program],
        [uv_binary, "--version"],
        [venv_python, "-c", lock_program, f"{repository_root}/uv.lock"],
        [venv_python, "-c", installed_program],
        [venv_python, "-c", filesystem_program, repository_root],
    ]
    expected_observation_cwds = [
        repository_root,
        repository_root,
        repository_root,
        repository_root,
        repository_root,
        repository_root,
        bootstrap_root,
        repository_root,
    ]
    if [record["argv"] for record in observation_records] != expected_observation_argv or [
        record["cwd"] for record in observation_records
    ] != expected_observation_cwds:
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "environment observation argv/cwd templates differ",
        )

    def output_text(command_id: str) -> str:
        return _strict_command_text(
            _decode_command_stream(mapped[command_id], "stdout"),
            f"{command_id} stdout",
        )

    def one_line(command_id: str) -> str:
        text = output_text(command_id)
        if not text.endswith("\n") or "\n" in text[:-1] or not text[:-1]:
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"{command_id} stdout is not one nonempty LF-terminated line",
            )
        return text[:-1]

    def canonical_json_line(command_id: str) -> Any:
        raw = _decode_command_stream(mapped[command_id], "stdout")
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"{command_id} stdout is not one canonical JSON line",
            )
        value = _strict_json(raw[:-1], require_canonical=True)
        if raw != _canonical_bytes(value) + b"\n":
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                f"{command_id} stdout is not one canonical JSON line",
            )
        return value

    platform_text = output_text("PLATFORM")
    platform_lines = platform_text.splitlines()
    if (
        len(platform_lines) != 3
        or not platform_text.endswith("\n")
        or any(not line for line in platform_lines)
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "PLATFORM stdout does not contain its exact three-line identity",
        )
    os_release_record = canonical_json_line("OS_RELEASE")
    installed_record = canonical_json_line("INSTALLED_DISTRIBUTIONS")
    filesystem_record = canonical_json_line("FILESYSTEM_HOME_CACHE")
    if (
        not isinstance(os_release_record, dict)
        or not isinstance(os_release_record.get("PRETTY_NAME"), str)
        or not isinstance(installed_record, list)
        or not installed_record
        or not isinstance(filesystem_record, dict)
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "environment JSON observation output has an invalid shape",
        )
    filesystem_digest = derived.get("filesystem")
    home_cache = derived.get("filesystem_home_cache")
    if (
        not isinstance(filesystem_digest, str)
        or not filesystem_digest.startswith("sha256:")
        or not HEX64.fullmatch(filesystem_digest.removeprefix("sha256:"))
        or not isinstance(home_cache, dict)
        or home_cache != filesystem_record
        or _sha(_canonical_bytes(home_cache)) != filesystem_digest.removeprefix("sha256:")
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "filesystem home/cache projection digest mismatch",
        )
    installed = derived.get("installed_distributions")
    if not isinstance(installed, list) or not installed or installed != installed_record:
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "installed distribution inventory is missing",
        )
    normalized_distribution_names: list[str] = []
    for row in installed:
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "normalized_name", "version"}
            or not all(isinstance(row.get(key), str) and row[key] for key in row)
        ):
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                "installed distribution row is malformed",
            )
        name = _nfc(cast(str, row["name"]), require_already_nfc=True)
        _nfc(cast(str, row["version"]), require_already_nfc=True)
        normalized_name = re.sub(r"[-_.]+", "-", name).lower()
        if row["normalized_name"] != normalized_name:
            _fail(
                "ENVIRONMENT_EVIDENCE_INVALID",
                "installed distribution normalization differs",
            )
        normalized_distribution_names.append(normalized_name)
    if normalized_distribution_names != sorted(
        normalized_distribution_names, key=lambda value: value.encode("utf-8")
    ) or len(normalized_distribution_names) != len(set(normalized_distribution_names)):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "installed distribution order or uniqueness differs",
        )
    allowlisted = home_cache.get("allowlisted_environment")
    paths = home_cache.get("paths")
    allowlisted_keys = {
        "HOME",
        "TMPDIR",
        "UV_CACHE_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
    }
    if (
        not isinstance(allowlisted, dict)
        or set(allowlisted) != allowlisted_keys
        or allowlisted.get("UV_CACHE_DIR") != uv_cache
        or allowlisted.get("UV_PROJECT_ENVIRONMENT") != uv_environment
        or not isinstance(paths, list)
        or len(paths) != 5
    ):
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "filesystem allowlist or path census differs",
        )
    expected_filesystem_paths = [
        ("repository_root", repository_root),
        ("home", allowlisted.get("HOME")),
        ("uv_cache_dir", uv_cache),
        ("uv_project_environment", uv_environment),
        ("temporary_root", allowlisted.get("TMPDIR")),
    ]
    if [
        (row.get("kind"), row.get("path")) if isinstance(row, dict) else None for row in paths
    ] != expected_filesystem_paths:
        _fail(
            "ENVIRONMENT_EVIDENCE_INVALID",
            "filesystem path rows do not bind the declared roots",
        )
    expected_derived_keys = {
        "profile",
        "os_release",
        "kernel",
        "architecture",
        "python",
        "uv",
        "lock_sha256",
        "installed_distributions",
        "filesystem",
        "filesystem_home_cache",
        "browser",
        "hardware",
    }
    if any(
        not isinstance(derived.get(key), str) or not derived[key]
        for key in (
            "profile",
            "os_release",
            "kernel",
            "architecture",
            "python",
            "uv",
            "lock_sha256",
        )
    ):
        _fail("ENVIRONMENT_EVIDENCE_INVALID", "environment derived identity is incomplete")
    if (
        set(derived) != expected_derived_keys
        or derived["profile"] != "bootstrap-lock-derived-root-suite"
        or derived.get("browser") is not None
        or derived.get("hardware") is not None
        or derived["kernel"] != one_line("UNAME")
        or derived["python"] != one_line("PYTHON_VERSION")
        or derived["architecture"] != platform_lines[1]
        or derived["os_release"] != os_release_record["PRETTY_NAME"]
        or derived["uv"] != one_line("UV_VERSION")
        or derived["lock_sha256"] != one_line("LOCK_SHA256")
        or derived["lock_sha256"]
        != "5857debd56a7d0a82bb7057c4edae136644b0887765423e73be41002f8ba5f70"
    ):
        _fail("ENVIRONMENT_EVIDENCE_INVALID", "bootstrap profile or lock identity changed")
    return {
        "support_disposition": "not_measured",
        "claim_level": "bootstrap_execution_observation_only",
        "profile": derived["profile"],
        "os_release": derived["os_release"],
        "kernel": derived["kernel"],
        "architecture": derived["architecture"],
        "python": derived["python"],
        "python_cache_tag": platform_lines[2],
        "uv": derived["uv"],
        "lock_sha256": derived["lock_sha256"],
        "installed_distributions": installed,
        "filesystem": {
            "sha256": filesystem_digest,
            "home_cache": home_cache,
        },
    }


def _installed_help(objects: GitObjects) -> dict[str, Any]:
    pyproject = tomllib.loads(objects.blob("pyproject.toml").decode("utf-8", "strict"))
    scripts = pyproject.get("project", {}).get("scripts")
    expected_entry_points = {
        "metriplane": "metriplane.cli:main",
        "metriplane-run": "metriplane.run:main",
    }
    if scripts != expected_entry_points:
        _fail(
            "CONSOLE_SCRIPT_CONTRACT_MISMATCH",
            "exact-base console script declarations changed",
        )
    try:
        distribution = importlib.metadata.distribution("metriplane")
    except importlib.metadata.PackageNotFoundError:
        _fail(
            "INSTALLED_PACKAGE_MISSING",
            "installed metriplane distribution is unavailable",
        )
    if distribution.version != AUDITED_VERSION:
        _fail(
            "INSTALLED_VERSION_MISMATCH",
            "installed metriplane version differs from audited base",
        )
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            direct = json.loads(direct_url)
        except json.JSONDecodeError:
            _fail(
                "INSTALLED_PACKAGE_INVALID",
                "installed distribution direct_url.json is malformed",
            )
        if direct.get("dir_info", {}).get("editable") is True:
            _fail(
                "EDITABLE_INSTALL_PROHIBITED",
                "installed help must not come from an editable checkout",
            )

    rows: list[dict[str, Any]] = []
    for command, entry_point in expected_entry_points.items():
        # Console scripts must be adjacent to the invoked interpreter.  Do not resolve the
        # venv interpreter symlink to the bootstrap runtime's underlying Python directory.
        executable = Path(os.path.abspath(sys.executable)).parent / command
        try:
            info = executable.lstat()
        except OSError:
            _fail(
                "CONSOLE_SCRIPT_MISSING",
                f"installed console script is missing: {command}",
            )
        if not stat.S_ISREG(info.st_mode) or not os.access(executable, os.X_OK):
            _fail(
                "CONSOLE_SCRIPT_INVALID",
                f"installed console script is not an executable regular file: {command}",
            )
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update({"PYTHONNOUSERSITE": "1", "LC_ALL": "C.UTF-8"})
        result = subprocess.run(
            [str(executable), "--help"],
            cwd=str(executable.parent),
            env=env,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or result.stderr:
            _fail(
                "INSTALLED_HELP_FAILED",
                f"installed {command} --help did not exit cleanly",
            )
        try:
            stdout = result.stdout.decode("utf-8", "strict")
            stderr = result.stderr.decode("utf-8", "strict")
        except UnicodeDecodeError:
            _fail(
                "INSTALLED_HELP_INVALID",
                f"installed {command} help is not strict UTF-8",
            )
        _nfc(stdout, require_already_nfc=True)
        _nfc(stderr, require_already_nfc=True)
        _, expected_size, expected_digest = EXPECTED_HELP_IDENTITIES[command]
        if len(result.stdout) != expected_size or _sha(result.stdout) != expected_digest:
            _fail(
                "INSTALLED_HELP_MISMATCH",
                f"installed {command} help differs from audited base",
            )
        rows.append(
            {
                "command": command,
                "entry_point": entry_point,
                "version": AUDITED_VERSION,
                "argv": [command, "--help"],
                "exit_code": result.returncode,
                "stdout": stdout,
                "stdout_sha256": _sha(result.stdout),
                "stderr": stderr,
                "stderr_sha256": _sha(result.stderr),
            }
        )
    return {"entries": rows}


def _source_identity(objects: GitObjects) -> dict[str, str]:
    tree = _ast_tree(objects, "metriplane/__init__.py")
    versions: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "__version__"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            versions.append(node.value.value)
    if versions != [AUDITED_VERSION]:
        _fail("VERSION_MISMATCH", "exact-base package version declaration changed")
    return {
        "repository": REPOSITORY,
        "commit": objects.base_sha,
        "tree": objects.tree_sha,
        "version": versions[0],
    }


def _limitations() -> list[dict[str, Any]]:
    return [
        {
            "limitation_id": "CLI_ROOT_ONLY",
            "disposition": "bounded_seed",
            "statement": "Root installed help is frozen; complete CLI leaf/action discovery is not yet claimed.",
            "downstream_owner_task_ids": ["MP2-011"],
            "claim_effect": "not_complete_cli_inventory",
        },
        {
            "limitation_id": "ROUTE_DECLARATIONS_ONLY",
            "disposition": "bounded_seed",
            "statement": "Terminal declarations are frozen; complete route/service/page/UI action semantics are not yet claimed.",
            "downstream_owner_task_ids": ["MP2-012"],
            "claim_effect": "not_complete_route_action_inventory",
        },
        {
            "limitation_id": "RESOURCE_SEED_ONLY",
            "disposition": "bounded_seed",
            "statement": "The 256-row resource census is a bounded repository seed, not complete semantic resource classification.",
            "downstream_owner_task_ids": ["MP2-013"],
            "claim_effect": "not_complete_resource_inventory",
        },
        {
            "limitation_id": "GENERATED_MODEL_SCHEMAS_DEFERRED",
            "disposition": "deferred",
            "statement": "Generated runtime model schemas are not inventoried unless already maintained as tracked schema files.",
            "downstream_owner_task_ids": ["MP2-013"],
            "claim_effect": "not_complete_schema_inventory",
        },
        {
            "limitation_id": "ROUTE_OVERACCEPTANCE_UNCHARACTERIZED",
            "disposition": "not_characterized",
            "statement": "Runner job prefix and cancel prefix/suffix matching accept tails beyond the normalized intended templates.",
            "downstream_owner_task_ids": ["MP2-012", "MP2-015"],
            "claim_effect": "not_supported_behavior",
        },
        {
            "limitation_id": "BOOTSTRAP_ENVIRONMENT_NOT_MEASURED",
            "disposition": "not_measured",
            "statement": "The bootstrap environment proves this task on one cell and does not establish a supported-environment claim.",
            "downstream_owner_task_ids": ["MP2-007"],
            "claim_effect": "not_supported_environment",
        },
    ]


def _build_snapshot(repo: Path, base_sha: str) -> dict[str, Any]:
    _, _, environment_observation, tests = _instance_core(repo, base_sha)
    objects = GitObjects(repo, base_sha)
    return {
        "schema_version": SCHEMA_VERSION,
        "captured_source": _source_identity(objects),
        "tracked_tree": _tracked_tree(objects),
        "commands_and_help": _installed_help(objects),
        "http_routes": _http_routes(objects),
        "schemas": _schemas(objects),
        "resources": _resources(objects),
        "workflows_and_jobs": _workflows(objects),
        "tests": tests,
        "environment": _environment_projection(environment_observation),
        "limitations": _limitations(),
    }


def _open_output_directory(path: Path) -> tuple[Path, int]:
    return _open_directory_nofollow(path, code="OUTPUT_PARENT_INVALID", label="output parent")


def _dir_entry_exists(directory_fd: int, leaf: str) -> bool:
    try:
        os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        _fail("OUTPUT_INSPECTION_FAILED", f"cannot inspect output leaf {leaf}: {exc}")


def _write_stage(directory_fd: int, leaf: str, data: bytes) -> tuple[int, int]:
    _require_descriptor_capabilities()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    file_fd: int | None = None
    created_opened = False
    created_identity: tuple[int, int] | None = None
    failure: BaseException | None = None
    try:
        file_fd = os.open(leaf, flags, 0o600, dir_fd=directory_fd)
        created_opened = True
        created = os.fstat(file_fd)
        created_identity = (created.st_dev, created.st_ino)
        if not stat.S_ISREG(created.st_mode):
            _fail("OUTPUT_WRITE_FAILED", f"staging leaf is not regular: {leaf}")
        view = memoryview(data)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                _fail("OUTPUT_WRITE_FAILED", f"short write for staging leaf {leaf}")
            view = view[written:]
        os.fchmod(file_fd, 0o644)
        os.fsync(file_fd)
    except BaseException as exc:  # noqa: BLE001 - owned stage cleanup precedes raise.
        failure = exc
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
    if failure is None:
        if created_identity is None:
            _fail("OUTPUT_WRITE_FAILED", f"staging identity is unavailable: {leaf}")
        return created_identity
    cleanup_error = _unlink_owned_entry(directory_fd, leaf, created_identity)
    if created_opened and created_identity is None:
        cleanup_error = f"{leaf}: safe cleanup ownership could not be established after open"
    if isinstance(failure, (KeyboardInterrupt, SystemExit)):
        raise failure
    detail = f"; cleanup issue: {cleanup_error}" if cleanup_error else ""
    if isinstance(failure, SnapshotError):
        _fail(
            "OUTPUT_WRITE_FAILED",
            f"{failure.code}: {failure.message}{detail}",
        )
    if isinstance(failure, OSError):
        _fail(
            "OUTPUT_WRITE_FAILED",
            f"cannot write staging leaf {leaf}: {failure}{detail}",
        )
    _fail(
        "OUTPUT_WRITE_FAILED",
        f"unexpected staging failure: {type(failure).__name__}{detail}",
    )


def _try_unlink(directory_fd: int, leaf: str) -> str | None:
    try:
        os.unlink(leaf, dir_fd=directory_fd)
        return None
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{leaf}: {exc}"


def _entry_identity(directory_fd: int, leaf: str) -> tuple[int, int] | None:
    try:
        info = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino


def _entry_has_identity(directory_fd: int, leaf: str, identity: tuple[int, int] | None) -> bool:
    return identity is not None and _entry_identity(directory_fd, leaf) == identity


def _unlink_owned_entry(
    directory_fd: int, leaf: str, identity: tuple[int, int] | None
) -> str | None:
    if identity is None:
        return None
    try:
        current = _entry_identity(directory_fd, leaf)
    except OSError as exc:
        return f"{leaf}: cannot inspect entry identity: {exc}"
    if current is None:
        return None
    if current != identity:
        return f"{leaf}: entry identity changed"
    return _try_unlink(directory_fd, leaf)


def _preflight_capture_outputs(output: Path, checksum_output: Path) -> tuple[Path, int]:
    if output.name != SNAPSHOT_LEAF or checksum_output.name != CHECKSUM_LEAF:
        _fail(
            "OUTPUT_NAME_INVALID",
            f"capture outputs must be named {SNAPSHOT_LEAF} and {CHECKSUM_LEAF}",
        )
    output_parent = Path(os.path.abspath(output.parent))
    checksum_parent = Path(os.path.abspath(checksum_output.parent))
    if output_parent != checksum_parent:
        _fail(
            "OUTPUT_PARENT_MISMATCH",
            "snapshot and checksum outputs must share one exact parent",
        )
    _, directory_fd = _open_output_directory(output_parent)
    try:
        if _dir_entry_exists(directory_fd, SNAPSHOT_LEAF) or _dir_entry_exists(
            directory_fd, CHECKSUM_LEAF
        ):
            _fail(
                "OUTPUT_EXISTS",
                "capture never overwrites an existing snapshot or checksum entry",
            )
        return output_parent, directory_fd
    except Exception:
        os.close(directory_fd)
        raise


def _require_output_parent_identity(path: Path, directory_fd: int) -> None:
    try:
        opened = os.fstat(directory_fd)
    except OSError as exc:
        _fail(
            "OUTPUT_PARENT_RACE",
            f"cannot inspect opened output parent identity: {exc}",
        )
    if not stat.S_ISDIR(opened.st_mode):
        _fail("OUTPUT_PARENT_RACE", "opened output parent is no longer a directory")
    candidate_fd: int | None = None
    try:
        _, candidate_fd = _open_directory_nofollow(
            path,
            code="OUTPUT_PARENT_RACE",
            label="requested output parent",
        )
        candidate = os.fstat(candidate_fd)
    except SnapshotError:
        raise
    except OSError as exc:
        _fail(
            "OUTPUT_PARENT_RACE",
            f"cannot revalidate requested output parent identity: {exc}",
        )
    finally:
        if candidate_fd is not None:
            try:
                os.close(candidate_fd)
            except OSError:
                pass
    if not stat.S_ISDIR(candidate.st_mode) or (candidate.st_dev, candidate.st_ino) != (
        opened.st_dev,
        opened.st_ino,
    ):
        _fail(
            "OUTPUT_PARENT_RACE",
            "requested output parent changed during paired publication",
        )


def _publish_pair_at(
    directory_fd: int,
    snapshot_bytes: bytes,
    *,
    requested_parent: Path | None = None,
) -> None:
    sidecar = f"{_sha(snapshot_bytes)}  {SNAPSHOT_LEAF}\n".encode("ascii")
    if len(sidecar) != 92:
        _fail("CHECKSUM_INTERNAL_ERROR", "checksum sidecar length is not exactly 92 bytes")
    token = secrets.token_hex(16)
    stage_snapshot = f".{SNAPSHOT_LEAF}.stage.{os.getpid()}.{token}"
    stage_checksum = f".{CHECKSUM_LEAF}.stage.{os.getpid()}.{token}"
    snapshot_identity: tuple[int, int] | None = None
    checksum_identity: tuple[int, int] | None = None
    failure: BaseException | None = None
    try:
        if requested_parent is not None:
            _require_output_parent_identity(requested_parent, directory_fd)
        if _dir_entry_exists(directory_fd, SNAPSHOT_LEAF) or _dir_entry_exists(
            directory_fd, CHECKSUM_LEAF
        ):
            _fail(
                "OUTPUT_EXISTS",
                "capture never overwrites an existing snapshot or checksum entry",
            )
        snapshot_identity = _write_stage(directory_fd, stage_snapshot, snapshot_bytes)
        checksum_identity = _write_stage(directory_fd, stage_checksum, sidecar)
        if requested_parent is not None:
            _require_output_parent_identity(requested_parent, directory_fd)
        os.link(
            stage_snapshot,
            SNAPSHOT_LEAF,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        os.link(
            stage_checksum,
            CHECKSUM_LEAF,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        os.fsync(directory_fd)
        stage_cleanup_errors = [
            error
            for error in (
                _unlink_owned_entry(directory_fd, stage_snapshot, snapshot_identity),
                _unlink_owned_entry(directory_fd, stage_checksum, checksum_identity),
            )
            if error is not None
        ]
        if stage_cleanup_errors:
            _fail(
                "OUTPUT_CLEANUP_FAILED",
                "cannot remove published staging links: " + "; ".join(stage_cleanup_errors),
            )
        os.fsync(directory_fd)
        if requested_parent is not None:
            _require_output_parent_identity(requested_parent, directory_fd)
    except BaseException as exc:  # noqa: BLE001 - rollback precedes propagation.
        failure = exc

    if failure is None:
        return

    rollback_errors: list[str] = []
    for final_leaf, identity in (
        (CHECKSUM_LEAF, checksum_identity),
        (SNAPSHOT_LEAF, snapshot_identity),
    ):
        error = _unlink_owned_entry(directory_fd, final_leaf, identity)
        if error is not None:
            rollback_errors.append(error)
    for stage, identity in (
        (stage_snapshot, snapshot_identity),
        (stage_checksum, checksum_identity),
    ):
        error = _unlink_owned_entry(directory_fd, stage, identity)
        if error is not None:
            rollback_errors.append(error)
    try:
        os.fsync(directory_fd)
    except OSError as exc:
        rollback_errors.append(f"directory fsync: {exc}")

    if isinstance(failure, (KeyboardInterrupt, SystemExit)):
        raise failure
    detail = f"; rollback issues: {'; '.join(rollback_errors)}" if rollback_errors else ""
    if isinstance(failure, SnapshotError) and not rollback_errors:
        raise failure
    if isinstance(failure, SnapshotError):
        _fail(
            "ATOMIC_PUBLICATION_FAILED",
            f"{failure.code}: {failure.message}{detail}",
        )
    if isinstance(failure, OSError):
        _fail(
            "ATOMIC_PUBLICATION_FAILED",
            f"paired no-overwrite publication failed: {failure}{detail}",
        )
    _fail(
        "ATOMIC_PUBLICATION_FAILED",
        f"unexpected publication failure: {type(failure).__name__}{detail}",
    )


def _publish_pair(output: Path, checksum_output: Path, snapshot_bytes: bytes) -> None:
    requested_parent, directory_fd = _preflight_capture_outputs(output, checksum_output)
    try:
        _publish_pair_at(
            directory_fd,
            snapshot_bytes,
            requested_parent=requested_parent,
        )
    finally:
        os.close(directory_fd)


def _artifact_paths(snapshot: Path, schema: Path, checksum: Path) -> None:
    if snapshot.name != SNAPSHOT_LEAF or checksum.name != CHECKSUM_LEAF:
        _fail(
            "ARTIFACT_NAME_INVALID",
            "snapshot/checksum leaf names differ from the v1 contract",
        )
    if schema.name != "metriplane.baseline-snapshot.v1.schema.json":
        _fail("ARTIFACT_NAME_INVALID", "schema leaf name differs from the v1 contract")


_SUPPORTED_SCHEMA_KEYWORDS = {
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "allOf",
    "const",
    "description",
    "enum",
    "else",
    "format",
    "if",
    "items",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "oneOf",
    "pattern",
    "prefixItems",
    "properties",
    "propertyNames",
    "required",
    "then",
    "title",
    "type",
    "uniqueItems",
}

_SUPPORTED_JSON_TYPES = {
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "array",
    "object",
}


def _check_schema_definition(schema: Any, root: dict[str, Any], path: str = "$schema") -> None:
    """Preflight every node in the hash-locked supported Draft 2020-12 subset."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise _SchemaViolation(path, "schema node is neither an object nor boolean")
    unknown = set(schema) - _SUPPORTED_SCHEMA_KEYWORDS
    if unknown:
        raise _SchemaViolation(path, f"unsupported schema keyword(s): {sorted(unknown)!r}")

    for keyword in ("$schema", "$id", "$ref", "title", "description", "pattern", "format"):
        if keyword in schema and not isinstance(schema[keyword], str):
            raise _SchemaViolation(path, f"{keyword} must be a string")
    if "$ref" in schema:
        _resolve_local_ref(root, schema["$ref"])
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise _SchemaViolation(path, f"pattern is invalid: {exc}") from exc
    if schema.get("format") not in (None, "uri", "date-time"):
        raise _SchemaViolation(path, f"unsupported string format: {schema['format']}")

    definitions = schema.get("$defs", {})
    properties = schema.get("properties", {})
    for keyword, values in (("$defs", definitions), ("properties", properties)):
        if not isinstance(values, dict):
            raise _SchemaViolation(path, f"{keyword} must be an object")
        for name, child in values.items():
            _check_schema_definition(child, root, f"{path}/{keyword}/{name}")

    for keyword in ("allOf", "oneOf", "prefixItems"):
        if keyword not in schema:
            continue
        values = schema[keyword]
        if not isinstance(values, list) or not values:
            raise _SchemaViolation(path, f"{keyword} must be a nonempty array")
        for index, child in enumerate(values):
            _check_schema_definition(child, root, f"{path}/{keyword}/{index}")

    for keyword in ("additionalProperties", "items", "propertyNames", "if", "then", "else"):
        if keyword in schema:
            _check_schema_definition(schema[keyword], root, f"{path}/{keyword}")

    if "type" in schema:
        declared = schema["type"]
        types = [declared] if isinstance(declared, str) else declared
        if (
            not isinstance(types, list)
            or not types
            or any(not isinstance(item, str) or item not in _SUPPORTED_JSON_TYPES for item in types)
            or len(types) != len(set(types))
        ):
            raise _SchemaViolation(path, "type must contain unique supported JSON types")

    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or len(required) != len(set(required))
    ):
        raise _SchemaViolation(path, "required must contain unique strings")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            raise _SchemaViolation(path, "enum must be a nonempty array")
        identities = [_canonical_bytes(item) for item in values]
        if len(identities) != len(set(identities)):
            raise _SchemaViolation(path, "enum values must be unique")

    for keyword in (
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minProperties",
    ):
        if keyword in schema and (
            not isinstance(schema[keyword], int)
            or isinstance(schema[keyword], bool)
            or schema[keyword] < 0
        ):
            raise _SchemaViolation(path, f"{keyword} must be a nonnegative integer")
    for keyword in ("minimum", "maximum"):
        if keyword in schema and (
            not isinstance(schema[keyword], (int, float)) or isinstance(schema[keyword], bool)
        ):
            raise _SchemaViolation(path, f"{keyword} must be a number")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise _SchemaViolation(path, "uniqueItems must be a boolean")


def _schema_equal(left: Any, right: Any) -> bool:
    try:
        return _canonical_bytes(left) == _canonical_bytes(right)
    except SnapshotError:
        return False


def _resolve_local_ref(root: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise _SchemaViolation("$", f"unsupported non-local schema reference: {reference}")
    value: Any = root
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise _SchemaViolation("$", f"unresolved local schema reference: {reference}")
        value = value[token]
    return value


def _json_type_matches(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "object":
        return isinstance(instance, dict)
    raise _SchemaViolation("$", f"unsupported JSON Schema type: {expected}")


def _uri_format_valid(value: str) -> bool:
    if any(char.isspace() or ord(char) < 0x20 for char in value):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parsed.scheme):
        return False
    return parsed.scheme not in {"http", "https"} or bool(parsed.netloc)


def _date_time_format_valid(value: str) -> bool:
    if (
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
            r"(?:Z|[+-]\d{2}:\d{2})",
            value,
        )
        is None
    ):
        return False
    try:
        datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    except ValueError:
        return False
    return True


def _schema_pattern_matches(pattern: str, value: str) -> bool:
    """Apply JSON Schema search semantics without Python's terminal-LF `$` exception."""
    if pattern.startswith("^") and pattern.endswith("$"):
        return re.fullmatch(pattern, value) is not None
    return re.search(pattern, value) is not None


def _validate_schema_node(instance: Any, schema: Any, root: dict[str, Any], path: str) -> None:
    if isinstance(schema, bool):
        if not schema:
            raise _SchemaViolation(path, "boolean false schema rejects the instance")
        return
    if not isinstance(schema, dict):
        raise _SchemaViolation(path, "schema node is neither an object nor boolean")
    unknown = set(schema) - _SUPPORTED_SCHEMA_KEYWORDS
    if unknown:
        raise _SchemaViolation(path, f"unsupported schema keyword(s): {sorted(unknown)!r}")

    reference = schema.get("$ref")
    if reference is not None:
        if not isinstance(reference, str):
            raise _SchemaViolation(path, "$ref must be a string")
        _validate_schema_node(instance, _resolve_local_ref(root, reference), root, path)

    all_of = schema.get("allOf")
    if all_of is not None:
        if not isinstance(all_of, list):
            raise _SchemaViolation(path, "allOf must be an array")
        for branch in all_of:
            _validate_schema_node(instance, branch, root, path)

    one_of = schema.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list):
            raise _SchemaViolation(path, "oneOf must be an array")
        matches = 0
        for branch in one_of:
            try:
                _validate_schema_node(instance, branch, root, path)
            except _SchemaViolation:
                continue
            matches += 1
        if matches != 1:
            raise _SchemaViolation(path, f"oneOf matched {matches} branches instead of exactly one")

    if "if" in schema:
        try:
            _validate_schema_node(instance, schema["if"], root, path)
        except _SchemaViolation:
            branch = "else"
        else:
            branch = "then"
        if branch in schema:
            _validate_schema_node(instance, schema[branch], root, path)

    expected_type = schema.get("type")
    if expected_type is not None:
        types = [expected_type] if isinstance(expected_type, str) else expected_type
        if (
            not isinstance(types, list)
            or not types
            or any(not isinstance(item, str) for item in types)
        ):
            raise _SchemaViolation(path, "type must be a string or nonempty string array")
        if not any(_json_type_matches(instance, item) for item in types):
            raise _SchemaViolation(path, f"instance does not match JSON type {types!r}")

    if "const" in schema and not _schema_equal(instance, schema["const"]):
        raise _SchemaViolation(path, "instance differs from const")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not any(_schema_equal(instance, item) for item in enum):
            raise _SchemaViolation(path, "instance is not one of the enumerated values")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise _SchemaViolation(path, "required must be an array of strings")
        missing = [item for item in required if item not in instance]
        if missing:
            raise _SchemaViolation(path, f"required properties are missing: {missing!r}")
        minimum_properties = schema.get("minProperties")
        if minimum_properties is not None and len(instance) < minimum_properties:
            raise _SchemaViolation(path, f"object has fewer than {minimum_properties} properties")
        property_names = schema.get("propertyNames")
        if property_names is not None:
            for key in instance:
                _validate_schema_node(key, property_names, root, f"{path}/<property-name>")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise _SchemaViolation(path, "properties must be an object")
        for key, child_schema in properties.items():
            if key in instance:
                _validate_schema_node(instance[key], child_schema, root, f"{path}/{key}")
        extras = [key for key in instance if key not in properties]
        additional = schema.get("additionalProperties", True)
        if additional is False and extras:
            raise _SchemaViolation(path, f"additional properties are prohibited: {extras!r}")
        if isinstance(additional, (dict, bool)):
            if additional is not True:
                for key in extras:
                    _validate_schema_node(instance[key], additional, root, f"{path}/{key}")
        else:
            raise _SchemaViolation(path, "additionalProperties must be a schema or boolean")

    if isinstance(instance, list):
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if minimum_items is not None and len(instance) < minimum_items:
            raise _SchemaViolation(path, f"array has fewer than {minimum_items} items")
        if maximum_items is not None and len(instance) > maximum_items:
            raise _SchemaViolation(path, f"array has more than {maximum_items} items")
        if schema.get("uniqueItems") is True:
            identities = [_canonical_bytes(item) for item in instance]
            if len(identities) != len(set(identities)):
                raise _SchemaViolation(path, "array items are not unique")
        prefixes = schema.get("prefixItems", [])
        if not isinstance(prefixes, list):
            raise _SchemaViolation(path, "prefixItems must be an array")
        for index, child_schema in enumerate(prefixes[: len(instance)]):
            _validate_schema_node(instance[index], child_schema, root, f"{path}/{index}")
        if "items" in schema:
            item_schema = schema["items"]
            for index in range(len(prefixes), len(instance)):
                _validate_schema_node(instance[index], item_schema, root, f"{path}/{index}")

    if isinstance(instance, str):
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if minimum_length is not None and len(instance) < minimum_length:
            raise _SchemaViolation(path, f"string is shorter than {minimum_length} characters")
        if maximum_length is not None and len(instance) > maximum_length:
            raise _SchemaViolation(path, f"string is longer than {maximum_length} characters")
        pattern = schema.get("pattern")
        if pattern is not None and (
            not isinstance(pattern, str) or not _schema_pattern_matches(pattern, instance)
        ):
            raise _SchemaViolation(path, f"string does not match pattern {pattern!r}")
        format_name = schema.get("format")
        if format_name is not None:
            if format_name == "uri":
                valid_format = _uri_format_valid(instance)
            elif format_name == "date-time":
                valid_format = _date_time_format_valid(instance)
            else:
                raise _SchemaViolation(path, f"unsupported string format: {format_name}")
            if not valid_format:
                raise _SchemaViolation(path, f"string is not a valid {format_name}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and instance < minimum:
            raise _SchemaViolation(path, f"number is less than minimum {minimum}")
        if maximum is not None and instance > maximum:
            raise _SchemaViolation(path, f"number is greater than maximum {maximum}")


def _internal_validate(instance: Any, schema: dict[str, Any]) -> None:
    """Validate the hash-locked v1 artifact without an external runtime dependency."""
    try:
        _check_schema_definition(schema, schema)
        _validate_schema_node(instance, schema, schema, "$")
    except _SchemaViolation as exc:
        _fail("SCHEMA_VALIDATION_FAILED", f"{exc.path}: {exc.message}")


def _validate_with_available_engine(instance: Any, schema: dict[str, Any]) -> str:
    _internal_validate(instance, schema)
    try:
        jsonschema_version = importlib.metadata.version("jsonschema")
        rfc3339_version = importlib.metadata.version("rfc3339-validator")
    except importlib.metadata.PackageNotFoundError:
        jsonschema_version = None
        rfc3339_version = None
    if jsonschema_version == "4.25.1" and rfc3339_version == "0.1.4":
        try:
            jsonschema = importlib.import_module("jsonschema")
            validator_class = jsonschema.Draft202012Validator
            format_checker = jsonschema.FormatChecker()
            schema_error = jsonschema.exceptions.SchemaError
            validation_error = jsonschema.exceptions.ValidationError
        except (ImportError, AttributeError):
            pass
        else:
            if "date-time" in format_checker.checkers:
                try:
                    validator_class.check_schema(schema)
                    validator_class(schema, format_checker=format_checker).validate(instance)
                except (schema_error, validation_error) as exc:
                    _fail(
                        "SCHEMA_VALIDATION_FAILED",
                        f"Draft 2020-12 schema validation failed: {exc}",
                    )
                return "jsonschema-4.25.1"
    return "internal-exact-schema-v1"


def _snapshot_invariant(condition: bool, message: str) -> None:
    if not condition:
        _fail("SNAPSHOT_INVARIANT_FAILED", message)


def _snapshot_rows(
    snapshot: dict[str, Any], section_name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    section = snapshot.get(section_name)
    if not isinstance(section, dict):
        _fail("SNAPSHOT_INVARIANT_FAILED", f"{section_name} must be an object")
    rows = section.get("entries")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        _fail(
            "SNAPSHOT_INVARIANT_FAILED",
            f"{section_name}.entries must contain objects",
        )
    return section, cast(list[dict[str, Any]], rows)


def _validate_snapshot_invariants(snapshot: dict[str, Any]) -> None:
    """Enforce semantic relations that JSON Schema cannot express."""
    expected_root = {
        "schema_version",
        "captured_source",
        "tracked_tree",
        "commands_and_help",
        "http_routes",
        "schemas",
        "resources",
        "workflows_and_jobs",
        "tests",
        "environment",
        "limitations",
    }
    _snapshot_invariant(set(snapshot) == expected_root, "snapshot root fields differ from v1")

    tracked, tracked_rows = _snapshot_rows(snapshot, "tracked_tree")
    tracked_paths = [cast(str, row["path"]) for row in tracked_rows]
    for path in tracked_paths:
        _require_safe_relative_posix(path, code="SNAPSHOT_INVARIANT_FAILED", label="tracked path")
    _snapshot_invariant(
        tracked_paths == sorted(tracked_paths, key=lambda value: value.encode("utf-8"))
        and len(tracked_paths) == len(set(tracked_paths)),
        "tracked entries are not in unique UTF-8 path order",
    )
    mode_counts = {
        mode: sum(row.get("mode") == mode for row in tracked_rows) for mode in EXPECTED_MODE_COUNTS
    }
    _snapshot_invariant(
        tracked.get("entry_count") == len(tracked_rows) == EXPECTED_TRACKED_COUNT
        and tracked.get("mode_counts") == mode_counts == EXPECTED_MODE_COUNTS
        and tracked.get("canonical_entries_sha256")
        == _sha(_canonical_bytes(tracked_rows))
        == EXPECTED_TRACKED_ROWS_SHA256,
        "tracked entry count, modes, or canonical digest is stale",
    )

    routes, route_rows = _snapshot_rows(snapshot, "http_routes")
    for row in route_rows:
        _require_safe_relative_posix(
            row.get("source_path"),
            code="SNAPSHOT_INVARIANT_FAILED",
            label="route source path",
        )
        forwarded = row.get("forwarded_by")
        if isinstance(forwarded, dict):
            _require_safe_relative_posix(
                forwarded.get("source_path"),
                code="SNAPSHOT_INVARIANT_FAILED",
                label="forwarding source path",
            )
    route_order = sorted(
        route_rows,
        key=lambda row: (
            row["protocol"].encode("utf-8"),
            row["normalized_path"].encode("utf-8"),
            row["method"].encode("utf-8"),
            row["source_path"].encode("utf-8"),
            row["line"],
            row["declaration_kind"].encode("utf-8"),
        ),
    )
    _snapshot_invariant(
        route_rows == route_order
        and len({_canonical_bytes(row) for row in route_rows}) == len(route_rows)
        and routes.get("count") == len(route_rows) == EXPECTED_ROUTE_COUNT
        and routes.get("canonical_rows_sha256")
        == _sha(_canonical_bytes(route_rows))
        == EXPECTED_ROUTE_ROWS_SHA256,
        "HTTP route order, count, uniqueness, or canonical digest is stale",
    )

    schemas, schema_rows = _snapshot_rows(snapshot, "schemas")
    schema_paths = [cast(str, row["path"]) for row in schema_rows]
    for path in schema_paths:
        _require_safe_relative_posix(path, code="SNAPSHOT_INVARIANT_FAILED", label="schema path")
    _snapshot_invariant(
        schema_paths == sorted(schema_paths, key=lambda value: value.encode("utf-8"))
        and len(schema_paths) == len(set(schema_paths))
        and schemas.get("count") == len(schema_rows) == EXPECTED_SCHEMA_COUNT
        and schemas.get("canonical_rows_sha256")
        == _sha(_canonical_bytes(schema_rows))
        == EXPECTED_SCHEMA_ROWS_SHA256,
        "schema order, count, uniqueness, or canonical digest is stale",
    )

    resources, resource_rows = _snapshot_rows(snapshot, "resources")
    resource_paths = [cast(str, row["path"]) for row in resource_rows]
    for row in resource_rows:
        _require_safe_relative_posix(
            row.get("path"),
            code="SNAPSHOT_INVARIANT_FAILED",
            label="resource path",
        )
        for declaration in row.get("package_data_declarations", []):
            _require_safe_relative_posix(
                declaration.get("pattern") if isinstance(declaration, dict) else None,
                code="SNAPSHOT_INVARIANT_FAILED",
                label="package-data pattern",
            )
    repository_paths = [
        row["path"]
        for row in resource_rows
        if any(kind in row["kinds"] for kind in ("config", "example", "proof"))
    ]
    package_paths = [row["path"] for row in resource_rows if "package_data" in row["kinds"]]
    kind_order = ("package_data", "config", "example", "proof")
    canonical_kinds = all(
        row["kinds"] == [kind for kind in kind_order if kind in row["kinds"]]
        for row in resource_rows
    )
    _snapshot_invariant(
        resource_paths == sorted(resource_paths, key=lambda value: value.encode("utf-8"))
        and len(resource_paths) == len(set(resource_paths))
        and canonical_kinds
        and resources.get("count")
        == len(resource_rows)
        == EXPECTED_RESOURCE_COUNTS["merged_unique_rows"]
        and resources.get("canonical_rows_sha256")
        == _sha(_canonical_bytes(resource_rows))
        == EXPECTED_RESOURCE_ROWS_SHA256
        and resources.get("canonical_path_array_sha256")
        == _path_array_digest(resource_paths)
        == EXPECTED_RESOURCE_PATH_DIGESTS["merged_unique_rows"]
        and resources.get("repository_seed_path_array_sha256")
        == _path_array_digest(repository_paths)
        == EXPECTED_RESOURCE_PATH_DIGESTS["repository_seed"]
        and resources.get("package_data_path_array_sha256")
        == _path_array_digest(package_paths)
        == EXPECTED_RESOURCE_PATH_DIGESTS["setuptools_package_data"],
        "resource order, classification, count, or canonical digest is stale",
    )

    workflows, workflow_rows = _snapshot_rows(snapshot, "workflows_and_jobs")
    workflow_paths = [cast(str, row["path"]) for row in workflow_rows]
    for path in workflow_paths:
        _require_safe_relative_posix(path, code="SNAPSHOT_INVARIANT_FAILED", label="workflow path")
    _snapshot_invariant(
        workflow_paths == sorted(workflow_paths, key=lambda value: value.encode("utf-8"))
        and len(workflow_paths) == len(set(workflow_paths))
        and workflows.get("count") == len(workflow_rows) == EXPECTED_WORKFLOW_COUNT
        and workflows.get("canonical_rows_sha256")
        == _sha(_canonical_bytes(workflow_rows))
        == EXPECTED_WORKFLOW_ROWS_SHA256,
        "workflow order, count, uniqueness, or canonical digest is stale",
    )

    _, help_rows = _snapshot_rows(snapshot, "commands_and_help")
    _snapshot_invariant(
        [row.get("command") for row in help_rows] == list(EXPECTED_HELP_IDENTITIES),
        "installed help command order differs",
    )
    for row in help_rows:
        command = row["command"]
        entry_point, size, digest = EXPECTED_HELP_IDENTITIES[command]
        stdout = row["stdout"].encode("utf-8")
        stderr = row["stderr"].encode("utf-8")
        _snapshot_invariant(
            row["entry_point"] == entry_point
            and row["version"] == AUDITED_VERSION
            and row["argv"] == [command, "--help"]
            and row["exit_code"] == 0
            and len(stdout) == size
            and row["stdout_sha256"] == _sha(stdout) == digest
            and stderr == b""
            and row["stderr_sha256"] == _sha(stderr) == EMPTY_SHA256,
            f"installed {command} help identity or stream digest differs",
        )

    tests = snapshot.get("tests")
    if not isinstance(tests, dict):
        _fail("SNAPSHOT_INVARIANT_FAILED", "tests must be an object")
    collection = tests.get("collection")
    execution = tests.get("execution")
    if not isinstance(collection, dict) or not isinstance(execution, dict):
        _fail(
            "SNAPSHOT_INVARIANT_FAILED",
            "test collection/execution projections are missing",
        )
    node_ids = collection.get("node_ids")
    failure_ids = execution.get("failure_node_ids")
    if not isinstance(node_ids, list) or not all(isinstance(node, str) for node in node_ids):
        _fail("SNAPSHOT_INVARIANT_FAILED", "test node identities are invalid")
    node_id_list = cast(list[str], node_ids)
    _snapshot_invariant(
        _sha(_canonical_bytes(node_id_list)) == EXPECTED_TEST_NODE_IDS_SHA256
        and len(node_id_list) == len(set(node_id_list)) == EXPECTED_TEST_COUNT,
        "test node identities or exact collection order differ",
    )
    if not isinstance(failure_ids, list) or not all(isinstance(node, str) for node in failure_ids):
        _fail("SNAPSHOT_INVARIANT_FAILED", "test failure node identities are invalid")
    failure_id_list = cast(list[str], failure_ids)
    _snapshot_invariant(
        failure_id_list == sorted(set(failure_id_list), key=lambda value: value.encode("utf-8"))
        and all(node in set(node_id_list) for node in failure_id_list),
        "test failure node identities are invalid",
    )
    expected_execution = {
        "exit_code": 0,
        "collected_count": EXPECTED_TEST_COUNT,
        "passed_count": 1192,
        "failed_count": 0,
        "error_count": 0,
        "skipped_count": 2,
        "xfailed_count": 0,
        "xpassed_count": 0,
        "warning_count": 0,
        "deselected_count": 0,
        "retry_count": 0,
        "failure_node_ids": [],
    }
    _snapshot_invariant(
        collection.get("exit_code") == 0
        and collection.get("count") == len(node_id_list) == EXPECTED_TEST_COUNT
        and collection.get("warning_count") == 0
        and collection.get("stderr_sha256") == EMPTY_SHA256
        and set(execution) == set(expected_execution) | {"stdout_sha256", "stderr_sha256"}
        and all(execution.get(key) == value for key, value in expected_execution.items())
        and execution.get("stderr_sha256") == EMPTY_SHA256
        and sum(
            execution[key]
            for key in (
                "passed_count",
                "failed_count",
                "error_count",
                "skipped_count",
                "xfailed_count",
                "xpassed_count",
                "deselected_count",
            )
        )
        == execution["collected_count"],
        "test counts, outcomes, exits, warnings, or stream relations differ",
    )

    environment = snapshot.get("environment")
    if not isinstance(environment, dict):
        _fail("SNAPSHOT_INVARIANT_FAILED", "environment must be an object")
    filesystem = environment.get("filesystem")
    if not isinstance(filesystem, dict) or not isinstance(filesystem.get("home_cache"), dict):
        _fail(
            "SNAPSHOT_INVARIANT_FAILED",
            "filesystem home/cache projection is missing",
        )
    _snapshot_invariant(
        filesystem.get("sha256") == f"sha256:{_sha(_canonical_bytes(filesystem['home_cache']))}",
        "filesystem home/cache digest relation differs",
    )
    home_cache = filesystem["home_cache"]
    paths = home_cache.get("paths")
    allowlisted_environment = home_cache.get("allowlisted_environment")
    if not isinstance(allowlisted_environment, dict):
        _fail(
            "SNAPSHOT_INVARIANT_FAILED",
            "filesystem allowlisted environment is missing",
        )
    for variable, path in allowlisted_environment.items():
        _require_normalized_absolute_posix(
            path,
            code="SNAPSHOT_INVARIANT_FAILED",
            label=f"environment path {variable}",
        )
    expected_path_kinds = [
        "repository_root",
        "home",
        "uv_cache_dir",
        "uv_project_environment",
        "temporary_root",
    ]
    installed = environment.get("installed_distributions")
    installed_normalized_names = (
        [row.get("normalized_name") for row in cast(list[dict[str, Any]], installed)]
        if isinstance(installed, list) and all(isinstance(row, dict) for row in installed)
        else []
    )
    if isinstance(paths, list):
        for row in paths:
            if isinstance(row, dict):
                _require_normalized_absolute_posix(
                    row.get("path"),
                    code="SNAPSHOT_INVARIANT_FAILED",
                    label="filesystem observation path",
                )
    _snapshot_invariant(
        isinstance(paths, list)
        and all(isinstance(row, dict) for row in paths)
        and [row.get("kind") for row in cast(list[dict[str, Any]], paths)] == expected_path_kinds
        and isinstance(installed, list)
        and all(isinstance(row, dict) for row in installed)
        and installed_normalized_names
        == sorted(
            (
                cast(str, row.get("normalized_name"))
                for row in cast(list[dict[str, Any]], installed)
            ),
            key=lambda value: value.encode("utf-8"),
        )
        and len(installed_normalized_names) == len(set(installed_normalized_names)),
        "environment path or installed-distribution ordering differs",
    )

    _snapshot_invariant(
        snapshot.get("limitations") == _limitations(),
        "limitation authority order or content differs",
    )


def _load_locked_schema(schema: Path) -> dict[str, Any]:
    schema_raw = _read_regular(schema, MAX_SCHEMA_BYTES)
    if len(schema_raw) != EXPECTED_SCHEMA_BYTES or _sha(schema_raw) != EXPECTED_SCHEMA_SHA256:
        _fail(
            "SCHEMA_IDENTITY_MISMATCH",
            "schema bytes differ from the reviewed v1 schema",
        )
    schema_value = _strict_json(schema_raw, require_canonical=True)
    if not isinstance(schema_value, dict):
        _fail("SCHEMA_INVALID", "schema root must be a JSON object")
    if schema_value.get("$schema") != SCHEMA_DRAFT_URI or schema_value.get("$id") != SCHEMA_ID:
        _fail(
            "SCHEMA_IDENTITY_MISMATCH",
            "schema draft or $id differs from the reviewed v1 schema",
        )
    return schema_value


def _validate_snapshot_value(snapshot_value: dict[str, Any], schema_value: dict[str, Any]) -> None:
    _validate_with_available_engine(snapshot_value, schema_value)
    if snapshot_value.get("schema_version") != SCHEMA_VERSION:
        _fail("SNAPSHOT_VERSION_MISMATCH", "snapshot schema_version differs from v1")
    _validate_snapshot_invariants(snapshot_value)


def _validate_artifact(snapshot: Path, schema: Path, checksum: Path) -> tuple[dict[str, Any], str]:
    _artifact_paths(snapshot, schema, checksum)
    checksum_raw = _read_regular(checksum, 92, exact_size=92)
    snapshot_raw = _read_regular(snapshot, MAX_SNAPSHOT_BYTES)
    snapshot_digest = _sha(snapshot_raw)
    expected_sidecar = f"{snapshot_digest}  {SNAPSHOT_LEAF}\n".encode("ascii")
    if checksum_raw != expected_sidecar:
        _fail(
            "CHECKSUM_MISMATCH",
            "checksum grammar, filename, case, or snapshot digest differs",
        )
    snapshot_value = _strict_json(snapshot_raw, require_canonical=True)
    if not isinstance(snapshot_value, dict):
        _fail("SNAPSHOT_INVALID", "snapshot root must be a JSON object")
    schema_value = _load_locked_schema(schema)
    _validate_snapshot_value(snapshot_value, schema_value)
    return snapshot_value, snapshot_digest


def _evidence_base_present(repo: Path) -> bool:
    _, directory_fd = _open_directory_nofollow(
        repo, code="EVIDENCE_ROOT_INVALID", label="repository root"
    )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        components = ("build", "work-orders", TASK_ID, AUDITED_BASE_SHA)
        for index, component in enumerate(components):
            try:
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if index <= 2:
                    return False
                _fail(
                    "EVIDENCE_ROOT_INVALID",
                    "work-order evidence namespace is partially materialized: "
                    + "/".join(components[: index + 1]),
                )
            except OSError as exc:
                _fail(
                    "EVIDENCE_ROOT_INVALID",
                    f"work-order evidence root cannot be inspected without following links: {exc}",
                )
            try:
                info = os.fstat(child_fd)
                if not stat.S_ISDIR(info.st_mode):
                    _fail(
                        "EVIDENCE_ROOT_INVALID",
                        f"work-order evidence component is not a directory: {component}",
                    )
            except Exception:
                os.close(child_fd)
                raise
            os.close(directory_fd)
            directory_fd = child_fd
        return True
    finally:
        os.close(directory_fd)


def _check_snapshot(repo: Path, snapshot: dict[str, Any], digest: str) -> None:
    source = snapshot.get("captured_source")
    if not isinstance(source, dict) or source.get("commit") != AUDITED_BASE_SHA:
        _fail(
            "SOURCE_IDENTITY_MISMATCH",
            "snapshot does not bind the audited source commit",
        )
    objects = GitObjects(repo, AUDITED_BASE_SHA)
    expected = {
        "captured_source": _source_identity(objects),
        "tracked_tree": _tracked_tree(objects),
        "http_routes": _http_routes(objects),
        "schemas": _schemas(objects),
        "resources": _resources(objects),
        "workflows_and_jobs": _workflows(objects),
        "limitations": _limitations(),
    }
    for section, expected_value in expected.items():
        if snapshot.get(section) != expected_value:
            _fail(
                "SOURCE_RECENSUS_MISMATCH",
                f"snapshot {section} differs from exact-base recensus",
            )
    if _evidence_base_present(repo):
        _, _, environment_observation, tests = _instance_core(repo, AUDITED_BASE_SHA)
        if snapshot.get("tests") != tests or snapshot.get("environment") != _environment_projection(
            environment_observation
        ):
            _fail(
                "RETAINED_EVIDENCE_MISMATCH",
                "snapshot tests or environment differ from retained READY evidence",
            )
    elif digest != EXPECTED_COMMITTED_SNAPSHOT_SHA256:
        _fail(
            "COMMITTED_SNAPSHOT_IDENTITY_MISMATCH",
            "evidence-absent check requires the reviewed committed snapshot digest",
        )


def _success(command: str, digest: str, *, base_sha: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "command": command,
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "snapshot_sha256": digest,
    }
    if base_sha is not None:
        result["base_sha"] = base_sha
    return result


def _write_json_stream(stream: Any, value: Any) -> None:
    stream.buffer.write(_canonical_bytes(value))
    stream.buffer.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="baseline_snapshot.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture", help="capture the audited exact-base snapshot")
    capture.add_argument("--repo", required=True, type=Path)
    capture.add_argument("--base-sha", required=True)
    capture.add_argument("--output", required=True, type=Path)
    capture.add_argument("--checksum-output", required=True, type=Path)
    validate = subparsers.add_parser("validate", help="validate a snapshot, schema, and checksum")
    validate.add_argument("--snapshot", required=True, type=Path)
    validate.add_argument("--schema", required=True, type=Path)
    validate.add_argument("--checksum", required=True, type=Path)
    check = subparsers.add_parser("check", help="validate and recensus source-derived sections")
    check.add_argument("--repo", required=True, type=Path)
    check.add_argument("--snapshot", required=True, type=Path)
    check.add_argument("--schema", required=True, type=Path)
    check.add_argument("--checksum", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "capture":
            requested_parent, directory_fd = _preflight_capture_outputs(
                args.output, args.checksum_output
            )
            try:
                value = _build_snapshot(args.repo, args.base_sha)
                schema_path = args.repo / "schemas" / "metriplane.baseline-snapshot.v1.schema.json"
                schema_value = _load_locked_schema(schema_path)
                _validate_snapshot_value(value, schema_value)
                snapshot_bytes = _canonical_bytes(value)
                if len(snapshot_bytes) > MAX_SNAPSHOT_BYTES:
                    _fail(
                        "SIZE_LIMIT",
                        "captured snapshot exceeds the declared snapshot byte limit",
                    )
                _publish_pair_at(
                    directory_fd,
                    snapshot_bytes,
                    requested_parent=requested_parent,
                )
            finally:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass
            return 0
        snapshot, digest = _validate_artifact(args.snapshot, args.schema, args.checksum)
        if args.command == "validate":
            _write_json_stream(sys.stdout, _success("validate", digest))
            return 0
        if args.command == "check":
            _check_snapshot(args.repo, snapshot, digest)
            _write_json_stream(sys.stdout, _success("check", digest, base_sha=AUDITED_BASE_SHA))
            return 0
        _fail("UNKNOWN_COMMAND", "unknown command")
    except SnapshotError as exc:
        _write_json_stream(
            sys.stderr,
            {"error": {"code": exc.code, "message": exc.message}, "ok": False},
        )
        return 3
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 - unexpected failures must use the fail-closed exit.
        _write_json_stream(
            sys.stderr,
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                },
                "ok": False,
            },
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
