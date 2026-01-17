"""
longevity.py

Gompertz–Makeham-based longevity model for ROOST / OWL.

This module provides a conservative, actuarially interpretable longevity
model suitable for retirement planning and Monte Carlo simulation.

Features:
- Three-tier health adjustments ("excellent", "average", "poor")
- Sex-based mortality differences
- Age-dependent smoker mortality multiplier
- Marriage longevity bonus
- Individual lifetime sampling
- Joint (last-survivor) lifetime sampling
- Integer-age stochastic sampling aligned with annual planning timelines

Design goals:
- Preserve actuarial intuition (Gompertz–Makeham hazard structure)
- Produce realistic but conservative longevity outcomes
- Avoid extreme upper-tail dominance (ages 110–120)
- Ensure relative longevity differences persist at advanced ages
- Maintain stability across Monte Carlo runs

Modeling notes:
- Baseline mortality follows a Gompertz–Makeham form calibrated to
  approximate SSA population mortality for ages 55+
- Health, sex, smoking, and marriage primarily scale baseline mortality
  (A, B)
- Health also applies a small adjustment to mortality acceleration (C)
  so that health advantages are not erased at older ages
- This is not a strict SSA or ALI table reproduction, but a smooth,
  planning-oriented hybrid model
"""

from __future__ import annotations

import numpy as np

# ============================================================
# Base Gompertz–Makeham Parameters (SSA-like population)
# ============================================================

# Calibrated to approximate SSA 2019 population mortality for ages 55+
# Used as a baseline before applying individual adjustments
A_BASE = 0.0009  # Makeham (background) mortality
B_BASE = 0.000010  # Gompertz level parameter
C_BASE = 0.110  # Gompertz acceleration (intentionally tightened to limit tail)


# ============================================================
# Health multipliers (conservative preferred-risk style)
# ============================================================

# Notes:
# - These primarily scale baseline mortality (A, B)
# - A small additional adjustment to mortality acceleration (C)
#   is applied separately to preserve health differences at older ages
#
# Reference ranges:
#   ALI / preferred-risk models often imply stronger effects
#   (excellent ≈ 0.75, poor ≈ 1.40–1.50). These values are intentionally
#   more conservative to avoid extreme longevity shifts.

HEALTH_MULTIPLIERS = {
    "excellent": 0.85,
    "average": 1.00,
    "poor": 1.15,
}

# ============================================================
# Health adjustment to mortality acceleration (C)
# ============================================================

# Rationale:
# In a Gompertz model, differences in baseline mortality (A, B)
# diminish at advanced ages unless mortality acceleration also differs.
# A small, damped adjustment to C ensures that health advantages persist
# into late life without reintroducing extreme upper-tail outcomes.
#
# These adjustments are intentionally modest (±4–5%) but have
# meaningful effects on expected longevity at age 60+.

C_HEALTH_ADJUSTMENT = {
    "excellent": 0.96,  # slower mortality acceleration
    "average": 1.00,
    "poor": 1.05,  # faster mortality acceleration
}


# ============================================================
# Sex multipliers
# ============================================================

# Notes:
# - Females receive a modest mortality reduction consistent with
#   observed SSA population differences at adult ages
# - Males receive a symmetric increase
# - Effects are intentionally weaker than full qₓ table substitution

SEX_MULTIPLIER = {
    "female": 0.92,
    "male": 1.08,
}


# ============================================================
# Marriage bonus
# ============================================================

# Married individuals exhibit modestly lower mortality on average.
# This is modeled as a small multiplicative reduction in baseline hazard.
# Joint-survivor effects emerge naturally from independent sampling.

MARRIAGE_MULTIPLIER = 0.97  # ~3% mortality reduction


# ============================================================
# Age-dependent smoker multiplier
# ============================================================

# Shape reflects ALI / SOA guidance:
# - strong excess mortality at ages 40–65
# - tapering effect at older ages
# - small residual effect at very advanced ages
#
# Maximum effects are intentionally capped to remain conservative.


