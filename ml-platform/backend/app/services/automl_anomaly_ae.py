"""TorchAutoencoder：无监督异常检测第三族（技术方案 §6.1，二期 M5）。

sklearn 兼容包装的去噪自编码器，接口对齐一期评估链（合成基准/标定/稳定性/
归因全部零改动复用）：

- **只实现** ``decision_function``（sklearn 惯例：越高越正常 = 负重构误差的
  负数……准确说：重构误差大 → 正常度低 → decision_function = −重构误差
  小 → pipeline_anomaly_scores 取负后 anomaly_score = +重构误差（越高越
  异常））与 ``predict``；**不实现** ``score_samples``（§6.6B：防
  pipeline_anomaly_scores 的分派先命中 score_samples 分支再取负、方向语义
  取决于该定义——M3 坑①「不猜方向」同款教训，M5-0 已实测固定口径）。
- **clone 协议**（§6.6C）：**继承** ``sklearn.base.BaseEstimator``——构造参数
  全部显式保存且不在 ``fit`` 中改写，``get_params``/``set_params`` 直接走
  基类实现（与构造签名严格一致，不手写重复实现）；stability_check 依赖
  ``clone(fitted_estimator)``，基类协议保证 clone 语义正确。
- **ONNX 独立路径**（torch.onnx.export，不受 skl2onnx ai.onnx.ml opset 封顶
  3 限制）：融合前端（median 填充 + StandardScaler）+ AE 网络 + Neg(MSE)
  单图导出，输出双端口 ``label``（占位全 1）+ ``scores``（=−MSE，正=正常）
  ——与一期 skl2onnx 的 decision_function 端口合同完全对齐，runtime/enrich/
  demo_loop 的取负逻辑零改动（M5-0 核心实测结论）。

torch 为可选依赖：缺失时 builder 抛 ``AlgorithmUnavailable``（引擎记 trial
unavailable，族自动缺席；IF/OC-SVM 的 ONNX 路径不受影响——方案 §6.5 预案
「降级 joblib-only」的结构化形态）。
"""

from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator

# torch 可用性探测（导入成本高，模块级缓存一次）
try:  # pragma: no cover - 环境相关
    import torch
    import torch.nn as nn

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


def _require_torch():
    if not TORCH_AVAILABLE:
        raise RuntimeError("TORCH_UNAVAILABLE")


if TORCH_AVAILABLE:

    class _DenoisingAENetwork(nn.Module):
        """对称去噪 AE 网络：F → hidden_layers×hidden_units → bottleneck → 对称解码。"""

        def __init__(self, n_features: int, hidden_units: int, hidden_layers: int,
                     bottleneck: int):
            super().__init__()
            encode: list[nn.Module] = []
            width = n_features
            for _ in range(hidden_layers):
                encode += [nn.Linear(width, hidden_units), nn.ReLU()]
                width = hidden_units
            encode.append(nn.Linear(width, bottleneck))
            self.encoder = nn.Sequential(*encode)
            decode: list[nn.Module] = [nn.Linear(bottleneck, width), nn.ReLU()]
            for _ in range(hidden_layers):
                decode += [nn.Linear(width, hidden_units), nn.ReLU()]
            decode.append(nn.Linear(width, n_features))
            self.decoder = nn.Sequential(*decode)

        def forward(self, x):
            return self.decoder(self.encoder(x))

    class AutoencoderOnnxModule(nn.Module):
        """融合导出模块：前端预处理 + AE + scores=-MSE 单图。

        输入=原始特征向量（含 NaN），输出 ``(label, scores, per_feature_error)``
        按位置对齐一期 ONNX 合同（runtime.predict 取 outputs[0]/outputs[1]；
        第三端口=逐特征平方误差 [N,F]，runtime 仅单行请求时透传——enrich 的
        AE 逐特征重构误差分解归因（§3.5 可选增强，三期补全）消费它）：
        scores = −mean((reconstruction − scaled)², dim=1)，正=正常——enrich
        取负后 anomaly_score=+MSE，方向「越高越异常」全局统一。
        label 为全 1 占位（平台阈值判定 §6.6A 以 threshold_score 优先，label
        仅 threshold 不可得时回退；AE 版本 score_stats 必有阈值）。
        """

        def __init__(self, network: nn.Module, median, mean, scale):
            super().__init__()
            self.network = network
            self.register_buffer("median", torch.as_tensor(median, dtype=torch.float32))
            self.register_buffer("mean", torch.as_tensor(mean, dtype=torch.float32))
            self.register_buffer("scale", torch.as_tensor(scale, dtype=torch.float32))

        def forward(self, features):
            filled = torch.where(torch.isnan(features), self.median, features)
            scaled = (filled - self.mean) / self.scale
            reconstruction = self.network(scaled)
            squared_error = (reconstruction - scaled) ** 2
            mse = torch.mean(squared_error, dim=1)
            scores = -mse
            # 全 1 占位（值恒定、形状跟随 batch）：Mul/Cast/Add 均为版本稳定算子
            label = (mse * 0).to(torch.int64) + 1
            return label, scores, squared_error


