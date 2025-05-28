from loguru import logger
import tomllib
import os
import requests
import json
import time
import uuid
import tempfile
import io
from PIL import Image
from typing import Optional
import traceback

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


# 添加Session类用于保存对话历史
class PollinationsSession(object):
    def __init__(self, session_id):
        self.session_id = session_id
        self.messages = []  # 存储对话消息
        self.max_history = 10  # 默认保存最近10条消息
    
    def add_message(self, role, content):
        """添加一条消息到历史记录"""
        self.messages.append({"role": role, "content": content})
        # 如果消息数量超过最大限制，移除最早的消息
        if len(self.messages) > self.max_history:
            self.messages.pop(0)
    
    def get_history(self):
        """获取会话历史"""
        return self.messages
    
    def get_openai_messages(self, system_prompt=None, current_prompt=None):
        """获取符合OpenAI格式的消息历史"""
        messages = []
        
        # 添加系统提示
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # 添加历史消息
        for msg in self.messages:
            messages.append(msg)
        
        # 添加当前提示（如果有）
        if current_prompt:
            messages.append({"role": "user", "content": current_prompt})
            
        return messages
    
    def clear(self):
        """清空会话历史"""
        self.messages = []


# 添加SessionManager类用于管理所有会话
class PollinationsSessionManager(object):
    def __init__(self):
        self.sessions = {}  # 存储所有会话
    
    def get_session(self, session_id):
        """获取会话，如果不存在则创建新会话"""
        if session_id not in self.sessions:
            self.sessions[session_id] = PollinationsSession(session_id)
        return self.sessions[session_id]
    
    def clear_session(self, session_id):
        """清除指定会话的历史记录"""
        if session_id in self.sessions:
            self.sessions[session_id].clear()
    
    def clear_all_sessions(self):
        """清除所有会话的历史记录"""
        for session in self.sessions.values():
            session.clear()


