import json
from datetime import datetime
from pathlib import Path

import numpy as np


def normalize_timestamp(ts) -> str:
    """
    Return an ISO-8601 timestamp string from either
    a datetime or a string.
    """
    if isinstance(ts, datetime):
        return ts.isoformat()
    if isinstance(ts, str):
        return ts
    raise TypeError(f"Unsupported timestamp type: {type(ts)}")


def metrics_from_plan(plan) -> dict:
    start_year = int(plan.year_n[0])
    final_year = int(plan.year_n[-1])

    # ---- totals: spending ----
    total_net_spending_nominal = float(np.sum(plan.g_n))
    total_net_spending_real = float(np.sum(plan.g_n / plan.gamma_n[:-1]))

    # ---- totals: Roth conversions ----
    total_roth_conversions_nominal = float(np.sum(plan.x_in))
    total_roth_conversions_real = float(np.sum(np.sum(plan.x_in, axis=0) / plan.gamma_n[:-1]))

    # ---- totals: taxes ----
    total_tax_ordinary_nominal = float(np.sum(plan.T_n))
    total_tax_ordinary_real = float(np.sum(plan.T_n / plan.gamma_n[:-1]))

    total_tax_capital_nominal = float(np.sum(plan.U_n))
    total_tax_capital_real = float(np.sum(plan.U_n / plan.gamma_n[:-1]))

    total_tax_niit_nominal = float(np.sum(plan.J_n))
    total_tax_niit_real = float(np.sum(plan.J_n / plan.gamma_n[:-1]))

    # ---- totals: Medicare ----
    total_medicare_premiums_nominal = float(np.sum(plan.m_n + plan.M_n))
    total_medicare_premiums_real = float(np.sum((plan.m_n + plan.M_n) / plan.gamma_n[:-1]))

    # ---- totals: estate ----
    estate = np.sum(plan.b_ijn[:, :, plan.N_n], axis=0)
    estate[1] *= 1 - plan.nu

    total_final_bequest_nominal = float(
        np.sum(estate) - plan.remaining_debt_balance + plan.fixed_assets_bequest_value
    )

    total_final_bequest_real = float(total_final_bequest_nominal / plan.gamma_n[-1])

    net_spending_for_plan_year_0 = plan.g_n[0]

    return {
        # metadata
        "schema": "owl.metrics.v1",
        "plan_name": plan._name,
        "run_timestamp": normalize_timestamp(plan._timestamp),
        "plan_start_date": str(plan.startDate),
        # horizon
        "year_start": start_year,
        "year_final_bequest": final_year,
        # model size
        "num_decision_variables": int(plan.A.nvars),
        "num_constraints": int(plan.A.ncons),
        # inflation
        "final_inflation_factor": float(plan.gamma_n[-1]),
        # totals — spending
        "total_net_spending_real": total_net_spending_real,
        "total_net_spending_nominal": total_net_spending_nominal,
        # totals — Roth
        "total_roth_conversions_real": total_roth_conversions_real,
        "total_roth_conversions_nominal": total_roth_conversions_nominal,
        # totals — taxes
        "total_tax_ordinary_real": total_tax_ordinary_real,
        "total_tax_ordinary_nominal": total_tax_ordinary_nominal,
        "total_tax_capital_real": total_tax_capital_real,
        "total_tax_capital_nominal": total_tax_capital_nominal,
        "total_tax_niit_real": total_tax_niit_real,
        "total_tax_niit_nominal": total_tax_niit_nominal,
        # totals — Medicare
        "total_medicare_premiums_real": total_medicare_premiums_real,
        "total_medicare_premiums_nominal": total_medicare_premiums_nominal,
        # totals — estate
        "total_final_bequest_real": total_final_bequest_real,
        "total_final_bequest_nominal": total_final_bequest_nominal,
        # net spending
        "net_spending_for_plan_year_0": net_spending_for_plan_year_0,
    }


def write_metrics_json(plan, metrics_path: Path) -> Path:
    metrics = metrics_from_plan(plan)

    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, sort_keys=True)

    return metrics_path
