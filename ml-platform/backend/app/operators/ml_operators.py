from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import io
import pandas as pd
import numpy as np
import joblib


@register_operator
class XGBoostTrainer(BaseOperator):
    id = "xgboost_train"
    name = "XGBoost Trainer"
    category = "ml"
    description = "Train an XGBoost model"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("n_estimators", "int", 100, "Number of Estimators"),
        ParamSpec("max_depth", "int", 6, "Max Depth"),
        ParamSpec("learning_rate", "float", 0.1, "Learning Rate"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
        ParamSpec("scale_pos_weight", "float", 1.0, "Positive Class Weight"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import xgboost as xgb
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        task = params.get("task", "classification")
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))
        scale_pos_weight = float(params.get("scale_pos_weight", 1.0))

        X = df.drop(columns=[target])
        y = df[target]

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if task == "classification":
            model = xgb.XGBClassifier(
                n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate, random_state=random_seed,
                eval_metric="logloss",
                scale_pos_weight=scale_pos_weight,
            )
        else:
            model = xgb.XGBRegressor(
                n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate, random_state=random_seed,
            )
        model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf); return OperatorResult(outputs={"model": buf.getvalue()})


@register_operator
class RandomForestTrainer(BaseOperator):
    id = "random_forest_train"
    name = "Random Forest Trainer"
    category = "ml"
    description = "Train a Random Forest model"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("n_estimators", "int", 100, "Number of Estimators"),
        ParamSpec("max_depth", "int", 10, "Max Depth"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
        ParamSpec("class_weight", "select", "none", "Class Weight",
                  options=["none", "balanced", "balanced_subsample"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        task = params.get("task", "classification")
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 10))
        random_seed = int(params.get("random_seed", 42))
        class_weight = params.get("class_weight", "none")

        X = df.drop(columns=[target])
        y = df[target]

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if task == "classification":
            model = RandomForestClassifier(
                n_estimators=n_estimators, max_depth=max_depth, random_state=random_seed,
                class_weight=None if class_weight == "none" else class_weight,
            )
        else:
            model = RandomForestRegressor(
                n_estimators=n_estimators, max_depth=max_depth, random_state=random_seed,
            )
        model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf); return OperatorResult(outputs={"model": buf.getvalue()})


@register_operator
class LinearModelTrainer(BaseOperator):
    id = "linear_model_train"
    name = "Linear Model Trainer"
    category = "ml"
    description = "Train a linear model (regression or classification)"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.linear_model import LinearRegression, LogisticRegression
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        task = params.get("task", "classification")
        random_seed = int(params.get("random_seed", 42))

        X = df.drop(columns=[target])
        y = df[target]

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if task == "classification":
            model = LogisticRegression(random_state=random_seed, max_iter=1000)
        else:
            model = LinearRegression()
        model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf); return OperatorResult(outputs={"model": buf.getvalue()})

import io
# === Auto-generated ML operators ===

