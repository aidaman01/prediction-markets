"""Study parameters from config.toml at the repository root."""
import os
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "config.toml"), "rb") as f:
    CFG = tomllib.load(f)
