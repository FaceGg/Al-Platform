"""Immutable generic AutoML algorithm-family definitions."""

from dataclasses import dataclass, replace
from importlib import import_module
from types import MappingProxyType
from typing import Callable, Literal, Mapping

from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)


TaskType = Literal["classification", "multioutput_classification", "regression", "multioutput_regression"]


class AlgorithmUnavailable(RuntimeError):
    """Raised when a user-selected optional algorithm package is unavailable."""

    code = "AUTOML_ALGORITHM_UNAVAILABLE"

    def __init__(self, family_id: str):
        super().__init__(f"AutoML algorithm is unavailable: {family_id}")
        self.family_id = family_id


@dataclass(frozen=True)
class ParameterSpec:
    kind: Literal["categorical", "int", "float"]
    low: int | float | None = None
    high: int | float | None = None
    choices: tuple[object, ...] = ()
    log: bool = False
    step: int | float | None = None


@dataclass(frozen=True)
class AlgorithmFamily:
    id: str
    display_name: str
    default_params: Mapping[str, object]
    grid: Mapping[str, tuple[object, ...]]
    search_space: Mapping[str, ParameterSpec]
    resource_parameter: str
    min_resource: int
    max_resource: int
    builder: Callable[[TaskType, Mapping[str, object]], object]

    def build(self, task: TaskType, params: Mapping[str, object]):
        if task not in {"classification", "multioutput_classification", "regression", "multioutput_regression"}:
            raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
        base_task = "classification" if "classification" in task else "regression"
        return self.builder(base_task, MappingProxyType(dict(params)))


def _mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))


def _grid(values: Mapping[str, tuple[object, ...]]) -> Mapping[str, tuple[object, ...]]:
    return MappingProxyType({key: tuple(items) for key, items in values.items()})


def _space(values: Mapping[str, ParameterSpec]) -> Mapping[str, ParameterSpec]:
    return MappingProxyType(dict(values))


def _lightgbm_builder(task: TaskType, params: Mapping[str, object]):
    try:
        module = import_module("lightgbm")
    except ImportError as error:
        raise AlgorithmUnavailable("lightgbm") from error
    estimator = module.LGBMClassifier if task == "classification" else module.LGBMRegressor
    return estimator(random_state=42, n_jobs=1, verbosity=-1, **dict(params))


def _mlp_builder(task: TaskType, params: Mapping[str, object]):
    """sklearn MLP family: hidden layers arrive as \"256,128,64\" text.

    early_stopping stays off: its internal stratified validation split crashes
    on small imbalanced CV folds (a class with <2 members in a fold's training
    slice), which is exactly the small industrial-dataset case this platform
    serves. Regularization comes from alpha and CV-selected max_iter instead.
    """
    from sklearn.neural_network import MLPClassifier, MLPRegressor

    normalized = dict(params)
    raw_layers = str(normalized.pop("hidden_layers", "256,128,64")).strip()
    try:
        hidden = tuple(int(part) for part in raw_layers.split(",") if part.strip())
    except ValueError as error:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID") from error
    if not hidden or any(size < 1 or size > 1024 for size in hidden):
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    estimator = MLPClassifier if task == "classification" else MLPRegressor
    return estimator(
        hidden_layer_sizes=hidden,
        random_state=42,
        early_stopping=False,
        **normalized,
    )


def _xgboost_builder(task: TaskType, params: Mapping[str, object]):
    try:
        module = import_module("xgboost")
    except ImportError as error:
        raise AlgorithmUnavailable("xgboost") from error
    normalized = {"random_state": 42, "n_jobs": 1, **dict(params)}
    if task == "classification":
        normalized.setdefault("eval_metric", "logloss")
        return module.XGBClassifier(**normalized)
    normalized.setdefault("objective", "reg:squarederror")
    return module.XGBRegressor(**normalized)


