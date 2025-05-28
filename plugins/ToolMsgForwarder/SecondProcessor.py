# SecondProcessor.py - ToolMsgForwarder插件的二次处理扩展示例
from loguru import logger
import base64
import json
import datetime
from utils.plugin_base import PluginBase


class SecondProcessor(PluginBase):
    """
    ToolMsgForwarder的消息二次处理示例插件
    
    本插件演示如何使用钩子系统对转发的消息进行二次处理，包括：
    1. 文本内容加密/解密
    2. 敏感词过滤
    3. 添加额外信息（如时间戳）
    4. 记录转发日志
    """
    description = "微信消息转发处理器示例 - 演示使用ToolMsgForwarder钩子系统进行消息二次处理"
    author = "ai"
    version = "1.0.0"
    
    def __init__(self):
        super().__init__()
        self.forwarder = None
        self.config = {
            "enable": True,
            "encrypt_messages": False,  # 是否加密消息内容
            "filter_sensitive_words": True,  # 是否过滤敏感词
            "add_timestamp": True,  # 是否添加时间戳
            "log_to_file": False,  # 是否记录日志到文件
            "sensitive_words": ["敏感词1", "敏感词2", "不当言论"]  # 敏感词列表
        }
        logger.info("[SecondProcessor] 二次处理插件初始化")
        
    async def on_plugins_loaded(self, plugins_map):
        """当所有插件加载完成后，注册处理器"""
        if "ToolMsgForwarder" in plugins_map:
            self.forwarder = plugins_map["ToolMsgForwarder"]
            
            # 检查是否有需要注册的处理器
            if self.config["enable"]:
                # 根据配置注册相应的处理器
                if self.config["filter_sensitive_words"]:
                    self.forwarder.register_processor("before_match", self.filter_sensitive_words)
                    
                if self.config["encrypt_messages"]:
                    self.forwarder.register_processor("after_match", self.encrypt_message)
                    self.forwarder.register_processor("before_forward", self.decrypt_message)
                    
                if self.config["add_timestamp"]:
                    self.forwarder.register_processor("before_forward", self.add_timestamp)
                    
                if self.config["log_to_file"]:
                    self.forwarder.register_processor("after_forward", self.log_forwarded_message)
                    
                logger.info("[SecondProcessor] 已根据配置注册处理器")
            else:
                logger.info("[SecondProcessor] 插件已禁用，不注册处理器")
        else:
            logger.error("[SecondProcessor] 未找到ToolMsgForwarder插件，无法注册处理器")
    
    async def convert_links(self, bot, message, rule):
        """监听转发消息并将京东链接转链"""
        if "Content" in message and isinstance(message["Content"], str):
            content = message["Content"]
            original_content = content
            """
            例子：
            ----
            京东无门槛🧧可抽三次
            https://u.jd.com/D6LNYZz
            --------
            @全体成员单白相纸小梨提醒上架！
            https://u.jd.com/DDMTG8y 
            --------
            mini相纸 人鱼尾巴10张
            https://u.jd.com/DOM35JP 
            --------
            mini相纸 马卡龙10张
            https://u.jd.com/D1McY1b 
            --------
            立拍立得 MINI相纸 锦绣相纸 10张
            https://u.jd.com/D6MaXuY 
            --------
            """
            # 如果都=是京东链接 调用接口转链

            
            # 如果内容有变化
            if content != original_content:
                logger.info(f"[SecondProcessor] 监听转发消息并将京东链接转链，消息ID: {message.get('MsgId', '未知')}")
                message["Content"] = content
                
        return message

    async def filter_sensitive_words(self, bot, message, rule):
        """过滤敏感词"""
        if "Content" in message and isinstance(message["Content"], str):
            content = message["Content"]
            original_content = content

            # 替换敏感词
            for word in self.config["sensitive_words"]:
                if word in content:
                    # 将敏感词替换为等长的星号
                    content = content.replace(word, "*" * len(word))

            # 如果内容有变化
            if content != original_content:
                logger.info(f"[SecondProcessor] 已过滤敏感词，消息ID: {message.get('MsgId', '未知')}")
                message["Content"] = content

        return message

    async def encrypt_message(self, bot, message, rule):
        """加密消息内容"""
        content_keys = ["Content", "File", "Video"]
        
        for key in content_keys:
            if key in message and message[key] and isinstance(message[key], str):
                try:
                    # 简单的Base64加密示例，实际可以使用更安全的加密算法
                    encoded = base64.b64encode(message[key].encode("utf-8")).decode("utf-8")
                    message[key] = f"ENCRYPTED:{encoded}"
                    logger.debug(f"[SecondProcessor] 已加密{key}字段，消息ID: {message.get('MsgId', '未知')}")
                except Exception as e:
                    logger.error(f"[SecondProcessor] 加密{key}字段失败: {e}")
        
        return message
    
    async def decrypt_message(self, bot, context, rule):
        """解密消息内容"""
        if "content_to_send" in context and isinstance(context["content_to_send"], str):
            content = context["content_to_send"]
            
            # 检查是否是加密内容
            if content.startswith("ENCRYPTED:"):
                try:
                    # 解密
                    encoded = content[10:]  # 去掉前缀 "ENCRYPTED:"
                    decoded = base64.b64decode(encoded).decode("utf-8")
                    context["content_to_send"] = decoded
                    logger.debug(f"[SecondProcessor] 已解密内容，目标: {context.get('target_name', '未知')}")
                except Exception as e:
                    logger.error(f"[SecondProcessor] 解密内容失败: {e}")
        
        return context
    
    async def add_timestamp(self, bot, context, rule):
        """为转发的消息添加时间戳"""
        if context.get("msg_type") == "text" and "content_to_send" in context:
            # 添加当前时间
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 根据消息内容决定添加位置
            if context["prepend_info"]:
                # 如果已经有前缀，添加到消息末尾
                context["content_to_send"] += f"\n\n[转发时间: {timestamp}]"
            else:
                # 如果没有前缀，添加到消息开头
                context["content_to_send"] = f"[转发时间: {timestamp}]\n\n{context['content_to_send']}"
                
            logger.debug(f"[SecondProcessor] 已添加时间戳，目标: {context.get('target_name', '未知')}")
        
        return context
    
    async def log_forwarded_message(self, bot, result, rule):
        """记录转发结果"""
        try:
            # 构建日志条目
            log_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "msg_type": result.get("msg_type", "未知"),
                "target": result.get("target_wxid", "未知"),
                "target_name": result.get("target_name", "未知"),
                "success": result.get("success", False)
            }
            
            if not result.get("success", False):
                log_entry["error"] = result.get("error", "未知错误")
            
            # 将日志写入文件
            with open("logs/message_forward.log", "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                
            logger.debug(f"[SecondProcessor] 已记录转发日志")
            
        except Exception as e:
            logger.error(f"[SecondProcessor] 记录转发日志失败: {e}")
    
    def on_unload(self):
        """插件卸载时，取消注册处理器"""
        if self.forwarder and self.config["enable"]:
            # 根据配置取消注册处理器
            if self.config["filter_sensitive_words"]:
                self.forwarder.unregister_processor("before_match", self.filter_sensitive_words)
                
            if self.config["encrypt_messages"]:
                self.forwarder.unregister_processor("after_match", self.encrypt_message)
                self.forwarder.unregister_processor("before_forward", self.decrypt_message)
                
            if self.config["add_timestamp"]:
                self.forwarder.unregister_processor("before_forward", self.add_timestamp)
                
            if self.config["log_to_file"]:
                self.forwarder.unregister_processor("after_forward", self.log_forwarded_message)
                
            logger.info("[SecondProcessor] 已取消注册所有处理器") 