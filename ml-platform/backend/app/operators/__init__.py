from app.operators import control_operators  # noqa: F401
from app.operators import evaluation  # noqa: F401
from app.operators import io_operators  # noqa: F401
from app.operators import ml_operators  # noqa: F401
from app.operators import processing  # noqa: F401
from app.operators import serving_operators  # noqa: F401
from app.operators import visualization  # noqa: F401

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