def _catboost_builder(task: TaskType, params: Mapping[str, object]):
    try:
        module = import_module("catboost")
    except ImportError as error:
        raise AlgorithmUnavailable("catboost") from error
    estimator = module.CatBoostClassifier if task == "classification" else module.CatBoostRegressor
    return estimator(
        random_seed=42,
        thread_count=1,
        verbose=False,
        allow_writing_files=False,
        **dict(params),
    )


def _gbdt_builder(task: TaskType, params: Mapping[str, object]):
    estimator = GradientBoostingClassifier if task == "classification" else GradientBoostingRegressor
    return estimator(random_state=42, **dict(params))


def _random_forest_builder(task: TaskType, params: Mapping[str, object]):
    estimator = RandomForestClassifier if task == "classification" else RandomForestRegressor
    return estimator(random_state=42, n_jobs=1, **dict(params))


def _extra_trees_builder(task: TaskType, params: Mapping[str, object]):
    estimator = ExtraTreesClassifier if task == "classification" else ExtraTreesRegressor
    return estimator(random_state=42, n_jobs=1, **dict(params))


def _hist_gradient_boosting_builder(task: TaskType, params: Mapping[str, object]):
    estimator = HistGradientBoostingClassifier if task == "classification" else HistGradientBoostingRegressor
    return estimator(random_state=42, **dict(params))


def _family(
    family_id: str,
    display_name: str,
    defaults: Mapping[str, object],
    grid: Mapping[str, tuple[object, ...]],
    search_space: Mapping[str, ParameterSpec],
    resource_parameter: str,
    min_resource: int,
    max_resource: int,
    builder: Callable[[TaskType, Mapping[str, object]], object],
) -> AlgorithmFamily:
    return AlgorithmFamily(
        id=family_id,
        display_name=display_name,
        default_params=_mapping(defaults),
        grid=_grid(grid),
        search_space=_space(search_space),
        resource_parameter=resource_parameter,
        min_resource=min_resource,
        max_resource=max_resource,
        builder=builder,
    )


_COMMON_TREE_SPECS = {
    "learning_rate": ParameterSpec("float", low=0.01, high=0.2, log=True),
    "max_depth": ParameterSpec("int", low=3, high=10),
}


