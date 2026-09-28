# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""The two package identities permitted during the v0.5 release cycle.

``metriplane.__version__`` remains a literal because the fail-closed release
source freezer and publication workflow read that exact source value.  This
module gives validators one explicit authority for distinguishing a checkout
or development wheel from the final release identity.
"""

DEVELOPMENT_VERSION = "0.5.0.dev0"
RELEASE_VERSION = "0.5.0"

__all__ = ["DEVELOPMENT_VERSION", "RELEASE_VERSION"]
