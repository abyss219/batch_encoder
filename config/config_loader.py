import os
import yaml
from typing import Optional
from dacite import from_dict, Config as DaciteConfig
from .config_definitions import Config

_config: Config = None  # module-level singleton

def load_config(path: Optional[str] = None) -> Config:
    global _config
    if _config is not None:
        return _config

    # Try default locations if no path provided
    if path is None:
        for candidate in ("config.yaml", "config.yml"):
            if os.path.isfile(candidate):
                path = candidate
                break
        else:
            raise FileNotFoundError(
                "No configuration file found (config.yaml or config.yml)."
            )

    with open(path, "r") as f:
        data = yaml.safe_load(f)

    _config = from_dict(Config, data, config=DaciteConfig(strict=False))
    _config.validate()
    return _config