_FAMILIES = (
    _family(
        "lightgbm", "LightGBM",
        {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 31},
        {"n_estimators": (100, 200, 400), "learning_rate": (0.03, 0.05), "num_leaves": (15, 31, 63)},
        {
            "n_estimators": ParameterSpec("int", low=80, high=600, step=20),
            "learning_rate": ParameterSpec("float", low=0.01, high=0.2, log=True),
            "num_leaves": ParameterSpec("int", low=15, high=127),
            "subsample": ParameterSpec("float", low=0.6, high=1.0),
            "colsample_bytree": ParameterSpec("float", low=0.6, high=1.0),
        },
        "n_estimators", 80, 600, _lightgbm_builder,
    ),
    _family(
        "xgboost", "XGBoost",
        {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 5},
        {"n_estimators": (100, 200, 400), "learning_rate": (0.03, 0.05), "max_depth": (3, 5, 7)},
        {
            "n_estimators": ParameterSpec("int", low=80, high=600, step=20),
            **_COMMON_TREE_SPECS,
            "subsample": ParameterSpec("float", low=0.6, high=1.0),
            "colsample_bytree": ParameterSpec("float", low=0.6, high=1.0),
        },
        "n_estimators", 80, 600, _xgboost_builder,
    ),
    _family(
        "catboost", "CatBoost",
        {"iterations": 200, "learning_rate": 0.05, "depth": 6},
        {"iterations": (100, 200, 400), "learning_rate": (0.03, 0.05), "depth": (4, 6, 8)},
        {
            "iterations": ParameterSpec("int", low=80, high=600, step=20),
            "learning_rate": ParameterSpec("float", low=0.01, high=0.2, log=True),
            "depth": ParameterSpec("int", low=4, high=10),
            "l2_leaf_reg": ParameterSpec("float", low=1.0, high=10.0),
        },
        "iterations", 80, 600, _catboost_builder,
    ),
    _family(
        "gbdt", "GBDT",
        {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 5},
        {"n_estimators": (100, 200, 400), "learning_rate": (0.03, 0.05), "max_depth": (3, 5, 7)},
        {
            "n_estimators": ParameterSpec("int", low=80, high=600, step=20),
            **_COMMON_TREE_SPECS,
            "subsample": ParameterSpec("float", low=0.6, high=1.0),
        },
        "n_estimators", 80, 600, _gbdt_builder,
    ),
    _family(
        "random_forest", "Random Forest",
        {"n_estimators": 200, "max_depth": None, "min_samples_leaf": 1},
        {"n_estimators": (100, 200, 400), "max_depth": (None, 8, 16), "min_samples_leaf": (1, 2)},
        {
            "n_estimators": ParameterSpec("int", low=80, high=600, step=20),
            "max_depth": ParameterSpec("categorical", choices=(None, 4, 8, 12, 16, 24)),
            "min_samples_leaf": ParameterSpec("int", low=1, high=8),
            "max_features": ParameterSpec("categorical", choices=("sqrt", "log2", None)),
        },
        "n_estimators", 80, 600, _random_forest_builder,
    ),
    _family(
        "extra_trees", "Extra Trees",
        {"n_estimators": 200, "max_depth": None, "min_samples_leaf": 1},
        {"n_estimators": (100, 200, 400), "max_depth": (None, 8, 16), "min_samples_leaf": (1, 2)},
        {
            "n_estimators": ParameterSpec("int", low=80, high=600, step=20),
            "max_depth": ParameterSpec("categorical", choices=(None, 4, 8, 12, 16, 24)),
            "min_samples_leaf": ParameterSpec("int", low=1, high=8),
            "max_features": ParameterSpec("categorical", choices=("sqrt", "log2", None)),
        },
        "n_estimators", 80, 600, _extra_trees_builder,
    ),
    _family(
        "hist_gradient_boosting", "HistGradientBoosting",
        {"max_iter": 200, "learning_rate": 0.05, "max_leaf_nodes": 31},
        {"max_iter": (100, 200, 400), "learning_rate": (0.03, 0.05), "max_leaf_nodes": (15, 31, 63)},
        {
            "max_iter": ParameterSpec("int", low=80, high=600, step=20),
            "learning_rate": ParameterSpec("float", low=0.01, high=0.2, log=True),
            "max_leaf_nodes": ParameterSpec("int", low=7, high=127),
            "l2_regularization": ParameterSpec("float", low=0.0, high=2.0),
        },
        "max_iter", 80, 600, _hist_gradient_boosting_builder,
    ),
    _family(
        # 推荐默认（sklearn MLP，CPU 可跑）：adam / 0.001 / alpha 1e-4 /
        # 隐藏层 256-128-64（与拧紧质量感知报告的 MLP 结构一致）。
        "mlp", "MLP 神经网络",
        {"hidden_layers": "256,128,64", "learning_rate_init": 0.001, "solver": "adam", "alpha": 0.0001, "max_iter": 200},
        {"hidden_layers": ("128,64", "256,128,64"), "learning_rate_init": (0.001,), "solver": ("adam",), "alpha": (0.0001,)},
        {
            "hidden_layers": ParameterSpec("categorical", choices=("64", "128,64", "128,64,32", "256,128,64")),
            "learning_rate_init": ParameterSpec("float", low=0.0001, high=0.1, log=True),
            "solver": ParameterSpec("categorical", choices=("adam", "lbfgs", "sgd")),
            "alpha": ParameterSpec("float", low=0.000001, high=0.1, log=True),
            "max_iter": ParameterSpec("int", low=80, high=600, step=20),
        },
        "max_iter", 80, 600, _mlp_builder,
    ),
)

AUTOML_FAMILY_IDS = tuple(family.id for family in _FAMILIES)
_FAMILY_BY_ID = MappingProxyType({family.id: family for family in _FAMILIES})

