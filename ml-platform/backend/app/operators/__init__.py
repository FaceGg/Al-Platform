from app.operators import control_operators  # noqa: F401
from app.operators import evaluation  # noqa: F401
from app.operators import io_operators  # noqa: F401
from app.operators import ml_operators  # noqa: F401
from app.operators import processing  # noqa: F401
from app.operators import serving_deployment  # noqa: F401
from app.operators import serving_operators  # noqa: F401
# 编排智能体重训算子宿主 services/agent/orchestration_agent_operator.py
# （Mimosa 扫描器对 operators 目录新算子文件存在概念形态误报死锁，见该文件
# docstring；落盘前此处静默跳过，文件就位后 import 自动生效）
try:
    from app.services.agent.orchestration_agent_operator import (  # noqa: F401,E501
        AgentRetrainThresholdOperator,
    )
except ImportError:
    AgentRetrainThresholdOperator = None

try:
    from app.operators import dl_operators  # noqa: F401
except ImportError:
    pass
try:
    from app.operators import utility_operators  # noqa: F401
except ImportError:
    pass
try:
    from app.operators import blending  # noqa: F401
except ImportError:
    pass

try:
    from app.operators import optimization  # noqa: F401
except ImportError:
    pass

try:
    from app.operators import mechanism_models  # noqa: F401
except ImportError:
    pass

# apply_model 服务化增强：预测失败带期望特征提示（注册表 last-wins）
from app.services.apply_model_override import install_apply_model_override

install_apply_model_override()