@register_operator
class DecisionTreeOp(BaseOperator):
    id = "decision_tree"
    name = "Decision Tree"
    category = "ml"
    description = "Train a Decision Tree classifier"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("criterion", "select", "gini", "Split Criterion", options=["gini", "entropy"]),
        ParamSpec("max_depth", "int", 5, "Max Depth", range_min=1),
        ParamSpec("min_samples_split", "int", 2, "Min Samples Split", range_min=2),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.tree import DecisionTreeClassifier
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            if len(df.columns) > 0:
                target = df.columns[-1]
            else:
                raise RuntimeError(f"Target column not found and no columns available")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = DecisionTreeClassifier(criterion=params.get("criterion","gini"), max_depth=int(params.get("max_depth",5)), min_samples_split=int(params.get("min_samples_split",2)), random_state=int(params.get("random_seed",42)))
        model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class NaiveBayesOp(BaseOperator):
    id = "naive_bayes"; name = "Naive Bayes"; category = "ml"
    description = "Train a Naive Bayes classifier"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [ParamSpec("target_column", "str", "target", "Target Column")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.naive_bayes import GaussianNB
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            raise RuntimeError(f"Target '{target}' not found.")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object","category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = GaussianNB(); model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class KNNClassifierOp(BaseOperator):
    id = "knn"; name = "k-NN"; category = "ml"
    description = "k-Nearest Neighbors classifier"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [ParamSpec("target_column", "str", "target", "Target Column"), ParamSpec("k", "int", 5, "k", range_min=1)]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.neighbors import KNeighborsClassifier
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            raise RuntimeError(f"Target '{target}' not found.")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object","category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = KNeighborsClassifier(n_neighbors=int(params.get("k",5))); model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class SVMClassifierOp(BaseOperator):
    id = "svm"; name = "SVM"; category = "ml"
    description = "Support Vector Machine classifier"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [ParamSpec("target_column", "str", "target", "Target Column"), ParamSpec("kernel", "select", "rbf", "Kernel", options=["linear","rbf","poly"]), ParamSpec("C", "float", 1.0, "C"), ParamSpec("gamma", "select", "scale", "Gamma", options=["scale","auto"])]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.svm import SVC
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            raise RuntimeError(f"Target '{target}' not found.")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object","category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = SVC(kernel=params.get("kernel","rbf"), C=float(params.get("C",1.0)), gamma=params.get("gamma","scale"), probability=True); model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class LogisticRegressionOp(BaseOperator):
    id = "logistic_regression"; name = "Logistic Regression"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [ParamSpec("target_column", "str", "target", "Target Column"), ParamSpec("C", "float", 1.0, "C"), ParamSpec("max_iter", "int", 100, "Max Iter")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.linear_model import LogisticRegression
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            raise RuntimeError(f"Target '{target}' not found.")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object","category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = LogisticRegression(C=float(params.get("C",1.0)), max_iter=int(params.get("max_iter",100))); model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class KMeansOp(BaseOperator):
    id = "kmeans_clustering"; name = "k-Means"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("clusters", "DataTable", "Data with cluster labels")]
    parameters = [ParamSpec("k", "int", 3, "K", range_min=1), ParamSpec("max_runs", "int", 10, "Max Runs"), ParamSpec("random_seed", "int", 42, "Seed")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.cluster import KMeans
        data = inputs.get("data", []); df = pd.DataFrame(data)
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        model = KMeans(n_clusters=int(params.get("k",3)), n_init=int(params.get("max_runs",10)), random_state=int(params.get("random_seed",42)))
        df["cluster"] = model.fit_predict(df[num_cols])
        return OperatorResult(outputs={"clusters": df.to_dict(orient="records")})

@register_operator
class DBSCANOp(BaseOperator):
    id = "dbscan"; name = "DBSCAN"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("clusters", "DataTable", "Data with cluster labels")]
    parameters = [ParamSpec("eps", "float", 0.5, "Epsilon"), ParamSpec("min_points", "int", 5, "Min Points", range_min=1)]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.cluster import DBSCAN
        data = inputs.get("data", []); df = pd.DataFrame(data)
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        model = DBSCAN(eps=float(params.get("eps",0.5)), min_samples=int(params.get("min_points",5)))
        df["cluster"] = model.fit_predict(df[num_cols])
        return OperatorResult(outputs={"clusters": df.to_dict(orient="records")})

@register_operator
class AprioriOp(BaseOperator):
    id = "apriori"; name = "Apriori"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Transaction data")]
    outputs = [PortSpec("rules", "DataTable", "Association Rules")]
    parameters = [ParamSpec("min_support", "float", 0.1, "Min Support"), ParamSpec("min_confidence", "float", 0.5, "Min Confidence")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", []); df = pd.DataFrame(data)
        ms = float(params.get("min_support",0.1))
        rules = []
        for col in df.columns:
            for val in df[col].unique():
                s = (df[col]==val).mean()
                if s >= ms:
                    rules.append({"antecedent":col,"consequent":str(val),"support":s,"confidence":s})
        return OperatorResult(outputs={"rules": rules})

@register_operator
class FPGrowthOp(BaseOperator):
    id = "fp_growth"; name = "FP-Growth"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Transaction data")]
    outputs = [PortSpec("rules", "DataTable", "Association Rules")]
    parameters = [ParamSpec("min_support", "float", 0.1, "Min Support"), ParamSpec("min_confidence", "float", 0.5, "Min Confidence")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", []); df = pd.DataFrame(data)
        ms = float(params.get("min_support",0.1))
        rules = []
        for col in df.columns:
            for val, s in df[col].value_counts(normalize=True).items():
                if s >= ms:
                    rules.append({"item":col,"value":str(val),"support":s})
        return OperatorResult(outputs={"rules": rules})

@register_operator
class RandomForestRegressorOp(BaseOperator):
    id = "random_forest_regression"; name = "Random Forest Regression"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [ParamSpec("target_column", "str", "target", "Target Column"), ParamSpec("n_estimators", "int", 100, "Trees"), ParamSpec("max_depth", "int", 10, "Max Depth"), ParamSpec("random_seed", "int", 42, "Seed")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.ensemble import RandomForestRegressor
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            raise RuntimeError(f"Target '{target}' not found.")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object","category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = RandomForestRegressor(n_estimators=int(params.get("n_estimators",100)), max_depth=int(params.get("max_depth",10)), random_state=int(params.get("random_seed",42))); model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class SVMRegressionOp(BaseOperator):
    id = "svm_regression"; name = "SVM Regression"; category = "ml"
    inputs = [PortSpec("data", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [ParamSpec("target_column", "str", "target", "Target Column"), ParamSpec("kernel", "select", "rbf", "Kernel", options=["linear","rbf","poly"]), ParamSpec("C", "float", 1.0, "C"), ParamSpec("epsilon", "float", 0.1, "Epsilon")]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.svm import SVR
        data = inputs.get("data", []); df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        if target not in df.columns:
            raise RuntimeError(f"Target '{target}' not found.")
        X = df.drop(columns=[target]); y = df[target]
        for col in X.select_dtypes(include=["object","category"]).columns:
            X[col] = X[col].astype("category").cat.codes
        model = SVR(kernel=params.get("kernel","rbf"), C=float(params.get("C",1.0)), epsilon=float(params.get("epsilon",0.1))); model.fit(X, y)
        buf = io.BytesIO(); joblib.dump(model, buf)
        return OperatorResult(outputs={"model": buf.getvalue()})

@register_operator
class ApplyModelOp(BaseOperator):
    id = "apply_model"; name = "Apply Model"; category = "ml"
    description = "Apply a trained model to data and append predictions"
    inputs = [PortSpec("model", "Model", "Trained Model"), PortSpec("data", "DataTable", "Data to predict")]
    outputs = [PortSpec("data", "DataTable", "Data with predictions")]
    parameters = []
    def validate(self, inputs): return True
    def _predict_pytorch(self, pkg, df):
        import torch; X = torch.tensor(df.values, dtype=torch.float32)
        nc = pkg.get("net_class")
        if nc is None: raise RuntimeError("Missing net_class in model pkg")
        dim = pkg.get("input_dim", X.shape[1]); ncls = pkg.get("num_classes", 2)
        if nc.__name__ == "_MLP":
            net = nc(dim, pkg.get("hidden_layers",[64,32]), ncls, pkg.get("activation","relu"))
        elif nc.__name__ == "_CNN1D":
            net = nc(1, pkg.get("seq_length",X.shape[1]), ncls); X = X.unsqueeze(1)
        else: raise RuntimeError("Unknown: "+nc.__name__)
        net.load_state_dict(pkg["state_dict"]); net.eval()
        with torch.no_grad():
            out = net(X)
            return torch.argmax(out,dim=1).numpy() if ncls>1 else out.squeeze().numpy()
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        model_bytes = inputs.get("model"); data = inputs.get("data", [])
        df = pd.DataFrame(data)
        for col in df.select_dtypes(include=["object","category"]).columns:
            df[col] = df[col].astype("category").cat.codes
        try:
            model = joblib.load(io.BytesIO(model_bytes))
            fc = getattr(model, "feature_names_in_", None)
            if fc is not None:
                avail = [c for c in fc if c in df.columns]
                df_pred = df[avail] if avail else df
            else:
                xtra = [c for c in ["cluster","prediction","target"] if c in df.columns]
                df_pred = df.drop(columns=xtra, errors="ignore") if xtra else df
            predictions = model.predict(df_pred)
        except Exception:
            import pickle
            buf = io.BytesIO(model_bytes); pkg = pickle.load(buf)
            if pkg.get("__framework__") == "pytorch":
                predictions = self._predict_pytorch(pkg, df)
            else: raise
        df["prediction"] = predictions
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})
