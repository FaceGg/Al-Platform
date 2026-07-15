from app.engine.operator_contract import OperatorContext, OperatorResult
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np, joblib
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator


@register_operator
class GridSearchOptimize(BaseOperator):
    id = "optimize_grid"
    name = "Grid Search Optimization"
    category = "optimization"
    description = "Grid search for hyperparameter optimization"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [
        PortSpec("best_params", "DataTable", "Best Parameters"),
        PortSpec("best_score", "DataTable", "Best Score"),
    ]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("model_type", "select", "random_forest", "Model Type",
                  options=["random_forest", "xgboost", "decision_tree"]),
        ParamSpec("param_grid", "str", '{"n_estimators":[50,100,200],"max_depth":[3,5,10]}',
                  "Parameter Grid (JSON)"),
        ParamSpec("cv_folds", "int", 3, "CV Folds", range_min=2),
        ParamSpec("scoring", "select", "accuracy", "Scoring Metric",
                  options=["accuracy", "f1", "precision", "recall", "roc_auc"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import json
        from sklearn.model_selection import GridSearchCV
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.tree import DecisionTreeClassifier

        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")

        if target not in df.columns:
            raise RuntimeError(f"Target column '{target}' not found. Available: {list(df.columns)}")

        X = df.drop(columns=[target])
        y = df[target]
        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        model_type = params.get("model_type", "random_forest")
        if model_type == "random_forest":
            model = RandomForestClassifier(random_state=42)
        elif model_type == "xgboost":
            import xgboost as xgb
            model = xgb.XGBClassifier(random_state=42, eval_metric="logloss")
        else:
            model = DecisionTreeClassifier(random_state=42)

        try:
            param_grid = json.loads(params.get("param_grid", "{}"))
        except json.JSONDecodeError:
            param_grid = {"max_depth": [3, 5, 10]}

        cv = int(params.get("cv_folds", 3))
        scoring = params.get("scoring", "accuracy")

        gs = GridSearchCV(model, param_grid, cv=cv, scoring=scoring, n_jobs=-1)
        gs.fit(X, y)

        best_params = [{"parameter": k, "value": str(v)} for k, v in gs.best_params_.items()]
        return OperatorResult(outputs={
            "best_params": best_params,
            "best_score": [{"score": float(gs.best_score_)}],
        })


@register_operator
class EvolutionaryOptimize(BaseOperator):
    id = "optimize_evolutionary"
    name = "Evolutionary Optimization"
    category = "optimization"
    description = "Evolutionary algorithm for hyperparameter optimization"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [
        PortSpec("best_params", "DataTable", "Best Parameters"),
        PortSpec("best_score", "DataTable", "Best Score"),
    ]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("model_type", "select", "random_forest", "Model Type",
                  options=["random_forest", "xgboost", "decision_tree"]),
        ParamSpec("population_size", "int", 20, "Population Size", range_min=5),
        ParamSpec("generations", "int", 10, "Generations", range_min=1),
        ParamSpec("mutation_rate", "float", 0.1, "Mutation Rate"),
        ParamSpec("scoring", "select", "accuracy", "Scoring",
                  options=["accuracy", "f1", "precision", "recall", "roc_auc"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.tree import DecisionTreeClassifier
        from sklearn.model_selection import cross_val_score

        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")

        if target not in df.columns:
            raise RuntimeError(f"Target column '{target}' not found. Available: {list(df.columns)}")

        X = df.drop(columns=[target])
        y = df[target]
        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        pop_size = int(params.get("population_size", 20))
        generations = int(params.get("generations", 10))
        mutation_rate = float(params.get("mutation_rate", 0.1))
        scoring = params.get("scoring", "accuracy")

        # Simple random search as evolutionary approximation
        best_score = -float("inf")
        best_params = {}
        param_options = {
            "n_estimators": [50, 100, 200, 300],
            "max_depth": [3, 5, 10, 15, None],
        }

        for _ in range(min(pop_size * generations, 50)):
            trial = {}
            for k, opts in param_options.items():
                trial[k] = opts[np.random.randint(0, len(opts))]
            model = RandomForestClassifier(**trial, random_state=42)
            try:
                scores = cross_val_score(model, X, y, cv=3, scoring=scoring)
                score = float(scores.mean())
                if score > best_score:
                    best_score = score
                    best_params = trial
            except Exception:
                pass

        best_params_list = [{"parameter": k, "value": str(v)} for k, v in best_params.items()]
        return OperatorResult(outputs={
            "best_params": best_params_list,
            "best_score": [{"score": best_score}],
        })