class ToolPollinationsChat(PluginBase):
    description = "一个AI的聊天插件，支持文本和语音回复"
    author = "AI Assistant"
    version = "0.2"
    is_ai_platform = True  # 标记为AI平台插件

    def __init__(self):
        super().__init__()
        try:
            # 加载配置
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            logger.debug(f"[Pollinations聊天] 尝试加载配置文件: {config_path}")
            
            try:
                if not os.path.exists(config_path):
                    logger.error(f"[Pollinations聊天] 配置文件不存在: {config_path}")
                    self.enable = False
                    return
                    
                with open(config_path, "rb") as f:
                    try:
                        config = tomllib.load(f)
                        logger.debug(f"[Pollinations聊天] 成功加载配置文件: {config}")
                    except tomllib.TOMLDecodeError as e:
                        logger.error(f"[Pollinations聊天] 配置文件格式错误: {str(e)}")
                        self.enable = False
                        return
                    
                # 读取基本配置
                basic_config = config.get("basic", {})
                self.enable = basic_config.get("enable", False)
                logger.debug(f"[Pollinations聊天] 读取enable配置: {self.enable}")
                
                # 提取命令前缀配置
                cmd_prefixes = config.get("command_prefixes", {})
                self.chat_prefix = cmd_prefixes.get("chat", ["p问", "p聊"])
                logger.debug(f"[Pollinations聊天] 读取chat_prefix配置: {self.chat_prefix}")
                
                self.voice_toggle_prefix = cmd_prefixes.get("voice_toggle", ["p语音开关"])
                self.voice_set_prefix = cmd_prefixes.get("voice_set", ["p设置语音"])
                self.clear_memory_prefix = cmd_prefixes.get("clear_memory", ["p清除记忆"])
                self.role_list_prefix = cmd_prefixes.get("role_list", ["p角色列表"])
                self.role_switch_prefix = cmd_prefixes.get("role_switch", ["p切换角色"])
                self.model_list_prefix = cmd_prefixes.get("model_list", ["p模型列表"])
                self.model_switch_prefix = cmd_prefixes.get("model_switch", ["p切换模型"])
                
                # 提取机器人名称配置 (从插件config.toml)
                self.robot_names = config.get("robot_names", ["AI", "毛球", "小助手", "小x", "机器人"])
                logger.debug(f"[Pollinations聊天] 从插件配置读取robot_names: {self.robot_names}")
                
                # 尝试从主配置文件加载并合并机器人名称
                try:
                    with open("main_config.toml", "rb") as f:
                        main_config = tomllib.load(f)
                        xybot_config = main_config.get("XYBot", {})
                        
                        main_robot_names = xybot_config.get("robot-names", [])
                        if main_robot_names:
                            for name in main_robot_names:
                                if name not in self.robot_names:
                                    self.robot_names.append(name)
                            logger.info(f"[Pollinations聊天] 合并主配置中的robot-names, 当前robot_names: {self.robot_names}")
                except Exception as e:
                    logger.warning(f"[Pollinations聊天] 从主配置加载robot-names失败: {e}")
                
                # 提取语音设置
                voice_config = config.get("voice", {})
                self.enable_voice = voice_config.get("enable", False)
                self.default_voice = voice_config.get("default_type", "alloy")
                
                # 提取记忆设置
                memory_config = config.get("memory", {})
                self.enable_memory = memory_config.get("enable", True)
                self.max_history = memory_config.get("max_history", 10)
                
                # 提取角色设置
                roles_config = config.get("roles", {})
                self.current_role = roles_config.get("default", "assistant")
                
                # 获取所有可用角色
                self.roles = {}
                for key, value in roles_config.items():
                    if key != "default" and isinstance(value, dict):
                        self.roles[key] = value
                
                # 提取API设置
                api_config = config.get("api", {})
                self.api_model = api_config.get("model", "openai")
                
                # 构建API参数
                self.api_params = {
                    "model": self.api_model
                }
                
                # 请求默认设置
                self.default_headers = {
                    "Accept": "*/*",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                    "Referer": "https://pollinations.ai/"
                }
                
                # API基础URL - 使用OpenAI兼容接口
                self.openai_api_url = "https://text.pollinations.ai/openai"
                self.text_models_url = "https://text.pollinations.ai/models"
                
                # 可用的语音选项
                self.available_voices = [
                    "alloy", "echo", "fable", "onyx", "nova", "shimmer"
                ]
                
                # 可用模型缓存
                self.available_models = None
                self.models_last_update = 0
                self.models_cache_ttl = 3600  # 缓存1小时更新一次
                
                # 初始化会话管理器
                self.session_manager = PollinationsSessionManager()
                
                # 添加图片处理相关属性
                self.image_cache = {}  # 存储用户图片缓存 {user_id: {"content": bytes, "timestamp": time}}
                self.image_cache_timeout = 60  # 图片缓存超时时间（秒）
                self.processed_messages = {}  # 存储已处理消息ID，防止重复处理
                self.message_expiry = 60  # 消息处理记录的过期时间（秒）
                self.files_dir = "files"  # 文件存储目录
                # 创建文件存储目录（如果不存在）
                os.makedirs(self.files_dir, exist_ok=True)
                
                logger.info(f"[Pollinations聊天] 插件初始化成功，当前角色：{self.current_role}，当前模型：{self.api_model}，机器人名称：{self.robot_names}")
            except Exception as e:
                logger.error(f"[Pollinations聊天] 加载配置文件失败: {str(e)}")
                self.enable = False  # 如果加载失败，禁用插件
                
        except Exception as e:
            logger.error(f"[Pollinations聊天] 插件初始化失败: {e}")
            self.enable = False

    @on_text_message(priority=20)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            logger.debug("[Pollinations聊天] 插件未启用")
            return True # 插件未启用，允许其他插件处理

        content = message.get("Content", "").strip()
        logger.debug(f"[Pollinations聊天] 收到消息: {content}")
        logger.debug(f"[Pollinations聊天] 插件状态: enable={self.enable}, chat_prefix={self.chat_prefix}")
        
        # 获取会话ID
        session_id = self._get_session_id(message)
        logger.debug(f"[Pollinations聊天] 会话ID: {session_id}")
        
        # 检查是否是群聊
        is_group = "IsGroup" in message and message["IsGroup"]
        
        # 检查群聊中是否包含@机器人，如果是群聊但没有@机器人，则跳过处理
        if is_group and not self._is_at_robot(message):
            logger.debug("[Pollinations聊天] 群聊消息未@机器人，跳过处理")
            return True
        
        # 检查是否是插件命令
        is_cmd = self._is_command(content)
        logger.debug(f"[Pollinations聊天] 是否是命令: {is_cmd}")
        
        # 添加详细日志
        logger.debug(f"[Pollinations聊天] 模型列表前缀: {self.model_list_prefix}")
        logger.debug(f"[Pollinations聊天] 模型切换前缀: {self.model_switch_prefix}")
        
        # 检查是否是模型列表命令
        is_model_list = False
        for prefix in self.model_list_prefix:
            if content.startswith(prefix):
                is_model_list = True
                logger.debug(f"[Pollinations聊天] 匹配到模型列表命令: {prefix}")
                break
        logger.debug(f"[Pollinations聊天] 是否是模型列表命令: {is_model_list}")
        
        # 检查是否是模型切换命令
        is_model_switch = False
        for prefix in self.model_switch_prefix:
            if content.startswith(prefix):
                is_model_switch = True
                logger.debug(f"[Pollinations聊天] 匹配到模型切换命令: {prefix}")
                break
        logger.debug(f"[Pollinations聊天] 是否是模型切换命令: {is_model_switch}")
        
        if is_cmd:
            # 处理角色列表命令
            if self._check_prefix(content, self.role_list_prefix):
                logger.info("[Pollinations聊天] 处理角色列表命令")
                await self._handle_role_list(bot, message)
                return False  # 阻止后续插件处理
                
            # 处理角色切换命令
            elif self._check_prefix(content, self.role_switch_prefix):
                logger.info("[Pollinations聊天] 处理角色切换命令")
                await self._handle_role_switch(bot, message, session_id)
                return False  # 阻止后续插件处理
            
            # 处理模型列表命令
            elif self._check_prefix(content, self.model_list_prefix):
                logger.info("[Pollinations聊天] 处理模型列表命令")
                await self._handle_model_list(bot, message)
                return False  # 阻止后续插件处理
                
            # 处理模型切换命令
            elif self._check_prefix(content, self.model_switch_prefix):
                logger.info("[Pollinations聊天] 处理模型切换命令")
                await self._handle_model_switch(bot, message)
                return False  # 阻止后续插件处理
            
            # 处理清除记忆命令
            elif self._check_prefix(content, self.clear_memory_prefix):
                logger.info("[Pollinations聊天] 处理清除记忆命令")
                await self._handle_clear_memory(bot, message, session_id)
                return False  # 阻止后续插件处理
            
            # 处理语音开关命令
            elif self._check_prefix(content, self.voice_toggle_prefix):
                logger.info("[Pollinations聊天] 处理语音开关命令")
                await self._handle_voice_toggle(bot, message)
                return False  # 阻止后续插件处理
            
            # 处理设置语音命令
            elif self._check_prefix(content, self.voice_set_prefix):
                logger.info("[Pollinations聊天] 处理设置语音命令")
                await self._handle_voice_set(bot, message)
                return False  # 阻止后续插件处理
                
            # 当chat_prefix为空时，优先处理聊天功能
            elif not self.chat_prefix or self._check_prefix(content, self.chat_prefix):
                logger.info("[Pollinations聊天] 处理聊天命令")
                await self._handle_chat(bot, message, session_id)
                return False  # 阻止后续插件处理
        
        logger.debug("[Pollinations聊天] 消息未匹配任何命令，允许后续插件处理")
        return True  # 允许后续插件处理
    
    def _get_session_id(self, message):
        """获取会话ID，区分私聊和群聊"""
        # 判断是否是群聊
        is_group = "IsGroup" in message and message["IsGroup"]
        
        if is_group:
            # 群聊：使用群ID作为会话ID
            return f"group_{message['FromWxid']}"
        else:
            # 私聊：使用发送者ID作为会话ID
            return f"private_{message['FromWxid']}"
    
    def _is_command(self, content):
        """检查消息是否是插件命令"""
        # 如果chat_prefix为空列表，则所有消息都认为是聊天命令
        if not self.chat_prefix:
            logger.debug("[Pollinations聊天] chat_prefix为空，所有消息都视为命令")
            return True
            
        # 检查模型列表命令
        for prefix in self.model_list_prefix:
            if content.startswith(prefix):
                logger.debug(f"[Pollinations聊天] 检测到模型列表命令: {prefix}")
                return True
                
        # 检查模型切换命令
        for prefix in self.model_switch_prefix:
            if content.startswith(prefix):
                logger.debug(f"[Pollinations聊天] 检测到模型切换命令: {prefix}")
                return True
        
        # 检查其他命令前缀
        if content.startswith(tuple(self.voice_toggle_prefix)):
            logger.debug("[Pollinations聊天] 检测到语音开关命令")
            return True
        if content.startswith(tuple(self.voice_set_prefix)):
            logger.debug("[Pollinations聊天] 检测到设置语音命令")
            return True
        if content.startswith(tuple(self.clear_memory_prefix)):
            logger.debug("[Pollinations聊天] 检测到清除记忆命令")
            return True
        if content.startswith(tuple(self.role_list_prefix)):
            logger.debug("[Pollinations聊天] 检测到角色列表命令")
            return True
        if content.startswith(tuple(self.role_switch_prefix)):
            logger.debug("[Pollinations聊天] 检测到角色切换命令")
            return True
            
        logger.debug("[Pollinations聊天] 未检测到任何命令前缀")
        return False
    
    def _check_prefix(self, content, prefix_list):
        """检查消息是否以指定前缀开始"""
        # 如果是空前缀列表且是在检查chat_prefix，则返回空字符串作为前缀
        if not prefix_list and prefix_list is self.chat_prefix:
            logger.debug("[Pollinations聊天] chat_prefix为空列表，返回空字符串作为前缀")
            return ""
        
        logger.debug(f"[Pollinations聊天] 检查前缀，内容: '{content}'，前缀列表: {prefix_list}")
            
        for prefix in prefix_list:
            if content.startswith(prefix):
                logger.debug(f"[Pollinations聊天] 匹配到前缀: '{prefix}'")
                return prefix
                
        logger.debug(f"[Pollinations聊天] 未匹配到任何前缀")
        return None
    
    def _extract_prompt(self, content, prefix):
        """从消息中提取提示词"""
        prompt = content[len(prefix):].strip()
        return prompt
    
    def _get_system_prompt(self):
        """获取当前角色的系统提示"""
        role_config = self.roles.get(self.current_role)
        if role_config and "description" in role_config:
            return role_config["description"]
        return "你是个乐于助人的AI助手"
    
    def is_message_processed(self, message: dict) -> bool:
        """检查消息是否已经处理过"""
        # 清理过期的消息记录
        current_time = time.time()
        expired_keys = []
        for msg_id, timestamp in self.processed_messages.items():
            if current_time - timestamp > self.message_expiry:
                expired_keys.append(msg_id)

        for key in expired_keys:
            del self.processed_messages[key]

        # 获取消息ID
        msg_id = message.get("MsgId") or message.get("NewMsgId")
        if not msg_id:
            return False  # 如果没有消息ID，视为未处理过

        # 检查消息是否已处理
        return msg_id in self.processed_messages
    
    def mark_message_processed(self, message: dict):
        """标记消息为已处理"""
        msg_id = message.get("MsgId") or message.get("NewMsgId")
        if msg_id:
            self.processed_messages[msg_id] = time.time()
    
    def _is_at_robot(self, message: dict) -> bool:
        """检查消息是否@了机器人
        
        仅通过匹配机器人名称 (self.robot_names) 来判断是否@了机器人。
        参考Dify插件的实现，支持检测普通消息和引用消息中的@。
        """
        if not message.get("IsGroup", False):
            # 私聊消息不需要@，直接视为@了机器人进行处理
            return True

        content = message.get("Content", "")
        logger.debug(f"[Pollinations聊天] 检查消息是否@机器人 (原始消息内容): {content[:100]}...")

        # 检查消息内容是否直接@机器人名称或包含@机器人名称
        for robot_name in self.robot_names:
            # 1. 内容以 "@机器人名称" 开头 (处理空格和大小写)
            if content.lower().startswith(f"@{robot_name.lower()}"):
                logger.debug(f"[Pollinations聊天] 内容以 '@{robot_name}' (忽略大小写) 开头")
                return True
            
            # 2. 内容中包含 "@机器人名称" (处理空格和大小写，确保是完整的词)
            # 使用正则表达式确保匹配到的是独立的@robot_name，而不是robot_name是其他词的一部分
            import re
            # 是一个细空格，微信中@人之后可能会跟这个空格
            pattern_at = re.compile(f"@{re.escape(robot_name)}(?:\s| |$)|\[atname={re.escape(robot_name)}\]", re.IGNORECASE)
            if pattern_at.search(content):
                logger.debug(f"[Pollinations聊天] 内容中通过正则找到 '@{robot_name}' 或 '[atname={robot_name}]'.")
                return True
        
        # 检查引用消息 (Quote)
        if "Quote" in message:
            quote_info = message.get("Quote", {})
            quoted_content = quote_info.get("Content", "")
            quoted_sender_nickname = quote_info.get("Nickname", "") # 被引用消息的发送者昵称
            
            logger.debug(f"[Pollinations聊天] 检查引用消息: 被引用的内容='{quoted_content[:50]}...', 被引用者='{quoted_sender_nickname}'")

            # 2.1. 当前消息内容@机器人 (上面已检查过，这里是为了逻辑清晰)
            # 检查当前消息的文本部分是否@机器人
            for robot_name in self.robot_names:
                if content.lower().startswith(f"@{robot_name.lower()}"):
                    logger.debug(f"[Pollinations聊天] 引用场景下，当前消息内容以 '@{robot_name}' (忽略大小写) 开头")
                    return True
                
                import re
                pattern_at = re.compile(f"@{re.escape(robot_name)}(?:\s| |$)|\[atname={re.escape(robot_name)}\]", re.IGNORECASE)
                if pattern_at.search(content):
                    logger.debug(f"[Pollinations聊天] 引用场景下，当前消息内容通过正则找到 '@{robot_name}' 或 '[atname={robot_name}]'.")
                    return True
            
            # 2.2. 检查被引用的消息是否是机器人自己发的
            for robot_name in self.robot_names:
                if robot_name.lower() == quoted_sender_nickname.lower():
                    logger.debug(f"[Pollinations聊天] 引用了机器人 '{robot_name}' (昵称匹配) 的消息")
                    return True
            
            # 2.3. 检查被引用的消息内容中是否@了机器人
            if quoted_content:
                for robot_name in self.robot_names:
                    import re
                    pattern_at_quoted = re.compile(f"@{re.escape(robot_name)}(?:\s| |$)|\[atname={re.escape(robot_name)}\]", re.IGNORECASE)
                    if pattern_at_quoted.search(quoted_content):
                        logger.debug(f"[Pollinations聊天] 在引用的消息内容中发现 '@{robot_name}' 或 '[atname={robot_name}]'.")
                        return True
        
        # 检查消息中是否直接包含机器人名称 (即使没有@符号，某些场景下也可能需要响应)
        # Dify插件有类似逻辑: "特殊处理：如果消息内容中包含机器人名称（不带@符号）"
        # 此部分逻辑可以根据需要决定是否启用或调整
        # for robot_name in self.robot_names:
        #     if robot_name.lower() in content.lower():
        #         logger.debug(f"[Pollinations聊天] 在消息内容中发现机器人名称 (无@): {robot_name}")
        #         return True

        logger.debug(f"[Pollinations聊天] 未检测到@机器人")
        return False
    
    @on_image_message(priority=50)
    async def handle_image(self, bot: WechatAPIClient, message: dict):
        """处理图片消息，缓存图片以便后续使用"""
        if not self.enable:
            return True

        try:
            # 获取图片消息的关键信息
            msg_id = message.get("MsgId")
            from_wxid = message.get("FromWxid")
            sender_wxid = message.get("SenderWxid", from_wxid)

            logger.info(f"[Pollinations聊天] 收到图片消息: MsgId={msg_id}, FromWxid={from_wxid}, SenderWxid={sender_wxid}")

            # 尝试多种方式获取图片内容
            image_content = None
            xml_content = message.get("Content")

            # 1. 检查二进制数据
            if isinstance(xml_content, bytes):
                try:
                    Image.open(io.BytesIO(xml_content))
                    image_content = xml_content
                    logger.info(f"[Pollinations聊天] 从二进制数据获取图片成功，大小: {len(xml_content)} 字节")
                except Exception as e:
                    logger.error(f"[Pollinations聊天] 二进制图片数据无效: {e}")

            # 2. 检查base64数据
            elif isinstance(xml_content, str) and (xml_content.startswith('/9j/') or xml_content.startswith('iVBOR')):
                try:
                    import base64
                    xml_content = xml_content.strip().replace('\n', '').replace('\r', '')
                    image_data = base64.b64decode(xml_content)
                    Image.open(io.BytesIO(image_data))
                    image_content = image_data
                    logger.info(f"[Pollinations聊天] 从base64数据获取图片成功，大小: {len(image_data)} 字节")
                except Exception as e:
                    logger.error(f"[Pollinations聊天] base64图片数据无效: {e}")

            # 3. 检查XML数据
            elif isinstance(xml_content, str) and "<?xml" in xml_content:
                try:
                    root = ET.fromstring(xml_content)
                    img_element = root.find('img')
                    if img_element is not None:
                        md5 = img_element.get('md5')
                        aeskey = img_element.get('aeskey')
                        length = img_element.get('length')
                        
                        if length and length.isdigit():
                            img_length = int(length)
                            # 分段下载大图片
                            chunk_size = 64 * 1024  # 64KB
                            chunks = (img_length + chunk_size - 1) // chunk_size
                            
                            full_image_data = bytearray()
                            for i in range(chunks):
                                chunk_data = await bot.get_msg_image(msg_id, from_wxid, img_length, start_pos=i*chunk_size)
                                if chunk_data:
                                    full_image_data.extend(chunk_data)
                            
                            if full_image_data:
                                image_content = bytes(full_image_data)
                                logger.info(f"[Pollinations聊天] 从XML分段下载图片成功，大小: {len(image_content)} 字节")
                except Exception as e:
                    logger.error(f"[Pollinations聊天] XML图片处理失败: {e}")

            # 缓存图片
            if image_content:
                # 缓存到发送者
                self.image_cache[sender_wxid] = {
                    "content": image_content,
                    "timestamp": time.time()
                }
                logger.info(f"[Pollinations聊天] 已缓存用户 {sender_wxid} 的图片")

                # 如果是群聊，也缓存到群ID
                if from_wxid != sender_wxid:
                    self.image_cache[from_wxid] = {
                        "content": image_content,
                        "timestamp": time.time()
                    }
                    logger.info(f"[Pollinations聊天] 已缓存群聊 {from_wxid} 的图片")

                # 保存到文件系统
                try:
                    import hashlib
                    md5 = hashlib.md5(image_content).hexdigest()
                    file_path = os.path.join(self.files_dir, f"{md5}.jpg")
                    with open(file_path, "wb") as f:
                        f.write(image_content)
                    logger.info(f"[Pollinations聊天] 已保存图片到文件: {file_path}")
                except Exception as e:
                    logger.error(f"[Pollinations聊天] 保存图片到文件失败: {e}")
            else:
                logger.warning(f"[Pollinations聊天] 未能获取图片内容，无法缓存")

        except Exception as e:
            logger.error(f"[Pollinations聊天] 处理图片消息失败: {e}")
            logger.error(traceback.format_exc())

        return True

    async def get_cached_image(self, user_wxid: str) -> Optional[bytes]:
        """获取用户最近的图片"""
        logger.debug(f"[Pollinations聊天] 尝试获取用户 {user_wxid} 的缓存图片")
        
        if user_wxid in self.image_cache:
            cache_data = self.image_cache[user_wxid]
            current_time = time.time()
            cache_age = current_time - cache_data["timestamp"]
            
            if cache_age <= self.image_cache_timeout:
                try:
                    image_content = cache_data["content"]
                    if not isinstance(image_content, bytes):
                        logger.error("[Pollinations聊天] 缓存的图片内容不是二进制格式")
                        del self.image_cache[user_wxid]
                        return None

                    # 验证图片数据
                    try:
                        img = Image.open(io.BytesIO(image_content))
                        logger.debug(f"[Pollinations聊天] 缓存图片验证成功，格式: {img.format}, 大小: {len(image_content)} 字节")
                    except Exception as e:
                        logger.error(f"[Pollinations聊天] 缓存的图片数据无效: {e}")
                        del self.image_cache[user_wxid]
                        return None

                    # 更新时间戳
                    self.image_cache[user_wxid]["timestamp"] = current_time
                    return image_content
                except Exception as e:
                    logger.error(f"[Pollinations聊天] 处理缓存图片失败: {e}")
                    del self.image_cache[user_wxid]
                    return None
            else:
                logger.debug(f"[Pollinations聊天] 缓存图片超时，已清除")
                del self.image_cache[user_wxid]
        
        return None
    
    async def find_image_by_md5(self, md5: str) -> Optional[bytes]:
        """根据MD5查找图片文件"""
        if not md5:
            logger.warning("[Pollinations聊天] MD5为空，无法查找图片")
            return None

        # 检查files目录是否存在
        files_dir = os.path.join(os.getcwd(), self.files_dir)
        if not os.path.exists(files_dir):
            logger.warning(f"[Pollinations聊天] files目录不存在: {files_dir}")
            return None

        # 尝试查找不同扩展名的图片文件
        for ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
            file_path = os.path.join(files_dir, f"{md5}.{ext}")
            if os.path.exists(file_path):
                try:
                    # 读取图片文件
                    with open(file_path, "rb") as f:
                        image_data = f.read()
                    logger.info(f"[Pollinations聊天] 根据MD5找到图片文件: {file_path}, 大小: {len(image_data)} 字节")
                    return image_data
                except Exception as e:
                    logger.error(f"[Pollinations聊天] 读取图片文件失败: {e}")

        logger.warning(f"[Pollinations聊天] 未找到MD5为 {md5} 的图片文件")
        return None
    
    async def _handle_role_list(self, bot, message):
        """处理角色列表命令"""
        role_list = "📜 可用角色列表：\n\n"
        for idx, (role_id, role_info) in enumerate(self.roles.items(), 1):
            role_name = role_info.get("name", role_id)
            if role_id == self.current_role:
                role_list += f"▶️ {idx}. {role_name} (当前角色)\n"
            else:
                role_list += f"   {idx}. {role_name}\n"
        
        role_list += "\n切换角色请使用：p切换角色 [角色名称]"
        
        await bot.send_text_message(message["FromWxid"], role_list)
    
    async def _handle_role_switch(self, bot, message, session_id):
        """处理角色切换命令"""
        content = message.get("Content", "")
        prefix = self._check_prefix(content, self.role_switch_prefix)
        if not prefix:
            return
            
        # 提取目标角色名
        target_role_name = self._extract_prompt(content, prefix).strip()
        
        # 如果没有指定角色名
        if not target_role_name:
            # 获取所有角色的中文名称
            role_names = [role_info.get("name", role_id) for role_id, role_info in self.roles.items()]
            await bot.send_text_message(message["FromWxid"], f"请指定要切换的角色名称。\n可用角色: {', '.join(role_names)}\n例如: p切换角色 助手")
            return
        
        # 查找匹配的角色ID
        target_role_id = None
        for role_id, role_info in self.roles.items():
            if role_info.get("name") == target_role_name:
                target_role_id = role_id
                break
        
        # 检查角色是否存在
        if target_role_id is None:
            # 获取所有角色的中文名称
            role_names = [role_info.get("name", role_id) for role_id, role_info in self.roles.items()]
            await bot.send_text_message(message["FromWxid"], f"角色「{target_role_name}」不存在。\n可用角色: {', '.join(role_names)}")
            return
        
        # 如果已经是当前角色
        if target_role_id == self.current_role:
            await bot.send_text_message(message["FromWxid"], f"当前已经是「{target_role_name}」角色了。")
            return
            
        # 保存之前的角色名称
        old_role_name = self.roles.get(self.current_role, {}).get("name", self.current_role)
        
        # 更新当前角色
        self.current_role = target_role_id
        
        # 清除当前会话的历史记录（角色切换后不应保留之前的对话）
        self.session_manager.clear_session(session_id)
        
        await bot.send_text_message(message["FromWxid"], f"已从「{old_role_name}」切换为「{target_role_name}」角色，并清除对话历史。")
    
    def _call_text_api(self, prompt, session):
        """调用文本生成API"""
        # 构建消息历史
        messages = []
        
        # 添加系统提示
        system_content = self._get_system_prompt()
        messages.append({
            "role": "system",
            "content": system_content
        })
        
        # 添加历史消息(如果启用了记忆功能)
        if self.enable_memory and session.messages:
            messages.extend(session.messages)
        else:
            # 如果没有启用记忆，或没有历史消息，直接添加当前提示
            messages.append({
                "role": "user",
                "content": prompt
            })
        
        # 如果启用了记忆但当前用户消息不在历史记录中，添加它
        if self.enable_memory and (not messages[-1]["role"] == "user" or not messages[-1]["content"] == prompt):
            messages.append({
                "role": "user",
                "content": prompt
            })
        
        # 构建API请求数据
        payload = {
            "model": self.api_params.get("model", self.api_model),
            "messages": messages,
            "private": True  # 默认为私有，防止显示在公共源
        }
        
        # 发送请求
        try:
            logger.debug(f"[Pollinations聊天] 发送文本请求: {json.dumps(payload, ensure_ascii=False)}")
            response = requests.post(
                self.openai_api_url,
                headers=self.default_headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                logger.debug(f"[Pollinations聊天] 收到响应: {json.dumps(response_data, ensure_ascii=False)}")
                
                if "choices" in response_data and len(response_data["choices"]) > 0:
                    message = response_data["choices"][0]["message"]
                    if "content" in message:
                        return message["content"]
            
            logger.error(f"[Pollinations聊天] API请求失败: 状态码={response.status_code}, 响应={response.text}")
            error_message = f"⚠️ API请求失败 ⚠️\n\n状态码: {response.status_code}\n响应内容: {response.text[:150]}...\n\n请稍后再试或联系管理员。"
            # 添加错误标记，以便其他方法识别这是错误消息
            return f"[ERROR] {error_message}"
            
        except Exception as e:
            logger.error(f"[Pollinations聊天] API请求异常: {str(e)}")
            error_message = f"❌ API请求出错 ❌\n\n错误信息: {str(e)}\n\n可能原因:\n- 网络连接问题\n- API服务不可用\n- 请求超时\n\n建议稍后再试或联系管理员。"
            # 添加错误标记，以便其他方法识别这是错误消息
            return f"[ERROR] {error_message}"
    
    def _call_voice_api(self, prompt):
        """调用语音生成API"""
        # 构建API请求数据
        payload = {
            "model": "openai-audio",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "voice": self.default_voice,
            "private": True  # 默认为私有，防止显示在公共源
        }
        
        # 发送请求
        try:
            logger.debug(f"[Pollinations聊天] 发送语音请求: {json.dumps(payload, ensure_ascii=False)}")
            response = requests.post(
                self.openai_api_url,
                headers=self.default_headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                # 保存语音文件
                temp_dir = tempfile.gettempdir()
                filename = f"pollinations_voice_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp3"
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, "wb") as f:
                    f.write(response.content)
                
                return filepath
                
            logger.error(f"[Pollinations聊天] 语音API请求失败: 状态码={response.status_code}")
            return None
            
        except Exception as e:
            logger.error(f"[Pollinations聊天] 语音API请求异常: {str(e)}")
            return None
    
    async def _handle_chat(self, bot, message, session_id):
        """处理聊天命令"""
        content = message.get("Content", "")
        prefix = self._check_prefix(content, self.chat_prefix)
        if prefix is None:
            return
            
        # 提取问题
        prompt = self._extract_prompt(content, prefix)
        if not prompt and prefix != "":  # 空前缀情况下不需要检查prompt是否为空
            return
        
        # 如果前缀为空字符串，使用整个内容作为prompt
        if prefix == "":
            prompt = content.strip()
        
        # 检查是否是群聊
        is_group = "IsGroup" in message and message["IsGroup"]
        
        try:
            # 获取会话对象
            session = self.session_manager.get_session(session_id)
            session.max_history = self.max_history  # 设置最大历史记录数
            
            # 添加用户消息到会话历史
            if self.enable_memory:
                session.add_message("user", prompt)
            
            if self.enable_voice:
                # 调用文本API获取回复
                response_text = self._call_text_api(prompt, session)
                
                # 检查是否是错误消息，只有非错误消息才添加到历史记录
                if self.enable_memory and not response_text.startswith("[ERROR]"):
                    session.add_message("assistant", response_text)
                
                # 调用语音API生成语音
                voice_path = self._call_voice_api(response_text)
                
                if voice_path:
                    # 发送语音回复
                    await bot.send_voice_message(message["FromWxid"], voice_path, format="mp3")
                else:
                    # 语音生成失败，发送文本回复
                    if is_group:
                        # 群聊中使用@回复
                        await bot.send_at_message(
                            message["FromWxid"],
                            f"\n{response_text}\n\n[语音生成失败，仅显示文本回复]",
                            [message["SenderWxid"]]
                        )
                    else:
                        # 私聊直接回复
                        await bot.send_text_message(
                            message["FromWxid"],
                            f"{response_text}\n\n[语音生成失败，仅显示文本回复]"
                        )
            else:
                # 调用文本API
                response_text = self._call_text_api(prompt, session)
                
                # 添加AI回复到会话历史
                if self.enable_memory and not response_text.startswith("[ERROR]"):
                    session.add_message("assistant", response_text)
                
                # 发送文本回复
                if is_group:
                    # 群聊中使用@回复
                    await bot.send_at_message(
                        message["FromWxid"],
                        f"\n{response_text}",
                        [message["SenderWxid"]]
                    )
                else:
                    # 私聊直接回复
                    await bot.send_text_message(message["FromWxid"], response_text)
                
        except Exception as e:
            logger.error(f"[Pollinations聊天] 处理聊天命令失败: {e}")
            
            # 发送错误信息
            if is_group:
                # 群聊中使用@回复
                await bot.send_at_message(
                    message["FromWxid"],
                    f"\n处理失败: {str(e)}",
                    [message["SenderWxid"]]
                )
            else:
                # 私聊直接回复
                await bot.send_text_message(message["FromWxid"], f"处理失败: {str(e)}")
    
    async def _handle_voice_toggle(self, bot, message):
        """处理语音开关命令"""
        content = message.get("Content", "")
        prefix = self._check_prefix(content, self.voice_toggle_prefix)
        if not prefix:
            return
            
        # 提取参数
        param = self._extract_prompt(content, prefix).strip().lower()
        
        if param in ["on", "开", "开启", "true", "1"]:
            self.enable_voice = True
            await bot.send_text_message(message["FromWxid"], f"语音回复已开启，当前语音类型: {self.default_voice}")
        elif param in ["off", "关", "关闭", "false", "0"]:
            self.enable_voice = False
            await bot.send_text_message(message["FromWxid"], "语音回复已关闭，将使用文本回复")
        else:
            current_status = "开启" if self.enable_voice else "关闭"
            await bot.send_text_message(message["FromWxid"], f"当前语音回复状态: {current_status}\n\n使用命令开启: p语音开关 开\n使用命令关闭: p语音开关 关")
    
    async def _handle_voice_set(self, bot, message):
        """处理设置语音命令"""
        content = message.get("Content", "")
        prefix = self._check_prefix(content, self.voice_set_prefix)
        if not prefix:
            return
            
        # 提取语音类型
        voice_type = self._extract_prompt(content, prefix).strip().lower()
        
        if not voice_type:
            available_voices = ", ".join(self.available_voices)
            await bot.send_text_message(message["FromWxid"], f"当前语音类型: {self.default_voice}\n\n可用的语音类型: {available_voices}\n\n使用示例: p设置语音 nova")
            return
        
        if voice_type in self.available_voices:
            self.default_voice = voice_type
            await bot.send_text_message(message["FromWxid"], f"语音类型已设置为: {voice_type}")
        else:
            available_voices = ", ".join(self.available_voices)
            await bot.send_text_message(message["FromWxid"], f"无效的语音类型: {voice_type}\n\n可用的语音类型: {available_voices}")
    
    async def _handle_clear_memory(self, bot, message, session_id):
        """处理清除记忆命令"""
        content = message.get("Content", "")
        prefix = self._check_prefix(content, self.clear_memory_prefix)
        if not prefix:
            return
        
        param = self._extract_prompt(content, prefix).strip().lower()
        
        if param == "all" or param == "所有":
            # 清除所有会话的记忆
            self.session_manager.clear_all_sessions()
            await bot.send_text_message(message["FromWxid"], "已清除所有会话记忆")
        else:
            # 清除当前会话的记忆
            self.session_manager.clear_session(session_id)
            await bot.send_text_message(message["FromWxid"], "已清除当前会话记忆")
    
    async def _get_available_models(self):
        """获取可用的模型列表"""
        current_time = time.time()
        
        # 如果缓存有效，直接返回
        if self.available_models and current_time - self.models_last_update < self.models_cache_ttl:
            logger.debug(f"[Pollinations聊天] 使用缓存的模型列表，包含 {len(self.available_models)} 个模型")
            return self.available_models
            
        logger.info("[Pollinations聊天] 缓存失效或不存在，正在请求最新模型列表")
            
        try:
            # 请求模型列表
            logger.debug(f"[Pollinations聊天] 发起GET请求: {self.text_models_url}")
            response = requests.get(
                self.text_models_url,
                headers=self.default_headers,
                timeout=30  # 增加超时时间
            )
            
            if response.status_code == 200:
                try:
                    # 尝试解析JSON
                    models_data = response.json()
                    if not isinstance(models_data, list):
                        logger.error(f"[Pollinations聊天] 模型数据格式不正确，预期列表，实际: {type(models_data)}")
                        return self.available_models or []  # 返回缓存或空列表
                        
                    # 更新缓存
                    self.available_models = models_data
                    self.models_last_update = current_time
                    logger.info(f"[Pollinations聊天] 成功获取 {len(models_data)} 个模型信息并更新缓存")
                    return self.available_models
                except json.JSONDecodeError as e:
                    logger.error(f"[Pollinations聊天] 解析模型列表JSON失败: {str(e)}")
                    logger.debug(f"[Pollinations聊天] 响应内容: {response.text[:200]}...")
                    return self.available_models or []  # 返回缓存或空列表
            else:
                logger.error(f"[Pollinations聊天] 获取模型列表失败: 状态码={response.status_code}, 响应={response.text[:200]}...")
                return self.available_models or []  # 返回缓存或空列表
                
        except requests.RequestException as e:
            logger.error(f"[Pollinations聊天] 请求模型列表异常: {str(e)}")
            return self.available_models or []  # 返回缓存或空列表
        except Exception as e:
            logger.error(f"[Pollinations聊天] 获取模型列表时发生未知错误: {str(e)}", exc_info=True)
            return self.available_models or []  # 返回缓存或空列表
    
    async def _handle_model_list(self, bot, message):
        """处理模型列表命令"""
        try:
            logger.info("[Pollinations聊天] 开始处理模型列表命令")
            
            # 添加直接响应，让用户知道命令已收到
            await bot.send_text_message(message["FromWxid"], "正在获取模型列表，请稍候...")
            
            # 获取可用模型
            logger.debug(f"[Pollinations聊天] 请求获取模型列表，URL: {self.text_models_url}")
            models = await self._get_available_models()
            
            if not models:
                logger.warning("[Pollinations聊天] 获取模型列表失败，返回空列表")
                await bot.send_text_message(message["FromWxid"], "获取模型列表失败，请稍后再试。")
                return
            
            logger.debug(f"[Pollinations聊天] 成功获取 {len(models)} 个模型信息")
                
            # 构建回复消息
            reply = "📋 可用模型列表：\n\n"
            
            # 在列表开头添加当前使用的模型信息
            reply += f"🔹 当前使用的模型：{self.api_model}\n\n"
            
            for idx, model in enumerate(models, 1):
                model_name = model.get("name", "")
                description = model.get("description", "")
                provider = model.get("provider", "")
                input_modalities = ", ".join(model.get("input_modalities", []))
                output_modalities = ", ".join(model.get("output_modalities", []))
                
                # 标记当前使用的模型
                current_mark = "▶️ " if model_name == self.api_model else "   "
                
                # 构建模型信息
                model_info = f"{current_mark}{idx}. {model_name}"
                if description:
                    model_info += f"\n     描述: {description}"
                if provider:
                    model_info += f"\n     提供商: {provider}"
                
                # 模型能力
                capabilities = []
                if model.get("tools"):
                    capabilities.append("工具调用")
                if model.get("vision"):
                    capabilities.append("视觉")
                if model.get("audio"):
                    capabilities.append("音频")
                if model.get("uncensored"):
                    capabilities.append("无限制")
                if model.get("reasoning"):
                    capabilities.append("推理")
                
                if capabilities:
                    model_info += f"\n     能力: {', '.join(capabilities)}"
                
                if input_modalities:
                    model_info += f"\n     输入: {input_modalities}"
                if output_modalities:
                    model_info += f"\n     输出: {output_modalities}"
                
                reply += f"{model_info}\n\n"
            
            reply += "切换模型请使用：p切换模型 [模型名称]"
            
            logger.debug(f"[Pollinations聊天] 发送模型列表响应，长度: {len(reply)}")
            await bot.send_text_message(message["FromWxid"], reply)
            logger.info("[Pollinations聊天] 模型列表命令处理完成")
            
        except Exception as e:
            logger.error(f"[Pollinations聊天] 处理模型列表命令失败: {str(e)}", exc_info=True)
            await bot.send_text_message(message["FromWxid"], f"处理模型列表命令失败: {str(e)}")
    
    async def _handle_model_switch(self, bot, message):
        """处理模型切换命令"""
        try:
            logger.info("[Pollinations聊天] 开始处理模型切换命令")
            content = message.get("Content", "")
            logger.debug(f"[Pollinations聊天] 接收到的内容: '{content}'")
            
            prefix = self._check_prefix(content, self.model_switch_prefix)
            logger.debug(f"[Pollinations聊天] 检测到的前缀: '{prefix}'")
            
            if not prefix:
                logger.warning("[Pollinations聊天] 未检测到有效前缀，退出处理")
                return
                
            # 提取目标模型名称
            target_model_name = self._extract_prompt(content, prefix).strip()
            logger.debug(f"[Pollinations聊天] 提取的目标模型名称: '{target_model_name}'")
            
            # 如果没有指定模型名称
            if not target_model_name:
                logger.info("[Pollinations聊天] 未指定模型名称，发送提示信息")
                await bot.send_text_message(message["FromWxid"], "请指定要切换的模型名称。\n例如: p切换模型 openai\n\n可以使用命令：p模型列表 查看所有可用模型")
                return
            
            # 添加直接响应，让用户知道命令已收到
            await bot.send_text_message(message["FromWxid"], f"正在切换至模型: {target_model_name}，请稍候...")
            
            # 获取可用模型列表
            logger.debug("[Pollinations聊天] 获取可用模型列表")
            models = await self._get_available_models()
            
            if not models:
                logger.warning("[Pollinations聊天] 获取模型列表失败，返回空列表")
                await bot.send_text_message(message["FromWxid"], "获取模型列表失败，无法切换模型。请稍后再试。")
                return
            
            logger.debug(f"[Pollinations聊天] 成功获取 {len(models)} 个模型信息")
            
            # 查找目标模型是否存在
            target_model = None
            for model in models:
                if model.get("name") == target_model_name:
                    target_model = model
                    logger.debug(f"[Pollinations聊天] 找到匹配的模型: {target_model_name}")
                    break
                    
            # 检查模型是否可用
            if target_model is None:
                logger.warning(f"[Pollinations聊天] 未找到匹配的模型: {target_model_name}")
                model_names = [model.get("name") for model in models]
                await bot.send_text_message(message["FromWxid"], f"模型「{target_model_name}」不存在或不可用。\n\n可用模型: {', '.join(model_names[:10])}...\n\n使用命令：p模型列表 查看所有可用模型")
                return
            
            # 如果已经是当前模型
            if target_model_name == self.api_model:
                logger.info(f"[Pollinations聊天] 已经在使用该模型: {target_model_name}")
                await bot.send_text_message(message["FromWxid"], f"当前已经在使用「{target_model_name}」模型了。")
                return
                
            # 更新当前模型
            old_model_name = self.api_model
            logger.info(f"[Pollinations聊天] 从 {old_model_name} 切换至 {target_model_name}")
            self.api_model = target_model_name
            self.api_params["model"] = target_model_name
            
            # 构建模型能力说明
            capabilities = []
            if target_model.get("tools"):
                capabilities.append("工具调用")
            if target_model.get("vision"):
                capabilities.append("视觉")
            if target_model.get("audio"):
                capabilities.append("音频")
            if target_model.get("uncensored"):
                capabilities.append("无限制")
            if target_model.get("reasoning"):
                capabilities.append("推理")
            
            capabilities_text = f"支持能力: {', '.join(capabilities)}" if capabilities else ""
            input_modalities = ", ".join(target_model.get("input_modalities", []))
            output_modalities = ", ".join(target_model.get("output_modalities", []))
            
            # 构建回复消息
            reply = f"已从「{old_model_name}」切换为「{target_model_name}」模型。\n"
            reply += f"描述: {target_model.get('description', '')}\n"
            if capabilities_text:
                reply += f"{capabilities_text}\n"
            reply += f"输入模态: {input_modalities}\n"
            reply += f"输出模态: {output_modalities}"
            
            logger.debug(f"[Pollinations聊天] 发送模型切换响应，长度: {len(reply)}")
            await bot.send_text_message(message["FromWxid"], reply)
            logger.info("[Pollinations聊天] 模型切换命令处理完成")
            
        except Exception as e:
            logger.error(f"[Pollinations聊天] 处理模型切换命令失败: {str(e)}", exc_info=True)
            await bot.send_text_message(message["FromWxid"], f"处理模型切换命令失败: {str(e)}")
    
    @on_quote_message(priority=50)
    async def handle_quote(self, bot: WechatAPIClient, message: dict):
        """处理引用消息，支持图片识别"""
        if not self.enable:
            logger.debug("[Pollinations聊天] 插件未启用")
            return True  # 插件未启用，允许其他插件处理

        # 检查消息是否已经处理过
        if self.is_message_processed(message):
            logger.info(f"[Pollinations聊天] 消息 {message.get('MsgId') or message.get('NewMsgId')} 已经处理过，跳过")
            return False  # 消息已处理，阻止后续插件处理

        # 标记消息为已处理
        self.mark_message_processed(message)

        # 提取引用消息的内容
        content = message.get("Content", "").strip()
        quote_info = message.get("Quote", {})
        quoted_content = quote_info.get("Content", "")
        quoted_sender = quote_info.get("Nickname", "")

        logger.info(f"[Pollinations聊天] 处理引用消息: 内容={content}, 引用内容={quoted_content}, 引用发送者={quoted_sender}")
        
        # 检查是否是群聊
        is_group = "IsGroup" in message and message["IsGroup"]
        
        # 检查群聊中是否包含@机器人，如果是群聊但没有@机器人，则跳过处理
        if is_group and not self._is_at_robot(message):
            logger.debug("[Pollinations聊天] 群聊引用消息未@机器人，跳过处理")
            return True
        
        # 检查是否是插件命令
        is_cmd = self._is_command(content)
        logger.debug(f"[Pollinations聊天] 是否是命令: {is_cmd}")
        
        # 检查引用的消息是否包含图片
        image_md5 = None
        
        # 检查消息类型
        if quote_info.get("MsgType") == 3:  # 图片消息
            import xml.etree.ElementTree as ET
            try:
                # 尝试从引用的图片消息中提取MD5
                if "<?xml" in quoted_content and "<img" in quoted_content:
                    root = ET.fromstring(quoted_content)
                    img_element = root.find('img')
                    if img_element is not None:
                        image_md5 = img_element.get('md5')
                        logger.info(f"[Pollinations聊天] 从引用的图片消息中提取到MD5: {image_md5}")
            except Exception as e:
                logger.error(f"[Pollinations聊天] 解析引用图片消息XML失败: {e}")

        # 处理命令
        # 检查是否是聊天命令
        prefix = self._check_prefix(content, self.chat_prefix)
        if prefix is not None:
            # 提取提示词
            prompt = self._extract_prompt(content, prefix)
            if not prompt and prefix != "":  # 空前缀情况下不需要检查prompt是否为空
                return True
                
            # 如果前缀为空字符串，使用整个内容作为prompt
            if prefix == "":
                prompt = content.strip()
                
            # 添加引用内容到提示词
            if quoted_content:
                if prompt:
                    prompt = f"{prompt} (引用内容: {quoted_content})"
                else:
                    prompt = f"请回复这条消息: '{quoted_content}'"
                    
            # 准备处理图片
            has_image = False
            image_content = None
            
            # 优先使用引用消息中的图片MD5
            if image_md5:
                try:
                    logger.info(f"[Pollinations聊天] 尝试根据MD5查找图片: {image_md5}")
                    image_content = await self.find_image_by_md5(image_md5)
                    if image_content:
                        logger.info(f"[Pollinations聊天] 根据MD5找到图片，大小: {len(image_content)} 字节")
                        has_image = True
                    else:
                        logger.warning(f"[Pollinations聊天] 未找到MD5为 {image_md5} 的图片")
                except Exception as e:
                    logger.error(f"[Pollinations聊天] 处理引用图片失败: {e}")
                    
            # 如果没有找到图片，尝试从缓存获取
            if not has_image:
                # 从发送者或群聊ID获取缓存图片
                sender_wxid = message.get("SenderWxid", message.get("FromWxid"))
                from_wxid = message.get("FromWxid")
                
                # 先尝试从发送者获取图片
                image_content = await self.get_cached_image(sender_wxid)
                if not image_content and from_wxid != sender_wxid:
                    # 再尝试从群聊获取图片
                    image_content = await self.get_cached_image(from_wxid)
                    
                if image_content:
                    logger.info(f"[Pollinations聊天] 从缓存中获取到图片，大小: {len(image_content)} 字节")
                    has_image = True
            
            # 获取会话对象
            session = self.session_manager.get_session(self._get_session_id(message))
            session.max_history = self.max_history
            
            # 添加用户消息到会话历史
            if self.enable_memory:
                if has_image:
                    # 如果有图片，添加提示词有图片信息
                    session.add_message("user", f"{prompt} [包含一张图片]")
                else:
                    session.add_message("user", prompt)
            
            # 如果有图片，需要处理提示词
            if has_image:
                from_base64 = None
                import base64
                try:
                    # 转换图片为base64
                    image_base64 = base64.b64encode(image_content).decode('utf-8')
                    from_base64 = f"data:image/jpeg;base64,{image_base64}"
                    
                    # 构建带图片的消息
                    modified_prompt = {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": from_base64}}
                        ]
                    }
                    
                    # 构建请求数据
                    system_content = self._get_system_prompt()
                    messages = [{"role": "system", "content": system_content}]
                    
                    # 引用图片消息时不添加历史消息，只添加当前带图片的消息
                    logger.info(f"[Pollinations聊天] 引用图片消息处理：不添加历史消息，确保图片分析更精准")
                    messages.append(modified_prompt)
                    
                    # 构建API请求数据
                    payload = {
                        "model": self.api_params.get("model", self.api_model),
                        "messages": messages,
                        "private": True  # 默认为私有
                    }
                    
                    # 发送请求
                    logger.debug(f"[Pollinations聊天] 发送带图片的请求，图片大小: {len(image_content)} 字节")
                    response = requests.post(
                        self.openai_api_url,
                        headers=self.default_headers,
                        json=payload,
                        timeout=60  # 图片处理需要更长时间
                    )
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        logger.debug(f"[Pollinations聊天] 收到响应: {json.dumps(response_data, ensure_ascii=False)}")
                        
                        if "choices" in response_data and len(response_data["choices"]) > 0:
                            message_obj = response_data["choices"][0]["message"]
                            if "content" in message_obj:
                                response_text = message_obj["content"]
                                
                                # 添加AI回复到会话历史
                                if self.enable_memory and not response_text.startswith("[ERROR]"):
                                    session.add_message("assistant", response_text)
                                
                                # 处理语音回复
                                if self.enable_voice:
                                    # 调用语音API生成语音
                                    voice_path = self._call_voice_api(response_text)
                                    
                                    if voice_path:
                                        # 发送语音回复
                                        await bot.send_voice_message(message["FromWxid"], voice_path, format="mp3")
                                    else:
                                        # 语音生成失败，发送文本回复
                                        if is_group:
                                            # 群聊中使用@回复
                                            await bot.send_at_message(
                                                message["FromWxid"],
                                                f"\n{response_text}\n\n[语音生成失败，仅显示文本回复]",
                                                [message["SenderWxid"]]
                                            )
                                        else:
                                            # 私聊直接回复
                                            await bot.send_text_message(
                                                message["FromWxid"],
                                                f"{response_text}\n\n[语音生成失败，仅显示文本回复]"
                                            )
                                else:
                                    # 发送文本回复
                                    if is_group:
                                        # 群聊中使用@回复
                                        await bot.send_at_message(
                                            message["FromWxid"],
                                            f"\n{response_text}",
                                            [message["SenderWxid"]]
                                        )
                                    else:
                                        # 私聊直接回复
                                        await bot.send_text_message(message["FromWxid"], response_text)
                                    
                                return False  # 阻止后续插件处理
                except Exception as e:
                    logger.error(f"[Pollinations聊天] 处理带图片的请求失败: {e}")
                    await bot.send_text_message(message["FromWxid"], f"处理带图片的请求失败: {str(e)}")
                    return False  # 阻止后续插件处理
            
            # 如果没有图片或图片处理失败，使用常规文本API
            try:
                # 调用文本API
                response_text = self._call_text_api(prompt, session)
                
                # 添加AI回复到会话历史
                if self.enable_memory and not response_text.startswith("[ERROR]"):
                    session.add_message("assistant", response_text)
                
                # 处理语音回复
                if self.enable_voice:
                    # 调用语音API生成语音
                    voice_path = self._call_voice_api(response_text)
                    
                    if voice_path:
                        # 发送语音回复
                        await bot.send_voice_message(message["FromWxid"], voice_path, format="mp3")
                    else:
                        # 语音生成失败，发送文本回复
                        if is_group:
                            # 群聊中使用@回复
                            await bot.send_at_message(
                                message["FromWxid"],
                                f"\n{response_text}\n\n[语音生成失败，仅显示文本回复]",
                                [message["SenderWxid"]]
                            )
                        else:
                            # 私聊直接回复
                            await bot.send_text_message(
                                message["FromWxid"],
                                f"{response_text}\n\n[语音生成失败，仅显示文本回复]"
                            )
                else:
                    # 发送文本回复
                    if is_group:
                        # 群聊中使用@回复
                        await bot.send_at_message(
                            message["FromWxid"],
                            f"\n{response_text}",
                            [message["SenderWxid"]]
                        )
                    else:
                        # 私聊直接回复
                        await bot.send_text_message(message["FromWxid"], response_text)
                    
                return False  # 阻止后续插件处理
            except Exception as e:
                logger.error(f"[Pollinations聊天] 处理引用消息失败: {e}")
                
                # 发送错误信息
                if is_group:
                    # 群聊中使用@回复
                    await bot.send_at_message(
                        message["FromWxid"],
                        f"\n处理失败: {str(e)}",
                        [message["SenderWxid"]]
                    )
                else:
                    # 私聊直接回复
                    await bot.send_text_message(message["FromWxid"], f"处理失败: {str(e)}")
                
                return False  # 阻止后续插件处理
        
        # 处理其他命令
        elif self._check_prefix(content, self.role_list_prefix):
            await self._handle_role_list(bot, message)
            return False
        elif self._check_prefix(content, self.role_switch_prefix):
            await self._handle_role_switch(bot, message, self._get_session_id(message))
            return False
        elif self._check_prefix(content, self.model_list_prefix):
            await self._handle_model_list(bot, message)
            return False
        elif self._check_prefix(content, self.model_switch_prefix):
            await self._handle_model_switch(bot, message)
            return False
        elif self._check_prefix(content, self.clear_memory_prefix):
            await self._handle_clear_memory(bot, message, self._get_session_id(message))
            return False
        elif self._check_prefix(content, self.voice_toggle_prefix):
            await self._handle_voice_toggle(bot, message)
            return False
        elif self._check_prefix(content, self.voice_set_prefix):
            await self._handle_voice_set(bot, message)
            return False
        
        return True  # 非匹配命令，允许其他插件处理
        
    @on_at_message(priority=50)
    async def handle_at(self, bot: WechatAPIClient, message: dict):
        """处理@消息"""
        if not self.enable:
            logger.debug("[Pollinations聊天] 插件未启用")
            return True  # 插件未启用，允许其他插件处理
        
        # 检查消息是否已经处理过
        if self.is_message_processed(message):
            logger.info(f"[Pollinations聊天] 消息 {message.get('MsgId') or message.get('NewMsgId')} 已经处理过，跳过")
            return False  # 消息已处理，阻止后续插件处理

        # 标记消息为已处理
        self.mark_message_processed(message)
        
        # 提取消息内容
        content = message.get("Content", "").strip()
        logger.info(f"[Pollinations聊天] 处理@消息: {content}")
        
        # 获取会话ID
        session_id = self._get_session_id(message)
        
        # 尝试移除@机器人部分
        cleaned_content = content
        for robot_name in self.robot_names:
            cleaned_content = cleaned_content.replace(f"@{robot_name}", "").strip()
        
        # 如果完全移除后没有内容，使用默认提示
        if not cleaned_content:
            cleaned_content = "你好"
        
        logger.debug(f"[Pollinations聊天] 移除@后的内容: {cleaned_content}")
        
        # 检查是否是命令
        is_cmd = self._is_command(cleaned_content)
        if is_cmd:
            # 处理角色列表命令
            if self._check_prefix(cleaned_content, self.role_list_prefix):
                await self._handle_role_list(bot, message)
                return False
            # 处理角色切换命令
            elif self._check_prefix(cleaned_content, self.role_switch_prefix):
                await self._handle_role_switch(bot, message, session_id)
                return False
            # 处理模型列表命令
            elif self._check_prefix(cleaned_content, self.model_list_prefix):
                await self._handle_model_list(bot, message)
                return False
            # 处理模型切换命令
            elif self._check_prefix(cleaned_content, self.model_switch_prefix):
                await self._handle_model_switch(bot, message)
                return False
            # 处理清除记忆命令
            elif self._check_prefix(cleaned_content, self.clear_memory_prefix):
                await self._handle_clear_memory(bot, message, session_id)
                return False
            # 处理语音开关命令
            elif self._check_prefix(cleaned_content, self.voice_toggle_prefix):
                await self._handle_voice_toggle(bot, message)
                return False
            # 处理设置语音命令
            elif self._check_prefix(cleaned_content, self.voice_set_prefix):
                await self._handle_voice_set(bot, message)
                return False
        
        try:
            # 获取会话对象
            session = self.session_manager.get_session(session_id)
            session.max_history = self.max_history
            
            # 添加用户消息到会话历史
            if self.enable_memory:
                session.add_message("user", cleaned_content)
            
            # 检查是否是群聊
            is_group = "IsGroup" in message and message["IsGroup"]
            
            # 处理回复
            if self.enable_voice:
                # 调用文本API获取回复
                response_text = self._call_text_api(cleaned_content, session)
                
                # 添加AI回复到会话历史
                if self.enable_memory and not response_text.startswith("[ERROR]"):
                    session.add_message("assistant", response_text)
                
                # 调用语音API生成语音
                voice_path = self._call_voice_api(response_text)
                
                if voice_path:
                    # 发送语音回复
                    await bot.send_voice_message(message["FromWxid"], voice_path, format="mp3")
                else:
                    # 语音生成失败，发送文本回复
                    if is_group:
                        # 群聊中使用@回复
                        await bot.send_at_message(
                            message["FromWxid"],
                            f"\n{response_text}\n\n[语音生成失败，仅显示文本回复]",
                            [message["SenderWxid"]]
                        )
                    else:
                        # 私聊直接回复
                        await bot.send_text_message(
                            message["FromWxid"],
                            f"{response_text}\n\n[语音生成失败，仅显示文本回复]"
                        )
            else:
                # 调用文本API
                response_text = self._call_text_api(cleaned_content, session)
                
                # 添加AI回复到会话历史
                if self.enable_memory and not response_text.startswith("[ERROR]"):
                    session.add_message("assistant", response_text)
                
                # 发送文本回复
                if is_group:
                    # 群聊中使用@回复
                    await bot.send_at_message(
                        message["FromWxid"],
                        f"\n{response_text}",
                        [message["SenderWxid"]]
                    )
                else:
                    # 私聊直接回复
                    await bot.send_text_message(message["FromWxid"], response_text)
            
            return False  # 阻止后续插件处理
            
        except Exception as e:
            logger.error(f"[Pollinations聊天] 处理@消息失败: {e}")
            
            # 发送错误信息
            if is_group:
                # 群聊中使用@回复
                await bot.send_at_message(
                    message["FromWxid"],
                    f"\n处理失败: {str(e)}",
                    [message["SenderWxid"]]
                )
            else:
                # 私聊直接回复
                await bot.send_text_message(message["FromWxid"], f"处理失败: {str(e)}")
            
            return False  # 阻止后续插件处理 