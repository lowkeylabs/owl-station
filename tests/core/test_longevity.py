import numpy as np
import pytest

from owlroost.core.longevity import (
    HEALTH_MULTIPLIERS,
    SEX_MULTIPLIER,
    adjust_parameters,
    age_dependent_smoker_multiplier,
    sample_individual_lifetime,
    sample_joint_last_survivor,
)

# ============================================================
# Basic parameter tests
# ============================================================


def test_health_multipliers_exist():
    assert "excellent" in HEALTH_MULTIPLIERS
    assert "average" in HEALTH_MULTIPLIERS
    assert "poor" in HEALTH_MULTIPLIERS


def test_sex_multiplier_valid():
    assert set(SEX_MULTIPLIER.keys()) == {"male", "female"}
    assert SEX_MULTIPLIER["female"] < SEX_MULTIPLIER["male"]


def test_invalid_health_raises():
    with pytest.raises(ValueError):
        adjust_parameters("not-a-level", 65, "male")


def test_invalid_sex_raises():
    with pytest.raises(ValueError):
        adjust_parameters("average", 65, "not-sex")


# ============================================================
# Smoker multiplier shape
# ============================================================


def test_smoker_multiplier_monotonic_decline():
    # Should decline after middle ages
    mid = age_dependent_smoker_multiplier(50)
    older = age_dependent_smoker_multiplier(80)

    assert mid > older


def test_smoker_multiplier_low_at_old_age():
    assert age_dependent_smoker_multiplier(95) < 1.2


def test_smoker_multiplier_high_at_young_age():
    assert age_dependent_smoker_multiplier(30) > 2.0


# ============================================================
# Parameter adjustment sanity checks
# ============================================================


def test_adjust_parameters_effect_direction():
    age = 65

    A_avg, B_avg, C_avg = adjust_parameters("average", age, "male", False, False)
    A_exc, B_exc, C_exc = adjust_parameters("excellent", age, "male", False, False)
    A_poor, B_poor, C_poor = adjust_parameters("poor", age, "male", False, False)

    # excellent health should reduce mortality → A, B smaller than average
    assert A_exc < A_avg
    assert B_exc < B_avg

    # poor health should increase mortality → A, B larger
    assert A_poor > A_avg
    assert B_poor > B_avg


def test_sex_difference_effect():
    age = 65

    A_f, B_f, _ = adjust_parameters("average", age, "female", False, False)
    A_m, B_m, _ = adjust_parameters("average", age, "male", False, False)

    assert A_f < A_m
    assert B_f < B_m


# ============================================================
# Sampling behavior tests
# ============================================================


def test_individual_lifetime_is_greater_than_current_age():
    rng = np.random.default_rng(123)
    age = 60
    life = sample_individual_lifetime(rng, age, "average", "male", False, False)
    assert life >= age


def test_sampling_reproducibility():
    rng1 = np.random.default_rng(999)
    rng2 = np.random.default_rng(999)

    life1 = sample_individual_lifetime(rng1, 60, "average", "female", False, False)
    life2 = sample_individual_lifetime(rng2, 60, "average", "female", False, False)

    assert life1 == life2  # same seed → same result


def test_smoker_lifetime_shorter_than_non_smoker():
    rng = np.random.default_rng(123)

    non_smoker = sample_individual_lifetime(rng, 60, "average", "male", smoker=False, married=False)

    rng = np.random.default_rng(123)

    smoker = sample_individual_lifetime(rng, 60, "average", "male", smoker=True, married=False)

    # smoker should die younger (mean shift)
    assert smoker <= non_smoker


def test_joint_last_survivor():
    rng = np.random.default_rng(123)

    last, life1, life2 = sample_joint_last_survivor(
        rng,
        age1=62,
        age2=60,
        health1="excellent",
        health2="poor",
        sex1="female",
        sex2="male",
        smoker1=False,
        smoker2=True,
        married=True,
    )

    # last should be max of the two lifetimes
    assert last == max(life1, life2)
    assert life1 >= 62
    assert life2 >= 60


# ============================================================
# Basic distribution-level sanity checks
# ============================================================


def xtest_average_lifetime_reasonable_range():
    """
    Check that average longevity for healthy nonsmokers is not pathological.
    This is NOT a strict actuarial test, just a stability check.
    """
    rng = np.random.default_rng(123)
    samples = [
        sample_individual_lifetime(rng, 60, "excellent", "female", False, False)
        for _ in range(10000)
    ]

    mean_age = np.mean(samples)

    # Conservative GM should produce mean around 88–100 for 60yo excellent females
    assert 85 <= mean_age <= 105


def test_excellent_health_advantage():
    rng = np.random.default_rng(123)

    excellent = np.mean(
        [
            sample_individual_lifetime(rng, 60, "excellent", "female", False, False)
            for _ in range(5000)
        ]
    )

    average = np.mean(
        [
            sample_individual_lifetime(rng, 60, "average", "female", False, False)
            for _ in range(5000)
        ]
    )

    assert excellent >= average + 3.0
