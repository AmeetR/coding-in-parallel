"""Configuration loading helpers for coding-in-parallel."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml


def _filter_kwargs(data: Dict[str, Any], *, allowed: set[str]) -> Dict[str, Any]:
    return {key: value for key, value in data.items() if key in allowed}


@dataclass(frozen=True)
class ModelConfig:
    provider: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class SearchConfig:
    max_steps: int = 4
    diffs_per_step: int = 3
    finalists: int = 2
    retries_per_step: int = 1
    investigations_enabled: bool = False
    use_landmarks: bool = False


@dataclass(frozen=True)
class LimitsConfig:
    max_loc_changes: int = 12
    max_files_per_diff: int = 2
    slice_padding_lines: int = 80


@dataclass(frozen=True)
class TnrConfig:
    actions_per_txn: int = 3
    require_mu_nonworsening: bool = True


@dataclass(frozen=True)
class GateConfig:
    static: bool = True
    targeted_tests: bool = True
    smoke: bool = False


@dataclass(frozen=True)
class LoggingConfig:
    dir: str = ".agent_runs"
    stream: bool = False


@dataclass(frozen=True)
class Config:
    """Aggregated configuration for the agent."""

    model: ModelConfig = field(default_factory=ModelConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    tnr: TnrConfig = field(default_factory=TnrConfig)
    gates: GateConfig = field(default_factory=GateConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        search = SearchConfig(**_filter_kwargs(data.get("search", {}), allowed=set(SearchConfig.__annotations__.keys())))
        limits = LimitsConfig(**_filter_kwargs(data.get("limits", {}), allowed=set(LimitsConfig.__annotations__.keys())))
        tnr_cfg = TnrConfig(**_filter_kwargs(data.get("tnr", {}), allowed=set(TnrConfig.__annotations__.keys())))
        gates = GateConfig(**_filter_kwargs(data.get("gates", {}), allowed=set(GateConfig.__annotations__.keys())))
        logging_cfg = LoggingConfig(
            **_filter_kwargs(data.get("logging", {}), allowed=set(LoggingConfig.__annotations__.keys()))
        )
        model_cfg = ModelConfig(**_filter_kwargs(data.get("model", {}), allowed=set(ModelConfig.__annotations__.keys())))
        return cls(
            model=model_cfg,
            search=search,
            limits=limits,
            tnr=tnr_cfg,
            gates=gates,
            logging=logging_cfg,
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Load configuration from *path* if it exists, otherwise defaults."""

        if path is None:
            path = Path("config.yaml")
        else:
            path = Path(path)
        if not path.exists():
            return cls.default()
        raw = yaml.safe_load(path.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError("Config file must contain a mapping at the top level.")
        return cls.from_dict(raw)


__all__ = [
    "Config",
    "GateConfig",
    "LimitsConfig",
    "LoggingConfig",
    "ModelConfig",
    "SearchConfig",
    "TnrConfig",
]