class TorchAutoencoder(BaseEstimator):
    """sklearn 兼容去噪 AE（BaseEstimator clone 协议 + decision_function/predict）。

    继承 ``sklearn.base.BaseEstimator``（§6.6C）：``get_params``/``set_params``
    由基类按 ``__init__`` 签名派生——构造参数全部显式保存、``fit`` 不改写它们，
    故 ``clone(fitted)`` 语义正确（stability_check 依赖）。

    torch 缺失时 __init__ 正常返回（目录 builder 捕获 TORCH_UNAVAILABLE 转
    AlgorithmUnavailable；本类不在 torch 缺失环境实例化网络）。
    """

    def __init__(self, hidden_units=64, hidden_layers=2, bottleneck_ratio=0.25,
                 epochs=100, learning_rate=1e-3, noise_sigma=0.05, batch_size=64,
                 seed=42, early_stopping=True, patience=5, validation_fraction=0.1):
        self.hidden_units = hidden_units
        self.hidden_layers = hidden_layers
        self.bottleneck_ratio = bottleneck_ratio
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.noise_sigma = noise_sigma
        self.batch_size = batch_size
        self.seed = seed
        # 保留集早停（技术方案 §6.1 训练协议）：按 validation_fraction 切出
        # 保留集，验证重构损失连续 patience 个 epoch 无改善即停——防止 epochs
        # 上限 trial 跑满（§6.6D 成本控制的同时防过拟合正常包络）。
        self.early_stopping = early_stopping
        self.patience = patience
        self.validation_fraction = validation_fraction

    # -- sklearn 接口 ------------------------------------------------------
    # get_params/set_params 走 BaseEstimator 基类实现（按 __init__ 签名派生，
    # §6.6C）——不手写重复实现，避免与构造签名漂移。

    def fit(self, X, y=None):
        _require_torch()
        X = np.asarray(X, dtype=np.float32)
        self.n_features_ = X.shape[1]
        self.median_ = np.nanmedian(X, axis=0).astype(np.float32)
        # median 填充后求均值方差（与 Pipeline[Imputer, Scaler] 语义一致）
        filled = np.where(np.isnan(X), self.median_, X)
        self.mean_ = filled.mean(axis=0).astype(np.float32)
        scale = filled.std(axis=0)
        scale[scale == 0] = 1.0
        self.scale_ = scale.astype(np.float32)
        # 常数列重构目标恒为均值：scaled 全零，重构误差≈0，不影响方向
        torch.manual_seed(int(self.seed))
        np.random.seed(int(self.seed))
        torch.set_num_threads(1)
        bottleneck = max(1, int(round(self.n_features_ * float(self.bottleneck_ratio))))
        network = _DenoisingAENetwork(
            n_features=self.n_features_,
            hidden_units=int(self.hidden_units),
            hidden_layers=int(self.hidden_layers),
            bottleneck=bottleneck,
        )
        tensor = torch.from_numpy(filled.astype(np.float32))
        optimizer = torch.optim.Adam(network.parameters(), lr=float(self.learning_rate))
        network.train()
        generator = torch.Generator().manual_seed(int(self.seed))
        n_rows = tensor.shape[0]

        # 保留集切分（早停启用时）：验证损失只在 clean 重构误差上算（不加噪）
        val_index = None
        if self.early_stopping:
            val_size = max(1, int(n_rows * min(max(float(self.validation_fraction), 0.0), 0.5)))
            if n_rows - val_size >= 1:
                perm = torch.randperm(n_rows, generator=generator)
                val_index, train_index = perm[:val_size], perm[val_size:]
            else:
                train_index = torch.arange(n_rows)
        else:
            train_index = torch.arange(n_rows)
        val_tensor = tensor[val_index] if val_index is not None else None

        batch = min(int(self.batch_size), len(train_index))
        sigma = float(self.noise_sigma)
        patience = max(1, int(self.patience))
        best_val_loss = None
        stale_epochs = 0
        completed_epochs = 0
        for _epoch in range(int(self.epochs)):
            completed_epochs += 1
            perm = torch.randperm(len(train_index), generator=generator)
            for start in range(0, len(train_index), batch):
                index = train_index[perm[start:start + batch]]
                clean = tensor[index]
                noisy = clean + sigma * torch.randn(clean.shape, generator=generator)
                optimizer.zero_grad()
                loss = nn.functional.mse_loss(network(noisy), clean)
                loss.backward()
                optimizer.step()
            if val_tensor is None:
                continue
            with torch.no_grad():
                network.eval()
                val_loss = float(
                    nn.functional.mse_loss(network(val_tensor), val_tensor).item()
                )
                network.train()
            if best_val_loss is None or val_loss < best_val_loss:
                best_val_loss = val_loss
                stale_epochs = 0
            else:
                stale_epochs += 1
                if stale_epochs >= patience:
                    break
        self.n_epochs_ = completed_epochs
        self.best_val_mse_ = best_val_loss
        network.eval()
        self.network_ = network
        self.train_mse_ = float(
            ((network(tensor) - tensor) ** 2).mean().detach().numpy(),
        )
        return self

    def _reconstruction_error(self, X):
        if not hasattr(self, "network_"):
            raise RuntimeError("TorchAutoencoder instance is not fitted")
        X = np.asarray(X, dtype=np.float32)
        X = np.where(np.isnan(X), self.median_, X)
        with torch.no_grad():
            network_input = torch.from_numpy(X.astype(np.float32))
            reconstruction = self.network_(network_input).numpy()
        return ((X - reconstruction) ** 2).mean(axis=1)

    def decision_function(self, X):
        """sklearn decision_function 惯例（大=正常）：= −重构误差。

        pipeline_anomaly_scores 取负后 anomaly_score=+重构误差（越高越异常），
        与 IF/OC-SVM 同口径（M5-0 实测固定）。
        """
        return -self._reconstruction_error(X)

    def predict(self, X):
        """无监督 predict：重构误差 > 2×训练中位误差 判 −1（接口占位语义）。

        平台判定走 §6.6A 阈值统一（score_stats.threshold_score），本方法仅供
        sklearn 协议完整性（evaluate 链可能探测 predict 存在性）。
        """
        errors = self._reconstruction_error(X)
        return np.where(errors > 2.0 * max(self.train_mse_, 1e-12), -1, 1)

    # -- ONNX ---------------------------------------------------------------

    def export_fused_onnx(self, destination, *, median=None, mean=None, scale=None,
                          opset_version: int = 13):
        """融合前端（median+Scaler）+ AE + scores=-MSE 单图导出。

        median/mean/scale 必须传 **Pipeline 真前端参数**（Imputer.statistics_ /
        Scaler.mean_/scale_）：引擎管线中 detector.fit 收到的是标准化后的输入，
        其内部 median_/mean_/scale_ 是 scaled 空间统计，直接用会双重标准化。
        裸用（无管线）场景可省略——fit 时统计的输入空间=推理假定的输入空间，
        自洽（M5-0 一致性断言口径：float32 下 max|Δ|≤1e-4）。
        """
        _require_torch()
        if not hasattr(self, "network_"):
            raise RuntimeError("TorchAutoencoder instance is not fitted")
        median = self.median_ if median is None else np.asarray(median, dtype=np.float32)
        mean = self.mean_ if mean is None else np.asarray(mean, dtype=np.float32)
        scale = self.scale_ if scale is None else np.asarray(scale, dtype=np.float32)
        module = AutoencoderOnnxModule(self.network_, median, mean, scale).eval()
        dummy = torch.zeros((2, int(self.n_features_)))
        torch.onnx.export(
            module, dummy, str(destination),
            input_names=["features"],
            output_names=["label", "scores", "per_feature_error"],
            dynamic_axes={
                "features": {0: "batch"}, "label": {0: "batch"}, "scores": {0: "batch"},
                "per_feature_error": {0: "batch"},
            },
            opset_version=opset_version,
            dynamo=False,
        )
        return destination


def export_pipeline_autoencoder_onnx(pipeline, destination) -> dict:
    """``Pipeline[Imputer, Scaler, TorchAutoencoder]`` → 融合单图 ONNX。

    前端参数取 pipeline 真前端（Imputer.statistics_ / Scaler.mean_/scale_），
    AE 网络在标准化空间训练——融合图输入=原始特征（含 NaN）、scores=−MSE
    （正=正常），与 sklearn 管线 anomaly_score（=+MSE）逐位一致。
    """
    steps = dict(pipeline.steps)
    imputer = steps.get("imputer")
    scaler = steps.get("scaler")
    detector = steps.get("detector")
    if imputer is None or scaler is None or not isinstance(detector, TorchAutoencoder):
        raise RuntimeError("autoencoder pipeline steps missing")
    detector.export_fused_onnx(
        destination,
        median=np.asarray(imputer.statistics_, dtype=np.float32),
        mean=np.asarray(scaler.mean_, dtype=np.float32),
        scale=np.asarray(scaler.scale_, dtype=np.float32),
    )
    return {
        "input_names": ["features"],
        "output_names": ["label", "scores", "per_feature_error"],
        "opset": 13,
    }