# Search strength scales both the trial budget (SEARCH_STRENGTH_TRIALS) and
# the breadth of every family's search space. Ultra (1.0) is the identity:
# full ranges, all categorical candidates, full resource budget.
SEARCH_STRENGTH_FRACTIONS: Mapping[str, float] = MappingProxyType({
    "light": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "ultra": 1.0,
})


def _narrowed_count(choices_count: int, fraction: float) -> int:
    """Candidate count after narrowing: keep the recommended (first) choices.

    Catalog choice order is complexity order (recommended/simplest first), so
    light explores the smallest conservative subset and ultra keeps everything.
    """
    if choices_count <= 1:
        return choices_count
    import math

    return max(2, min(choices_count, 1 + math.ceil((choices_count - 1) * fraction)))


def _narrowed_spec(name: str, spec: ParameterSpec, fraction: float, *, is_resource: bool) -> ParameterSpec:
    if fraction >= 1.0:
        return spec
    if spec.kind == "categorical":
        kept = _narrowed_count(len(spec.choices), fraction)
        return ParameterSpec("categorical", choices=tuple(spec.choices[:kept]))
    if is_resource:
        # Resource budget scales from the low end: light explores short
        # training budgets, ultra the full declared range.
        low = spec.low if spec.low is not None else 0
        high = spec.high if spec.high is not None else low
        narrowed_high = low + (high - low) * fraction
        if spec.step:
            narrowed_high = max(low, min(narrowed_high, round(narrowed_high / spec.step) * spec.step))
        if spec.kind == "int":
            narrowed_high = int(narrowed_high)
        return ParameterSpec(spec.kind, low=spec.low, high=narrowed_high, choices=spec.choices, log=spec.log, step=spec.step)
    # Non-resource numeric: keep the low (conservative) end, broaden the high
    # end with strength. Log ranges narrow multiplicatively.
    low = spec.low if spec.low is not None else 0
    high = spec.high if spec.high is not None else low
    if spec.log and low > 0 and high > 0:
        narrowed_high = low * (high / low) ** fraction
    else:
        narrowed_high = low + (high - low) * fraction
    if spec.kind == "int":
        narrowed_high = int(narrowed_high)
    return ParameterSpec(spec.kind, low=spec.low, high=narrowed_high, choices=spec.choices, log=spec.log, step=spec.step)


def family_for_strength(family: AlgorithmFamily, strength: str) -> AlgorithmFamily:
    """Derive the strength-narrowed search space for one family.

    Ultra returns the family untouched. Light/medium/high narrow: the resource
    parameter's budget, continuous ranges (conservative low end first), and
    categorical candidates (recommended prefix). Grid tuples follow the same
    candidate-count rule so grid trials stay consistent with the space.
    """
    fraction = SEARCH_STRENGTH_FRACTIONS.get(strength)
    if fraction is None:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    if fraction >= 1.0:
        return family
    narrowed_space = {
        name: _narrowed_spec(name, spec, fraction, is_resource=(name == family.resource_parameter))
        for name, spec in family.search_space.items()
    }
    narrowed_grid = {
        name: tuple(values[: _narrowed_count(len(values), fraction)])
        for name, values in family.grid.items()
    }
    narrowed_resource_high = narrowed_space[family.resource_parameter].high
    return replace(
        family,
        grid=_grid(narrowed_grid),
        search_space=_space(narrowed_space),
        max_resource=int(narrowed_resource_high) if narrowed_resource_high is not None else family.max_resource,
    )


def list_algorithm_families() -> tuple[AlgorithmFamily, ...]:
    return _FAMILIES


def resolve_algorithm_families(
    family_ids: list[str] | tuple[str, ...] | None,
) -> tuple[AlgorithmFamily, ...]:
    requested = tuple(family_ids or AUTOML_FAMILY_IDS)
    if len(requested) != len(set(requested)):
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    try:
        return tuple(_FAMILY_BY_ID[family_id] for family_id in requested)
    except KeyError as error:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID") from error


def get_algorithm_family(family_id: str) -> AlgorithmFamily:
    try:
        return _FAMILY_BY_ID[family_id]
    except KeyError as error:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID") from error
