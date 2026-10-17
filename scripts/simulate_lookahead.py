"""Look-ahead check on simulated efficient markets (pm/sim.py): slope b of the three measuring rules, true b = 1.

  python scripts/simulate_lookahead.py     # -> results/lookahead_simulation.csv
"""
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pm.config import CFG
from pm.sim import lookahead_slopes

if __name__ == "__main__":
    c = CFG["simulation"]
    fit = lookahead_slopes(c["markets"], c["seed"], c["horizon_days"] * 86400)
    out = pd.DataFrame([{"rule": k, "n": r["n"], "b": r["b"], "se_b": r["se_b"], "a": r["a"], "se_a": r["se_a"],
                         "p_joint": r["p_joint"]} for k, r in fit.items()])
    out.to_csv(os.path.join(ROOT, "results", "lookahead_simulation.csv"), index=False, float_format="%.6g")
    print(out.round(4).to_string(index=False))