def age_dependent_smoker_multiplier(age: float) -> float:
    """
    Actuarially reasonable smoker mortality multiplier.

    Characteristics:
    - Large excess mortality at middle ages
    - Declining effect at advanced ages
    - Mild residual penalty at very old ages
    """
    if age < 40:
        return 2.3  # conservative maximum (ALI up to ~2.33)

    if 40 <= age <= 80:
        # Declines linearly from ~2.2 at age 40 to ~1.3 by age 80
        k_mid = 2.2
        excess = k_mid - 1.0
        factor = (80 - age) / 40.0
        return 1.0 + excess * factor

    if 80 < age <= 90:
        return 1.3

    return 1.1  # small residual effect at very old ages


# ============================================================
# Survival function and sampling
# ============================================================


def survival_function(age: np.ndarray, A: float, B: float, C: float) -> np.ndarray:
    """
    Gompertz–Makeham survival function S(x).

    S(x) = exp( -A·x - (B/C)·(exp(C·x) − 1) )
    """
    return np.exp(-A * age - (B / C) * (np.exp(C * age) - 1))


def gm_sample_lifetime(
    rng: np.random.Generator,
    current_age: float,
    A: float,
    B: float,
    C: float,
    max_age: int = 120,
) -> float:
    """
    Draw a stochastic lifetime from a Gompertz–Makeham distribution,
    conditional on survival to `current_age`.

    Sampling is performed on an integer-age grid, consistent with
    annual retirement planning models.
    """
    ages = np.arange(current_age, max_age + 1, 1.0)

    S = survival_function(ages, A, B, C)
    S0 = survival_function(current_age, A, B, C)
    S_cond = S / S0

    F = 1.0 - S_cond

    u = rng.uniform()
    return float(np.interp(u, F, ages))


# ============================================================
# Parameter adjustment: health + sex + smoker + marriage
# ============================================================


def adjust_parameters(
    health: str,
    age: float,
    sex: str,
    smoker: bool = False,
    married: bool = False,
) -> tuple[float, float, float]:
    """
    Compute mortality-adjusted Gompertz–Makeham parameters (A, B, C).

    - Health, sex, smoking, and marriage primarily affect baseline
      mortality (A, B)
    - Health also applies a small adjustment to mortality acceleration (C)
      so that longevity differences persist at advanced ages
    """

    if health not in HEALTH_MULTIPLIERS:
        raise ValueError(
            f"Invalid health level '{health}'. " f"Valid values: {list(HEALTH_MULTIPLIERS.keys())}"
        )

    if sex not in SEX_MULTIPLIER:
        raise ValueError(f"sex must be 'male' or 'female' (got '{sex}')")

    # Start with health multiplier
    k = HEALTH_MULTIPLIERS[health]

    # Sex-based mortality adjustment
    k *= SEX_MULTIPLIER[sex]

    # Age-dependent smoker multiplier
    if smoker:
        k *= age_dependent_smoker_multiplier(age)

    # Marriage longevity bonus
    if married:
        k *= MARRIAGE_MULTIPLIER

    # Apply adjustments
    A_adj = A_BASE * k
    B_adj = B_BASE * k
    C_adj = C_BASE * C_HEALTH_ADJUSTMENT[health]

    return A_adj, B_adj, C_adj


# ============================================================
# Public sampling APIs
# ============================================================


def sample_individual_lifetime(
    rng: np.random.Generator,
    current_age: float,
    health: str = "average",
    sex: str = "female",
    smoker: bool = False,
    married: bool = False,
) -> float:
    """
    Sample an individual's age at death.
    """
    A, B, C = adjust_parameters(health, current_age, sex, smoker, married)
    return gm_sample_lifetime(rng, current_age, A, B, C)


def sample_joint_last_survivor(
    rng: np.random.Generator,
    age1: float,
    age2: float,
    health1: str = "average",
    health2: str = "average",
    sex1: str = "female",
    sex2: str = "male",
    smoker1: bool = False,
    smoker2: bool = False,
    married: bool = True,
) -> tuple[float, float, float]:
    """
    Sample two independent lifetimes and return:

        (last_survivor_age, life1_age_at_death, life2_age_at_death)
    """
    life1 = sample_individual_lifetime(rng, age1, health1, sex1, smoker1, married)

    life2 = sample_individual_lifetime(rng, age2, health2, sex2, smoker2, married)

    return max(life1, life2), life1, life2
