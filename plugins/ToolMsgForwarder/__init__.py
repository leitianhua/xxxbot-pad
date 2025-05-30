from .main import ToolMsgForwarder
from .SecondProcessor import SecondProcessor, SECOND_PROCESSOR_VERSION
import importlib

# 创建SecondProcessor实例，确保它被自动加载
second_processor = SecondProcessor()

# 添加一个函数，用于获取SecondProcessor实例
def get_processor():
    """获取SecondProcessor实例，确保每次重载时都能获取新的实例"""
    global second_processor
    try:
        # 重新加载SecondProcessor模块
        import sys
        if "plugins.ToolMsgForwarder.SecondProcessor" in sys.modules:
            module = sys.modules["plugins.ToolMsgForwarder.SecondProcessor"]
            importlib.reload(module)
            # 重新创建实例
            second_processor = module.SecondProcessor()
        return second_processor
    except Exception as e:
        from loguru import logger
        logger.error(f"[ToolMsgForwarder.__init__] 获取SecondProcessor实例失败: {e}")
        import traceback
        logger.error(f"[ToolMsgForwarder.__init__] 错误堆栈: {traceback.format_exc()}")
        return second_processor