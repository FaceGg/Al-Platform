"""Immutable generic AutoML algorithm-family definitions."""

from dataclasses import dataclass
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
)

AUTOML_FAMILY_IDS = tuple(family.id for family in _FAMILIES)
_FAMILY_BY_ID = MappingProxyType({family.id: family for family in _FAMILIES})


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
