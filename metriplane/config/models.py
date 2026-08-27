# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# metriplane/config/models.py (or wherever your config schema lives)

from pydantic import BaseModel, Field, AliasChoices


class HealthConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("enabled", "enable"),
    )


class AppConfig(BaseModel):
    # ...
    health: HealthConfig = Field(default_factory=HealthConfig)
