# OWL-Station

**OWL-Station** is a research and experimental design framework built on top of [Optimal Wealth Laboratory (OWL)](https://github.com/mdlacasse/Owl).

OWL-Station does **not** replace OWL.  OWL-Station is **not** a retirement planner.

Instead, OWL-Station provides an infrastructure for **designing, executing, and analyzing controlled experiments** that use OWL as the core optimization engine.

## How OWL and OWL-Station Differ

| Tool                                | Purpose                                                                       |
| ----------------------------------- | ----------------------------------------------------------------------------- |
| **OWL (Optimal Wealth Laboratory)** | Optimizes a *single* retirement scenario under a specified set of assumptions |
| **OWL-Station**                     | Designs and executes *experiments* that systematically vary those assumptions |

Put simply:

> **OWL optimizes retirement scenarios.
> OWL-Station studies the sensitivity of those optimizations.**

## What OWL Does

[OWL](https://github.com/mdlacasse/Owl) is a modeling framework for exploring retirement financial decisions under uncertainty.
It uses rigorous mathematical optimization to generate optimal realizations of a financial strategy under a given set of assumptions.

OWL:

* Optimizes a **single plan**
* Uses **linear programming**
* Solves for either:
  * maximum net spending, or
  * maximum after-tax bequest
* Applies detailed constraints involving:
  * taxes
  * Roth conversions
  * Social Security
  * Medicare and IRMAA
* Re-optimizes under each scenario rather than simulating fixed behavior

OWL is a **laboratory instrument**, not a prescriptive planner.

## What OWL-Station Adds

OWL-Station operates *around* OWL.  OWL-Station provides:

* Experiment design
* Scenario orchestration
* Rate-regime management
* Sensitivity analysis
* Stochastic and histochastic studies
* Monte Carlo replication
* Result aggregation and comparison

OWL-Station never performs financial optimization itself. Every calculation is delegated to OWL.

## A Clear Boundary

OWL-Station intentionally excludes:

* retirement planning logic
* financial rules
* tax calculations
* optimization formulations

Those remain **authoritative inside OWL**.

OWL-Station focuses exclusively on:

* *how* assumptions vary
* *which* scenarios are compared
* *how* uncertainty is explored
* *what* can be learned from repeated optimized outcomes

## Why OWL-Station Exists

Financial decisions cannot be planned with certainty because markets are volatile. What *can* be done is to understand *how sensitive optimal decisions are* to changes in assumptions.

OWL already enables this at the single-scenario level.

OWL-Station enables it **systematically**.

Examples:

* Comparing retirement outcomes across historical market regimes
* Testing “near-worst-case” sequences vs average conditions
* Studying stochastic rate distributions with known statistical properties
* Evaluating how optimal Roth conversion strategies change under different assumptions
* Measuring probabilities of success across thousands of optimized futures

## Feedback Loop to OWL

OWL-Station is not a one-way consumer of OWL.

    *Insights gained from experiments conducted in OWL-Station may motivate refinements, extensions, or improvements to the underlying OWL planner.*

This includes:

* improved formulations
* new constraints
* better objective handling
* enhanced rate modeling
* performance optimizations

OWL remains the authoritative solver. OWL-Station serves as a *research proving ground*.

## Relationship to Interactive Tools

* [`owlplanner.streamlit.app`](https://owlplanner.streamlit.app/) provides interactive exploration of individual OWL plans.  The user interface does provide some multiple scenario features.
* **OWL-Station** significantly expenses on the multiple-scenario features and provides reproducible, scriptable, research-oriented experimentation.

These tools are complementary, not competing.

## Typical Workflow

1. Define a baseline retirement plan (OWL input TOML).  Save the TOML file
2. Design an experiment in OWL-Station
3. OWL-Station builds a family of TOML files and executes these OWL runs under controlled variations
4. Results are collected, compared, and analyzed
5. Insights may inform decision-making *or* future OWL development


## Summary

* OWL is the optimizer.
* OWL-Station is the research station built around it.

Together, they form a rigorous framework for understanding retirement decisions under uncertainty.
