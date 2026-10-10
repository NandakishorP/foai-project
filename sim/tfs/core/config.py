"""Experiment configuration: YAML files -> frozen, validated dataclasses.

Design choices:
- **No defaults in code.** Every parameter must appear in the YAML (usually
  `base.yaml`, which documents the rationale for each value). This keeps magic
  numbers out of the code and makes every run fully described by its config.
- **Strict validation.** Unknown keys are an error. A typo such as
  `kelly_fraction` -> `kely_fraction` would otherwise silently fall back to the
  base value and corrupt an experiment without anyone noticing.
- **Inheritance.** An experiment file may say `extends: base.yaml`; its keys are
  deep-merged over the base.
- **Sweeps.** An experiment may declare `sweep:` with `crossed` parameters (every
  combination) and `one_at_a_time` parameters (vary one, others at baseline).
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

BeliefModel = Literal["own_signals", "price_anchored"]
ResearchMode = Literal["always", "endogenous"]


# --------------------------------------------------------------------------- #
# Config schema
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SeedsConfig:
    count: int  # number of master seeds (independent runs) per sweep point
    start: int  # first master seed; seeds are start, start+1, ...


@dataclass(frozen=True)
class SeasonConfig:
    n_markets: int  # markets per season (SPEC §2.1)


@dataclass(frozen=True)
class MarketConfig:
    ticks: int  # blocks per market
    prior: float  # prior P(Y=1)
    b_main: float  # LMSR liquidity of the main market
    b_ref: float  # LMSR liquidity of the reference venue


@dataclass(frozen=True)
class PublicNewsConfig:
    rate: float  # expected public news items per tick (Poisson)
    expected_nats: float  # expected total log-likelihood ratio of all public news in a market


@dataclass(frozen=True)
class PrivateSignalConfig:
    rate: float  # expected research events per tick; at each event every potential forecaster gets a signal
    pooled_nats: float  # expected LLR per market of ALL forecasters' research combined (full participation)
    rho: float  # correlation of two forecasters' signals given Y (0 = independent, 1 = one shared signal)
    max_delay: int  # each forecaster receives each research event 0..max_delay ticks late (0 = simultaneous)


@dataclass(frozen=True)
class ShockConfig:
    tick: int  # when the breaking news arrives
    nats: float  # expected log-likelihood ratio of the shock signal


@dataclass(frozen=True)
class InformationConfig:
    mu: float  # signal mean is +mu if Y=1, -mu if Y=0
    precision_scale: float  # multiplies every signal's precision (E1 sweep variable)
    public: PublicNewsConfig
    private: PrivateSignalConfig
    shocks: tuple[ShockConfig, ...]


@dataclass(frozen=True)
class ResearchConfig:
    mode: ResearchMode  # "always": everyone researches; "endogenous": SPEC §2.1 rule
    cost_median: float | None  # median research cost c_i (required when endogenous)
    cost_log_sigma: float  # lognormal spread of c_i across forecasters
    ema_alpha: float  # EMA weight on the newest researched-market profit
    explore_prob: float  # epsilon: chance to research anyway when the rule says no


@dataclass(frozen=True)
class ForecasterConfig:
    count: int  # potential forecasters
    capital_ratio: float  # bankroll per market / b_main: informed capital relative to market depth (D-015, D-029)
    kelly_fraction: float  # k in f = k (p - m) / (1 - m)
    public_latency: int  # ticks before a public signal is visible to the forecaster
    max_order: float  # largest single order, in shares
    min_order: float  # orders smaller than this are not worth sending
    research: ResearchConfig


@dataclass(frozen=True)
class PublicTraderConfig:
    count: int
    bankroll: float
    kelly_fraction: float
    delay: int  # ticks before public news is visible to this trader
    max_order: float
    min_order: float


@dataclass(frozen=True)
class NoiseConfig:
    count: int
    rate: float  # expected orders per tick, per trader (Poisson)
    mean_size: float  # order size ~ Exponential(mean_size) shares
    bankroll: float


@dataclass(frozen=True)
class ArbitrageConfig:
    count: int
    capital: float
    min_profit: float  # minimum locked-in profit (USDC) worth trading for
    slippage: float  # tolerance on each leg's average price


@dataclass(frozen=True)
class TrendConfig:
    count: int
    fast_span: int  # EMA span (ticks) of the fast moving average
    slow_span: int
    threshold: float  # minimum |fast - slow| price gap to act on
    order_size: float
    max_position: float
    bankroll: float


@dataclass(frozen=True)
class PredatorConfig:
    """MEV predator (SPEC §6). Reference values and their rationale are in base.yaml (PREREGISTRATION rule 5)."""

    count: int
    latency: float  # fraction of the block interval before it can read a pending transaction
    capital_ratio: float  # bankroll / b_main
    horizon: int  # H: ticks of the markout window; positions are unwound at H + 1
    markout_threshold: float  # log-odds continuation that counts as "the price kept moving my way"
    drift_ema_alpha: float  # EMA weight for E[drift | informed]
    bid_share: float  # share of the expected gross profit bid to the builder
    min_profit: float  # minimum expected net profit (USDC) worth acting on
    slippage: float  # tolerance on the front-run's average price
    own_impact_reversion: float  # share of its own front-run impact it expects the market to undo before it unwinds
    back_run: bool  # False: hold H ticks then unwind; True: sell right after the victim (sandwich)


@dataclass(frozen=True)
class AttackersConfig:
    """Sealed-batch attackers (E3-V, descriptive; D-046). All zero in the baseline."""

    non_reveal: int  # griefers that commit and never reveal
    free_option: int  # attackers with two identities committing opposite sides, revealing one
    spam: int  # committers of insolvent orders (rejected by the proof under zk_batch)
    size: float  # shares per attacker order
    bankroll: float


@dataclass(frozen=True)
class AgentsConfig:
    belief_model: BeliefModel  # how informed agents read the price (DECISIONS D-013)
    forecasters: ForecasterConfig
    public_main: PublicTraderConfig
    public_ref: PublicTraderConfig
    noise_main: NoiseConfig
    noise_ref: NoiseConfig
    arbitrageurs: ArbitrageConfig
    trend: TrendConfig
    predators: PredatorConfig
    attackers: AttackersConfig


MempoolPolicyName = Literal["public", "private_relay", "commit_reveal", "zk_batch"]


@dataclass(frozen=True)
class MempoolConfig:
    policy: MempoolPolicyName  # how main-market orders reach the chain (SPEC §3.2, D-046)
    base_fee: float  # fee every included transaction pays the builder (0 in the reference config, D-033)
    batch_interval: int  # K: blocks per sealed batch (commit_reveal / zk_batch)
    escrow_tiers: tuple[float, ...]  # fixed escrow sizes (USDC), so escrow does not reveal order size
    proving_delay: int  # ticks to generate a ZK proof before a sealed order can be committed (zk_batch)
    sender_visible: bool  # can observers see who sent a commitment? False = relayer variant


@dataclass(frozen=True)
class MetricsConfig:
    epsilon: float  # tolerance for time-to-epsilon after shocks


@dataclass(frozen=True)
class SimConfig:
    name: str
    seeds: SeedsConfig
    season: SeasonConfig
    market: MarketConfig
    information: InformationConfig
    agents: AgentsConfig
    mempool: MempoolConfig
    metrics: MetricsConfig

    def __post_init__(self) -> None:
        _validate(self)


def _validate(cfg: SimConfig) -> None:
    """Cross-field checks that the type system cannot express."""
    research = cfg.agents.forecasters.research
    if research.mode == "endogenous" and research.cost_median is None:
        raise ConfigError("agents.forecasters.research.cost_median is required when mode is 'endogenous'")
    if not 0.0 < cfg.market.prior < 1.0:
        raise ConfigError("market.prior must be in (0, 1)")
    for shock in cfg.information.shocks:
        if not 0 <= shock.tick < cfg.market.ticks:
            raise ConfigError(f"shock tick {shock.tick} is outside the market")
    if cfg.mempool.batch_interval < 1:
        raise ConfigError("mempool.batch_interval must be at least 1")
    if list(cfg.mempool.escrow_tiers) != sorted(cfg.mempool.escrow_tiers) or not cfg.mempool.escrow_tiers:
        raise ConfigError("mempool.escrow_tiers must be a non-empty increasing list")
    if not 0.0 <= cfg.information.private.rho <= 1.0:
        raise ConfigError("information.private.rho must be in [0, 1]")
    if cfg.agents.trend.fast_span >= cfg.agents.trend.slow_span:
        raise ConfigError("agents.trend.fast_span must be shorter than slow_span")


class ConfigError(ValueError):
    """Raised for malformed or inconsistent configuration."""


# --------------------------------------------------------------------------- #
# dict -> dataclass conversion with strict checking
# --------------------------------------------------------------------------- #


def build(cls: type, data: Any, path: str = "") -> Any:
    """Recursively build dataclass `cls` from plain YAML data, rejecting unknown or missing keys."""
    if not isinstance(data, dict):
        raise ConfigError(f"{path or 'config'}: expected a mapping, got {type(data).__name__}")
    hints = typing.get_type_hints(cls)
    field_names = [f.name for f in dataclasses.fields(cls)]
    unknown = set(data) - set(field_names)
    if unknown:
        raise ConfigError(f"{path or 'config'}: unknown key(s) {sorted(unknown)}")
    missing = [name for name in field_names if name not in data]
    if missing:
        raise ConfigError(f"{path or 'config'}: missing key(s) {missing}")
    kwargs = {name: _convert(hints[name], data[name], f"{path}.{name}".lstrip(".")) for name in field_names}
    return cls(**kwargs)


def _convert(tp: Any, value: Any, path: str) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    if dataclasses.is_dataclass(tp):
        return build(tp, value, path)
    if origin is Literal:
        if value not in args:
            raise ConfigError(f"{path}: {value!r} is not one of {list(args)}")
        return value
    if origin in (typing.Union, types.UnionType):  # e.g. float | None
        if value is None and type(None) in args:
            return None
        non_none = [a for a in args if a is not type(None)]
        return _convert(non_none[0], value, path)
    if origin is tuple:  # tuple[X, ...]
        if not isinstance(value, list):
            raise ConfigError(f"{path}: expected a list")
        return tuple(_convert(args[0], item, f"{path}[{i}]") for i, item in enumerate(value))
    if tp is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{path}: expected true or false, got {value!r}")
        return value
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path}: expected a number, got {value!r}")
        return float(value)
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path}: expected an integer, got {value!r}")
        return value
    if tp is str:
        if not isinstance(value, str):
            raise ConfigError(f"{path}: expected a string, got {value!r}")
        return value
    raise ConfigError(f"{path}: unsupported config type {tp}")


# --------------------------------------------------------------------------- #
# Loading files, inheritance and sweeps
# --------------------------------------------------------------------------- #


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return `base` with `override` merged in; nested mappings merge, everything else replaces."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_raw(path: Path) -> dict[str, Any]:
    """Load a YAML file, resolving `extends:` chains. Returns plain data (sweep kept, unvalidated)."""
    path = Path(path)
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    parent = data.pop("extends", None)
    if parent is None:
        return data
    base = load_raw(path.parent / parent)
    base.pop("sweep", None)  # a sweep (and its analysis) belongs to the file that declares it, not its children
    base.pop("analysis", None)
    return deep_merge(base, data)


def set_dotted(data: dict[str, Any], dotted: str, value: Any) -> dict[str, Any]:
    """Return a copy of `data` with the key at `dotted` path (e.g. 'agents.trend.count') replaced."""
    keys = dotted.split(".")
    out = copy.deepcopy(data)
    node = out
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            raise ConfigError(f"sweep parameter {dotted!r}: no such section {key!r}")
        node = node[key]
    if keys[-1] not in node:
        raise ConfigError(f"sweep parameter {dotted!r}: no such key")
    node[keys[-1]] = value
    return out


def get_dotted(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            raise ConfigError(f"parameter {dotted!r}: no such key {key!r}")
        node = node[key]
    return node


@dataclass(frozen=True)
class SweepPoint:
    """One configuration in an experiment, with the swept values that define it."""

    label: str
    params: dict[str, Any]  # effective value of every swept parameter at this point
    config: SimConfig


def expand_sweep(raw: dict[str, Any]) -> list[SweepPoint]:
    """Expand an experiment's raw config into its sweep points.

    `crossed` parameters are fully crossed with each other. Within each crossed
    combination, the baseline point is included once, then each
    `one_at_a_time` parameter is varied alone (values equal to the baseline are
    skipped as duplicates). With no `sweep:` key there is a single point.
    """
    raw = copy.deepcopy(raw)
    raw.pop("analysis", None)  # paired-analysis settings, read by the runner, not part of SimConfig
    sweep = raw.pop("sweep", None) or {}
    unknown = set(sweep) - {"crossed", "one_at_a_time"}
    if unknown:
        raise ConfigError(f"sweep: unknown key(s) {sorted(unknown)}")
    crossed: dict[str, list[Any]] = sweep.get("crossed") or {}
    ofat: dict[str, list[Any]] = sweep.get("one_at_a_time") or {}
    swept_names = list(crossed) + [name for name in ofat if name not in crossed]

    points: list[SweepPoint] = []
    for combo in itertools.product(*crossed.values()) if crossed else [()]:
        base = raw
        for name, value in zip(crossed, combo):
            base = set_dotted(base, name, value)
        variants: list[tuple[str, dict[str, Any]]] = [("baseline", base)]
        for name, values in ofat.items():
            for value in values:
                if value == get_dotted(base, name):
                    continue
                variants.append((f"{name}={value}", set_dotted(base, name, value)))
        crossed_label = "|".join(f"{name}={value}" for name, value in zip(crossed, combo))
        for variant_label, data in variants:
            label = "|".join(part for part in (crossed_label, variant_label) if part)
            params = {name: get_dotted(data, name) for name in swept_names}
            points.append(SweepPoint(label=label, params=params, config=build(SimConfig, data)))
    return points


def load_config(path: Path) -> SimConfig:
    """Load a single (non-swept) configuration."""
    raw = load_raw(path)
    raw.pop("sweep", None)
    raw.pop("analysis", None)
    return build(SimConfig, raw)


def replace_in(cfg: SimConfig, dotted: str, value: Any) -> SimConfig:
    """Return a copy of `cfg` with one nested field replaced (used by tests and calibration)."""
    keys = dotted.split(".")

    def _replace(obj: Any, remaining: list[str]) -> Any:
        if len(remaining) == 1:
            return dataclasses.replace(obj, **{remaining[0]: value})
        child = getattr(obj, remaining[0])
        return dataclasses.replace(obj, **{remaining[0]: _replace(child, remaining[1:])})

    return _replace(cfg, keys)
