"""Hypothesis profiles: `dev` explores, `ci` is derandomized so a red run reproduces."""

import os

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=100)
settings.register_profile(
    "ci", max_examples=300, derandomize=True, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
