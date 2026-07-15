from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import numpy as np
import io

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


if TORCH_AVAILABLE:

    class _MLP(nn.Module):
        def __init__(self, input_dim, hidden_layers, output_dim, activation):
            super().__init__()
            layers = []
            prev = input_dim
            activation_fn = nn.ReLU() if activation == "relu" else nn.Tanh()
            for h in hidden_layers:
                layers.append(nn.Linear(prev, h))
                layers.append(activation_fn)
                prev = h
            layers.append(nn.Linear(prev, output_dim))
            self.net = nn.Sequential(*layers)

        def forward(self, x):
            return self.net(x)


    class _CNN1D(nn.Module):
        def __init__(self, input_channels, seq_length, num_classes):
            super().__init__()
            self.conv1 = nn.Conv1d(input_channels, 64, kernel_size=3, padding=1)
            self.conv2 = nn.Conv1d(64, 128, kernel_size=3, padding=1)
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.fc = nn.Linear(128, num_classes)

        def forward(self, x):
            x = torch.relu(self.conv1(x))
            x = torch.relu(self.conv2(x))
            x = self.pool(x).squeeze(-1)
            x = self.fc(x)
            return x


    @register_operator
    class MLPClassifier(BaseOperator):
        id = "mlp_classifier"
        name = "MLP Classifier"
        category = "dl"
        description = "Train a simple MLP classifier with PyTorch"
        inputs = [PortSpec("data", "DataTable", "Training Data")]
        outputs = [PortSpec("model", "Model", "Trained Model")]
        parameters = [
            ParamSpec("target_column", "str", "target", "Target Column"),
            ParamSpec("hidden_layers", "str", "64,32", "Hidden Layer Sizes"),
            ParamSpec("activation", "select", "relu", "Activation Function", options=["relu", "tanh"]),
            ParamSpec("epochs", "int", 10, "Epochs", range_min=1),
            ParamSpec("batch_size", "int", 32, "Batch Size", range_min=1),
            ParamSpec("learning_rate", "float", 0.001, "Learning Rate"),
            ParamSpec("device", "select", "cpu", "Device", options=["cpu", "cuda"]),
            ParamSpec("random_seed", "int", 42, "Random Seed"),
        ]

        def validate(self, inputs):
            return True

        def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
            torch.manual_seed(int(params.get("random_seed", 42)))
            data = inputs.get("data", [])
            df = pd.DataFrame(data)
            target = params.get("target_column", "target")

            cat_cols = df.drop(columns=[target]).select_dtypes(include=["object", "category"]).columns.tolist()
            if cat_cols:
                X = pd.get_dummies(df.drop(columns=[target]), columns=cat_cols).values.astype(np.float32)
            else:
                X = df.drop(columns=[target]).values.astype(np.float32)
            y = df[target].values

            if y.dtype.kind in ("O", "U"):
                from sklearn.preprocessing import LabelEncoder
                y = LabelEncoder().fit_transform(y)

            num_classes = len(np.unique(y))
            y = torch.tensor(y, dtype=torch.long)
            X = torch.tensor(X, dtype=torch.float32)

            hidden = [int(h.strip()) for h in params.get("hidden_layers", "64,32").split(",") if h.strip()]
            activation = params.get("activation", "relu")
            epochs = int(params.get("epochs", 10))
            batch_size = int(params.get("batch_size", 32))
            lr = float(params.get("learning_rate", 0.001))

            dataset = TensorDataset(X, y)
            loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

            model = _MLP(X.shape[1], hidden, num_classes, activation)
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=lr)

            model.train()
            for _ in range(epochs):
                for batch_x, batch_y in loader:
                    optimizer.zero_grad()
                    outputs = model(batch_x)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    optimizer.step()

            import pickle as _pickle
            model_pkg = {
                "__framework__": "pytorch",
                "__model_type__": "mlp_classifier",
                "state_dict": model.state_dict(),
                "input_dim": X.shape[1],
                "hidden_layers": hidden,
                "num_classes": num_classes,
                "activation": activation,
                "net_class": _MLP,
            }
            buf = io.BytesIO()
            _pickle.dump(model_pkg, buf)
            buf.seek(0)
            return OperatorResult(outputs={"model": buf.getvalue()})


    @register_operator
    class MLPRegressor(BaseOperator):
        id = "mlp_regressor"
        name = "MLP Regressor"
        category = "dl"
        description = "Train a simple MLP regressor with PyTorch"
        inputs = [PortSpec("data", "DataTable", "Training Data")]
        outputs = [PortSpec("model", "Model", "Trained Model")]
        parameters = [
            ParamSpec("target_column", "str", "target", "Target Column"),
            ParamSpec("hidden_layers", "str", "64,32", "Hidden Layer Sizes"),
            ParamSpec("activation", "select", "relu", "Activation Function", options=["relu", "tanh"]),
            ParamSpec("epochs", "int", 10, "Epochs", range_min=1),
            ParamSpec("batch_size", "int", 32, "Batch Size", range_min=1),
            ParamSpec("learning_rate", "float", 0.001, "Learning Rate"),
            ParamSpec("device", "select", "cpu", "Device", options=["cpu", "cuda"]),
            ParamSpec("random_seed", "int", 42, "Random Seed"),
        ]

        def validate(self, inputs):
            return True

        def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
            torch.manual_seed(int(params.get("random_seed", 42)))
            data = inputs.get("data", [])
            df = pd.DataFrame(data)
            target = params.get("target_column", "target")


            cat_cols = df.drop(columns=[target]).select_dtypes(include=["object", "category"]).columns.tolist()
            if cat_cols:
                X = pd.get_dummies(df.drop(columns=[target]), columns=cat_cols).values.astype(np.float32)
            else:
                X = df.drop(columns=[target]).values.astype(np.float32)
            y = df[target].values.astype(np.float32).reshape(-1, 1)
            X = torch.tensor(X, dtype=torch.float32)
            y = torch.tensor(y, dtype=torch.float32)

            hidden = [int(h.strip()) for h in params.get("hidden_layers", "64,32").split(",") if h.strip()]
            activation = params.get("activation", "relu")
            epochs = int(params.get("epochs", 10))
            batch_size = int(params.get("batch_size", 32))
            lr = float(params.get("learning_rate", 0.001))

            dataset = TensorDataset(X, y)
            loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

            model = _MLP(X.shape[1], hidden, 1, activation)
            criterion = nn.MSELoss()
            optimizer = optim.Adam(model.parameters(), lr=lr)

            model.train()
            for _ in range(epochs):
                for batch_x, batch_y in loader:
                    optimizer.zero_grad()
                    outputs = model(batch_x)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    optimizer.step()

            import pickle as _pickle
            model_pkg = {
                "__framework__": "pytorch",
                "__model_type__": "mlp_regressor",
                "state_dict": model.state_dict(),
                "input_dim": X.shape[1],
                "hidden_layers": hidden,
                "activation": activation,
                "net_class": _MLP,
            }
            buf = io.BytesIO()
            _pickle.dump(model_pkg, buf)
            buf.seek(0)
            return OperatorResult(outputs={"model": buf.getvalue()})


    @register_operator
    class CNN1DClassifier(BaseOperator):
        id = "cnn1d_classifier"
        name = "CNN1D Classifier"
        category = "dl"
        description = "Train a 1D CNN classifier with PyTorch"
        inputs = [PortSpec("data", "DataTable", "Training Data")]
        outputs = [PortSpec("model", "Model", "Trained Model")]
        parameters = [
            ParamSpec("target_column", "str", "target", "Target Column"),
            ParamSpec("epochs", "int", 10, "Epochs", range_min=1),
            ParamSpec("batch_size", "int", 32, "Batch Size", range_min=1),
            ParamSpec("learning_rate", "float", 0.001, "Learning Rate"),
            ParamSpec("device", "select", "cpu", "Device", options=["cpu", "cuda"]),
            ParamSpec("random_seed", "int", 42, "Random Seed"),
        ]

        def validate(self, inputs):
            return True

        def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
            torch.manual_seed(int(params.get("random_seed", 42)))
            data = inputs.get("data", [])
            df = pd.DataFrame(data)
            target = params.get("target_column", "target")

            cat_cols = df.drop(columns=[target]).select_dtypes(include=["object", "category"]).columns.tolist()
            if cat_cols:
                X = pd.get_dummies(df.drop(columns=[target]), columns=cat_cols).values.astype(np.float32)
            else:
                X = df.drop(columns=[target]).values.astype(np.float32)
            y = df[target].values

            if y.dtype.kind in ("O", "U"):
                from sklearn.preprocessing import LabelEncoder
                y = LabelEncoder().fit_transform(y)

            num_classes = len(np.unique(y))
            seq_length = X.shape[1]
            # Reshape to (batch, channels=1, seq_length)
            X = torch.tensor(X, dtype=torch.float32).unsqueeze(1)
            y = torch.tensor(y, dtype=torch.long)

            epochs = int(params.get("epochs", 10))
            batch_size = int(params.get("batch_size", 32))
            lr = float(params.get("learning_rate", 0.001))

            dataset = TensorDataset(X, y)
            loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

            model = _CNN1D(1, seq_length, num_classes)
            criterion = nn.CrossEntropyLoss()
            optimizer = optim.Adam(model.parameters(), lr=lr)

            model.train()
            for _ in range(epochs):
                for batch_x, batch_y in loader:
                    optimizer.zero_grad()
                    outputs = model(batch_x)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    optimizer.step()

            import pickle as _pickle
            model_pkg = {
                "__framework__": "pytorch",
                "__model_type__": "cnn1d_classifier",
                "state_dict": model.state_dict(),
                "input_channels": 1,
                "seq_length": seq_length,
                "num_classes": num_classes,
                "net_class": _CNN1D,
            }
            buf = io.BytesIO()
            _pickle.dump(model_pkg, buf)
            buf.seek(0)
            return OperatorResult(outputs={"model": buf.getvalue()})
