from loguru import logger
import os
import tomllib
from utils.plugin_base import PluginBase
from utils.decorators import on_text_message, on_image_message, on_file_message, on_video_message
import json


class ToolMsgForwarder(PluginBase):
    description = "消息转发插件，可根据配置转发指定来源的文本、图片、文件、视频消息到指定目标(支持多目标和群内指定人)。需要手动配置才能使用，无默认配置。"
    author = "ai"
    version = "0.5.0"  # 添加消息处理钩子系统，支持消息的二次处理

    def __init__(self):
        super().__init__()
        self.plugin_config = {}
        self.enable = True  # 默认启用
        self.text_rules = []
        self.image_rules = []
        self.file_rules = []
        self.video_rules = []
        # 新增：消息处理钩子
        self.msg_processors = {
            "before_match": [],    # 规则匹配前处理器
            "after_match": [],     # 规则匹配后处理器
            "before_forward": [],  # 转发前处理器
            "after_forward": []    # 转发后处理器
        }
        logger.info(f"[ToolMsgForwarder] 插件初始化")
        self._load_config()
        
        # 尝试加载JD转链功能
        self._init_jd_converter()

    def _load_config(self):
        """从 config.toml 加载配置"""
        plugin_name = self.__class__.__name__
        config_path = f"plugins/{plugin_name}/config.toml"

        try:
            # 尝试使用标准TOML加载器
            with open(config_path, "rb") as f:
                toml_data = tomllib.load(f)

            # 读取插件配置
            if plugin_name not in toml_data:
                logger.warning(f"[ToolMsgForwarder] 配置文件 {config_path} 中未找到 [{plugin_name}] 配置部分")
                logger.error(f"[ToolMsgForwarder] 插件将被禁用，请正确配置后重启")
                self._disable_plugin()
                return

            config = toml_data[plugin_name]
            self.plugin_config = config
            logger.debug(f"[ToolMsgForwarder] 已读取配置: {list(config.keys())}")

            # 加载插件状态
            self.enable = config.get("enable", True)
            logger.debug(f"[ToolMsgForwarder] 插件状态: {'启用' if self.enable else '禁用'}")
            
            # 检查是否使用表格数组格式
            if f"{plugin_name}.text_rules" in toml_data:
                logger.info(f"[ToolMsgForwarder] 检测到表格数组配置格式")
                self._load_table_array_config(toml_data)
            # 检查是否使用扁平化配置
            elif "text_rule_enabled" in config:
                logger.info(f"[ToolMsgForwarder] 检测到扁平化配置格式")
                self._convert_flat_config(config)
            else:
                # 使用传统嵌套格式
                logger.info(f"[ToolMsgForwarder] 使用传统嵌套格式")
                # 加载各类消息规则
                self.text_rules = config.get("text_rules", [])
                self.image_rules = config.get("image_rules", [])
                self.file_rules = config.get("file_rules", [])
                self.video_rules = config.get("video_rules", [])
            
            # 记录规则数量
            logger.info(f"[ToolMsgForwarder] 已加载转发规则: 文本({len(self.text_rules)}), 图片({len(self.image_rules)}), "
                        f"文件({len(self.file_rules)}), 视频({len(self.video_rules)})")
            
            # 检查并打印规则详情（调试用）
            self._log_rules_details()
            
            # 每次重载配置时都加载SecondProcessor
            self._load_second_processor()

        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 加载配置文件 {config_path} 时发生错误: {e}")
            return

    def _log_rules_details(self):
        """记录所有规则的详细信息"""
        for rule_type, rules in [
            ("文本", self.text_rules), 
            ("图片", self.image_rules),
            ("文件", self.file_rules),
            ("视频", self.video_rules)
        ]:
            for i, rule in enumerate(rules):
                if rule.get("enabled", False):
                    from_wxid = rule.get("from_wxid", "未指定")
                    from_name = rule.get("name", from_wxid)  # 获取别名
                    to_wxids = rule.get("to_wxids", [])
                    specific_senders = rule.get("listen_specific_senders_in_group", [])
                    
                    # 获取发送者别名
                    sender_names = rule.get("sender_names", {})
                    sender_names_info = ""
                    if sender_names and specific_senders:
                        sender_names_list = [f"{wxid}({sender_names.get(wxid, '无别名')})" for wxid in specific_senders if wxid in sender_names]
                        if sender_names_list:
                            sender_names_info = f", 别名: {', '.join(sender_names_list)}"
                    
                    sender_info = f"(监听群内特定用户: {len(specific_senders)}人{sender_names_info})" if specific_senders else ""
                    logger.debug(f"[ToolMsgForwarder] {rule_type}规则 #{i+1}: 来源 {from_wxid}(别名:{from_name}) {sender_info} -> 转发到 {len(to_wxids)} 个目标")

    def _load_table_array_config(self, toml_data):
        """加载表格数组格式配置"""
        plugin_name = self.__class__.__name__
        try:
            # 读取各类规则
            self.text_rules = toml_data.get(f"{plugin_name}.text_rules", [])
            self.image_rules = toml_data.get(f"{plugin_name}.image_rules", [])
            self.file_rules = toml_data.get(f"{plugin_name}.file_rules", [])
            self.video_rules = toml_data.get(f"{plugin_name}.video_rules", [])
            
            # 规则统计
            text_enabled = sum(1 for rule in self.text_rules if rule.get("enabled", False))
            image_enabled = sum(1 for rule in self.image_rules if rule.get("enabled", False))
            file_enabled = sum(1 for rule in self.file_rules if rule.get("enabled", False))
            video_enabled = sum(1 for rule in self.video_rules if rule.get("enabled", False))
            
            logger.debug(f"[ToolMsgForwarder] 表格数组配置加载完成: "
                         f"文本规则({text_enabled}/{len(self.text_rules)}启用), "
                         f"图片规则({image_enabled}/{len(self.image_rules)}启用), "
                         f"文件规则({file_enabled}/{len(self.file_rules)}启用), "
                         f"视频规则({video_enabled}/{len(self.video_rules)}启用)")
            
            # 更新插件配置
            self.plugin_config["text_rules"] = self.text_rules
            self.plugin_config["image_rules"] = self.image_rules
            self.plugin_config["file_rules"] = self.file_rules
            self.plugin_config["video_rules"] = self.video_rules
            
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 加载表格数组配置失败: {e}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
            self._disable_plugin()

    def _convert_flat_config(self, config):
        """将扁平化配置转换为嵌套格式"""
        try:
            # 扁平化配置 -> 嵌套格式
            # 处理文本规则
            self.text_rules = []
            self.image_rules = []
            self.file_rules = []
            self.video_rules = []
            
            # 查找所有规则前缀
            text_rule_prefixes = set()
            image_rule_prefixes = set()
            file_rule_prefixes = set()
            video_rule_prefixes = set()
            
            for key in config.keys():
                if key.startswith("text_rule") and key.endswith("_enabled"):
                    prefix = key[:-8]  # 去掉"_enabled"
                    text_rule_prefixes.add(prefix)
                elif key.startswith("image_rule") and key.endswith("_enabled"):
                    prefix = key[:-8]
                    image_rule_prefixes.add(prefix)
                elif key.startswith("file_rule") and key.endswith("_enabled"):
                    prefix = key[:-8]
                    file_rule_prefixes.add(prefix)
                elif key.startswith("video_rule") and key.endswith("_enabled"):
                    prefix = key[:-8]
                    video_rule_prefixes.add(prefix)
            
            logger.debug(f"[ToolMsgForwarder] 找到规则前缀: 文本{len(text_rule_prefixes)}个, 图片{len(image_rule_prefixes)}个, "
                         f"文件{len(file_rule_prefixes)}个, 视频{len(video_rule_prefixes)}个")
            
            # 处理文本规则
            for prefix in text_rule_prefixes:
                if config.get(f"{prefix}_enabled", False):
                    # 提取配置并处理数组格式
                    text_rule = {
                        "enabled": config.get(f"{prefix}_enabled", True),
                        "from_wxid": config.get(f"{prefix}_from_wxid", ""),
                        "listen_specific_senders_in_group": config.get(f"{prefix}_listen_users", []),
                        "to_wxids": config.get(f"{prefix}_to_wxids", []),
                        "prepend_info": config.get(f"{prefix}_prepend_info", True)
                    }
                    
                    # 如果数组格式是内部嵌套的(双括号)，则需要提取内层
                    if text_rule["listen_specific_senders_in_group"] and isinstance(text_rule["listen_specific_senders_in_group"][0], list):
                        text_rule["listen_specific_senders_in_group"] = text_rule["listen_specific_senders_in_group"][0]
                        
                    if text_rule["to_wxids"] and isinstance(text_rule["to_wxids"][0], list):
                        text_rule["to_wxids"] = text_rule["to_wxids"][0]
                    
                    self.text_rules.append(text_rule)
                    logger.debug(f"[ToolMsgForwarder] 已加载文本规则 {prefix}: 监听{text_rule['from_wxid']}, "
                                 f"转发给{len(text_rule['to_wxids'])}个目标")
            
            # 处理图片规则
            for prefix in image_rule_prefixes:
                if config.get(f"{prefix}_enabled", False):
                    image_rule = {
                        "enabled": config.get(f"{prefix}_enabled", True),
                        "from_wxid": config.get(f"{prefix}_from_wxid", ""),
                        "listen_specific_senders_in_group": config.get(f"{prefix}_listen_users", []),
                        "to_wxids": config.get(f"{prefix}_to_wxids", []),
                        "prepend_info": config.get(f"{prefix}_prepend_info", True)
                    }
                    
                    # 处理双括号格式
                    if image_rule["listen_specific_senders_in_group"] and isinstance(image_rule["listen_specific_senders_in_group"][0], list):
                        image_rule["listen_specific_senders_in_group"] = image_rule["listen_specific_senders_in_group"][0]
                        
                    if image_rule["to_wxids"] and isinstance(image_rule["to_wxids"][0], list):
                        image_rule["to_wxids"] = image_rule["to_wxids"][0]
                    
                    self.image_rules.append(image_rule)
                    logger.debug(f"[ToolMsgForwarder] 已加载图片规则 {prefix}: 监听{image_rule['from_wxid']}, "
                                 f"转发给{len(image_rule['to_wxids'])}个目标")
            
            # 处理文件规则
            for prefix in file_rule_prefixes:
                if config.get(f"{prefix}_enabled", False):
                    file_rule = {
                        "enabled": config.get(f"{prefix}_enabled", True),
                        "from_wxid": config.get(f"{prefix}_from_wxid", ""),
                        "listen_specific_senders_in_group": config.get(f"{prefix}_listen_users", []),
                        "to_wxids": config.get(f"{prefix}_to_wxids", []),
                        "prepend_info": config.get(f"{prefix}_prepend_info", True)
                    }
                    
                    # 处理双括号格式
                    if file_rule["listen_specific_senders_in_group"] and isinstance(file_rule["listen_specific_senders_in_group"][0], list):
                        file_rule["listen_specific_senders_in_group"] = file_rule["listen_specific_senders_in_group"][0]
                        
                    if file_rule["to_wxids"] and isinstance(file_rule["to_wxids"][0], list):
                        file_rule["to_wxids"] = file_rule["to_wxids"][0]
                    
                    self.file_rules.append(file_rule)
                    logger.debug(f"[ToolMsgForwarder] 已加载文件规则 {prefix}: 监听{file_rule['from_wxid']}, "
                                 f"转发给{len(file_rule['to_wxids'])}个目标")
            
            # 处理视频规则
            for prefix in video_rule_prefixes:
                if config.get(f"{prefix}_enabled", False):
                    video_rule = {
                        "enabled": config.get(f"{prefix}_enabled", True),
                        "from_wxid": config.get(f"{prefix}_from_wxid", ""),
                        "listen_specific_senders_in_group": config.get(f"{prefix}_listen_users", []),
                        "to_wxids": config.get(f"{prefix}_to_wxids", []),
                        "prepend_info": config.get(f"{prefix}_prepend_info", True)
                    }
                    
                    # 处理双括号格式
                    if video_rule["listen_specific_senders_in_group"] and isinstance(video_rule["listen_specific_senders_in_group"][0], list):
                        video_rule["listen_specific_senders_in_group"] = video_rule["listen_specific_senders_in_group"][0]
                        
                    if video_rule["to_wxids"] and isinstance(video_rule["to_wxids"][0], list):
                        video_rule["to_wxids"] = video_rule["to_wxids"][0]
                    
                    self.video_rules.append(video_rule)
                    logger.debug(f"[ToolMsgForwarder] 已加载视频规则 {prefix}: 监听{video_rule['from_wxid']}, "
                                 f"转发给{len(video_rule['to_wxids'])}个目标")
            
            # 更新插件配置
            self.plugin_config["text_rules"] = self.text_rules
            self.plugin_config["image_rules"] = self.image_rules
            self.plugin_config["file_rules"] = self.file_rules
            self.plugin_config["video_rules"] = self.video_rules
            
            # 记录规则数量统计
            logger.info(f"[ToolMsgForwarder] 扁平化配置转换完成: 文本({len(self.text_rules)}), "
                        f"图片({len(self.image_rules)}), 文件({len(self.file_rules)}), 视频({len(self.video_rules)})")
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 扁平化配置转换失败: {e}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
            self._disable_plugin()

    def _get_forward_prefix(self, message: dict, bot) -> str:
        """生成转发消息的前缀，优先使用规则中配置的name别名"""
        # 获取wxid
        sender_wxid = message.get('SenderWxid', '未知成员')
        from_wxid = message.get('FromWxid', '未知来源')
        is_group = message.get('IsGroup', False)
        rule = message.get('MatchedRule', {})
        
        # 获取来源别名（优先使用配置中的name）
        from_name = rule.get('name', from_wxid)
        
        # 获取发送者别名（优先使用配置中的sender_names字典）
        sender_names = rule.get('sender_names', {})
        sender_name = sender_names.get(sender_wxid, sender_wxid)
        
        # 使用真实换行符而不是\n字符串
        if is_group:
            return f"[转发自群聊 {from_name} (由 {sender_name} 发送)]:\n\n"
        else:
            return f"[转发自 {from_name}]:\n\n"

    async def _get_display_names(self, bot, message: dict) -> dict:
        """简化版本，不再获取名称信息"""
        # 返回空结果，不再尝试获取名称
        return {}

    def register_processor(self, hook_point, processor_func):
        """注册消息处理器
        
        Args:
            hook_point: 处理钩子点，可选值: 
                - before_match: 规则匹配前
                - after_match: 规则匹配后
                - before_forward: 转发前
                - after_forward: 转发后
            processor_func: 处理函数，接收参数 (bot, message, rule)，
                            需返回处理后的message对象或None表示拦截消息
        """
        if hook_point not in self.msg_processors:
            logger.error(f"[ToolMsgForwarder] 无效的钩子点: {hook_point}")
            return False
            
        if not callable(processor_func):
            logger.error(f"[ToolMsgForwarder] 处理器必须是可调用函数")
            return False
            
        self.msg_processors[hook_point].append(processor_func)
        logger.info(f"[ToolMsgForwarder] 已注册{hook_point}处理器: {processor_func.__name__}")
        return True
        
    def unregister_processor(self, hook_point, processor_func):
        """取消注册消息处理器"""
        if hook_point not in self.msg_processors:
            return False
            
        if processor_func in self.msg_processors[hook_point]:
            self.msg_processors[hook_point].remove(processor_func)
            logger.info(f"[ToolMsgForwarder] 已移除{hook_point}处理器: {processor_func.__name__}")
            return True
        return False
        
    async def _apply_processors(self, hook_point, bot, message, rule=None):
        """应用指定钩子点的所有处理器
        
        Returns:
            处理后的message对象，或None表示消息被拦截
        """
        if hook_point not in self.msg_processors:
            return message
        
        # 添加详细日志，特别关注before_forward
        if hook_point == "before_forward":
            processor_names = [p.__name__ for p in self.msg_processors[hook_point]]
            logger.warning(f"[ToolMsgForwarder] 调用before_forward钩子，共{len(processor_names)}个处理器: {processor_names}")
            
            # 检查消息内容
            if isinstance(message, dict) and "content_to_send" in message:
                logger.warning(f"[ToolMsgForwarder] before_forward处理的内容: {message.get('content_to_send', '')[:100]}...")
            
        current_message = message
        for processor in self.msg_processors[hook_point]:
            try:
                # 添加处理器调用日志
                if hook_point == "before_forward":
                    logger.warning(f"[ToolMsgForwarder] 执行before_forward处理器: {processor.__name__}")
                
                result = await processor(bot, current_message, rule)
                
                if result is None:
                    logger.debug(f"[ToolMsgForwarder] {hook_point}处理器 {processor.__name__} 拦截了消息")
                    return None
                
                # 检查处理结果
                if hook_point == "before_forward" and isinstance(result, dict) and "content_to_send" in result:
                    if result["content_to_send"] != current_message.get("content_to_send", ""):
                        logger.warning(f"[ToolMsgForwarder] 处理器{processor.__name__}修改了内容: {result['content_to_send'][:100]}...")
                
                current_message = result
            except Exception as e:
                logger.error(f"[ToolMsgForwarder] {hook_point}处理器 {processor.__name__} 执行出错: {e}")
                import traceback
                logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
                
        return current_message

    async def _process_forwarding(
        self, bot, message: dict, msg_content_key: str, 
        msg_type_rules_key: str, send_action, is_media: bool = False, 
        filename_key: str = None
    ):
        """转发消息处理逻辑"""
        msg_id = message.get('MsgId', '未知ID')
        from_wxid = message.get('FromWxid', '未知来源')
        sender_wxid = message.get('SenderWxid', '与来源相同')
        is_group = message.get('IsGroup', False)
        
        # 记录收到的消息基本信息
        logger.debug(
            f"[ToolMsgForwarder] 收到{msg_type_rules_key[:-6]}消息: "
            f"ID={msg_id}, 来源={from_wxid}, "
            f"发送者={sender_wxid if sender_wxid != from_wxid else '与来源相同'}, "
            f"是否群聊={is_group}"
        )
        
        # 如果插件被禁用，直接返回
        if not self.enable:
            logger.debug(f"[ToolMsgForwarder] 插件已禁用，不处理消息")
            return True
        
        # 应用规则匹配前处理器
        processed_message = await self._apply_processors("before_match", bot, message)
        if processed_message is None:
            logger.debug(f"[ToolMsgForwarder] 消息被before_match处理器拦截")
            return True
        message = processed_message
            
        # 获取对应类型的规则
        rules = self.plugin_config.get(msg_type_rules_key, [])
        rule_count = len(rules)
        if not rules:
            logger.debug(f"[ToolMsgForwarder] 没有配置{msg_type_rules_key[:-6]}规则，跳过处理")
            return True

        # 检查消息内容是否存在
        original_content = message.get(msg_content_key)
        if original_content is None or (is_media and not original_content):
            logger.warning(f"[ToolMsgForwarder] {msg_type_rules_key[:-6]}消息内容为空，消息ID: {msg_id}")
            return True

        logger.debug(f"[ToolMsgForwarder] 开始匹配{rule_count}条{msg_type_rules_key[:-6]}规则")
        matched_count = 0
        processed_count = 0

        # 遍历规则进行匹配
        for i, rule in enumerate(rules):
            rule_id = f"{msg_type_rules_key[:-6]}-{i+1}"
            
            # 检查规则是否启用
            if not rule.get("enabled", False):
                logger.debug(f"[ToolMsgForwarder] 规则{rule_id}已禁用，跳过")
                continue

            # 检查来源是否匹配
            rule_from_wxid = rule.get("from_wxid")
            if rule_from_wxid != from_wxid:
                logger.debug(f"[ToolMsgForwarder] 规则{rule_id}的来源{rule_from_wxid}与消息来源{from_wxid}不匹配，跳过")
                continue

            # 如果是群聊，检查发送者是否符合规则
            if is_group:
                specific_senders = rule.get("listen_specific_senders_in_group", [])
                if specific_senders:
                    if sender_wxid not in specific_senders:
                        logger.debug(
                            f"[ToolMsgForwarder] 规则{rule_id}指定了监听{len(specific_senders)}人，"
                            f"但发送者{sender_wxid}不在列表中，跳过"
                        )
                        continue
                    else:
                        logger.debug(f"[ToolMsgForwarder] 规则{rule_id}的发送者{sender_wxid}在监听列表中，匹配成功")

            # 获取转发目标
            targets = rule.get("to_wxids", [])
            if not targets:
                logger.debug(f"[ToolMsgForwarder] 规则{rule_id}没有配置转发目标，跳过")
                continue
            
            # 规则匹配成功
            matched_count += 1
            logger.debug(
                f"[ToolMsgForwarder] 规则{rule_id}匹配成功，"
                f"准备转发给{len(targets)}个目标: {targets}"
            )
            
            # 将匹配的规则添加到消息中，用于后续获取别名
            message["MatchedRule"] = rule
            
            # 应用规则匹配后处理器
            processed_message = await self._apply_processors("after_match", bot, message, rule)
            if processed_message is None:
                logger.debug(f"[ToolMsgForwarder] 消息被after_match处理器拦截")
                continue
            message = processed_message
            
            # 获取消息内容（可能已被处理器修改）
            original_content = message.get(msg_content_key)
            
            # 准备转发消息
            prepend_info = rule.get("prepend_info", True)
            prefix = self._get_forward_prefix(message, bot) if prepend_info else ""
            
            # 转发给每个目标
            for target_wxid in targets:
                try:
                    content_to_send = original_content
                    text_prefix_for_media = ""

                    # 处理前缀信息
                    if prepend_info:
                        if msg_type_rules_key == "text_rules":
                            content_to_send = f"{prefix}{original_content}"
                            logger.debug(f"[ToolMsgForwarder] 已添加前缀到文本消息")
                        else:
                            media_type_display = msg_type_rules_key.split('_')[0].capitalize()
                            file_name_info = ""
                            if filename_key and message.get(filename_key):
                                file_name_info = f": {message.get(filename_key)}"
                            text_prefix_for_media = f"{prefix}[{media_type_display}{file_name_info}]"
                            logger.debug(f"[ToolMsgForwarder] 为媒体消息准备前缀文本: {text_prefix_for_media}")
                    
                    # 获取目标名称（显示）
                    target_names = rule.get("target_names", {})
                    target_name = target_names.get(target_wxid, target_wxid)
                    
                    # 构建单个目标的转发上下文
                    forward_context = {
                        "target_wxid": target_wxid,
                        "target_name": target_name,
                        "content_to_send": content_to_send,
                        "text_prefix": text_prefix_for_media,
                        "prepend_info": prepend_info,
                        "msg_type": msg_type_rules_key[:-6],
                        "filename": message.get(filename_key) if filename_key else None
                    }
                    
                    # 应用转发前处理器
                    processed_context = await self._apply_processors("before_forward", bot, forward_context, rule)
                    if processed_context is None:
                        logger.debug(f"[ToolMsgForwarder] 转发到 {target_name} 被before_forward处理器拦截")
                        continue
                    
                    # 处理器可能修改了内容
                    forward_context = processed_context
                    content_to_send = forward_context.get("content_to_send", content_to_send)
                    text_prefix_for_media = forward_context.get("text_prefix", text_prefix_for_media)
                    
                    # 发送媒体前缀文本
                    if text_prefix_for_media:
                        logger.debug(f"[ToolMsgForwarder] 发送媒体前缀文本到 {target_name}")
                        await bot.send_text_message(target_wxid, text_prefix_for_media)
                    
                    # 发送实际内容
                    logger.debug(
                        f"[ToolMsgForwarder] 发送{msg_type_rules_key[:-6]}内容到 {target_name}, "
                        f"{'带文件名' if filename_key else '无附加参数'}"
                    )
                    
                    if filename_key:
                        file_name = forward_context.get("filename", message.get(filename_key, "未知文件"))
                        logger.debug(f"[ToolMsgForwarder] 文件名: {file_name}")
                        await send_action(bot, target_wxid, content_to_send, file_name)
                    else:
                        await send_action(bot, target_wxid, content_to_send)
                    
                    processed_count += 1
                    logger.debug(f"[ToolMsgForwarder] 成功转发到 {target_name}")
                    
                    # 应用转发后处理器
                    await self._apply_processors("after_forward", bot, {
                        **forward_context,
                        "success": True
                    }, rule)
                        
                except Exception as e:
                    logger.error(f"[ToolMsgForwarder] 转发消息到 {target_wxid} 失败: {e}")
                    import traceback
                    logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
                    
                    # 应用转发后处理器（失败情况）
                    await self._apply_processors("after_forward", bot, {
                        **forward_context,
                        "success": False,
                        "error": str(e)
                    }, rule)
        
        logger.debug(
            f"[ToolMsgForwarder] {msg_type_rules_key[:-6]}消息处理完成: "
            f"规则总数={rule_count}, 匹配规则数={matched_count}, 成功转发数={processed_count}"
        )
        return True

    @on_text_message(priority=99)
    async def handle_text_forward(self, bot, message: dict):
        """处理文本消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到文本消息，准备处理")
        async def send_text_action(b, to_wxid, content):
            await b.send_text_message(to_wxid, content)
        return await self._process_forwarding(bot, message, "Content", "text_rules", send_text_action)

    @on_image_message(priority=99)
    async def handle_image_forward(self, bot, message: dict):
        """处理图片消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到图片消息，准备处理")
        async def send_image_action(b, to_wxid, content):
            await b.send_image_message(to_wxid, content)
        return await self._process_forwarding(bot, message, "Content", "image_rules", send_image_action, is_media=True)

    @on_file_message(priority=99)
    async def handle_file_forward(self, bot, message: dict):
        """处理文件消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到文件消息，准备处理")
        async def send_file_action(b, to_wxid, content, filename):
            await b.send_file_message(to_wxid, content, filename)
        return await self._process_forwarding(bot, message, "File", "file_rules", send_file_action, is_media=True, filename_key="Filename")

    @on_video_message(priority=99)
    async def handle_video_forward(self, bot, message: dict):
        """处理视频消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到视频消息，准备处理")
        async def send_video_action(b, to_wxid, content):
            await b.send_video_message(to_wxid, content)
        return await self._process_forwarding(bot, message, "Video", "video_rules", send_video_action, is_media=True)

    def _load_second_processor(self):
        """加载并注册SecondProcessor处理器"""
        logger.warning(f"[ToolMsgForwarder] 开始加载SecondProcessor...")
        
        try:
            # 清除之前可能存在的处理器
            # 记录当前处理器名称，用于检测重复
            old_processors = []
            if "before_forward" in self.msg_processors:
                old_processors = [p.__name__ for p in self.msg_processors.get("before_forward", [])]
                logger.warning(f"[ToolMsgForwarder] 当前before_forward处理器: {old_processors}")
                
            # 清空处理器列表
            self.msg_processors["before_forward"] = []
            logger.warning(f"[ToolMsgForwarder] 已清空before_forward处理器")
            
            try:
                # 使用get_processor函数获取最新的SecondProcessor实例
                from . import get_processor, SECOND_PROCESSOR_VERSION
                second_processor = get_processor()
                
                logger.warning(f"[ToolMsgForwarder] 已获取SecondProcessor实例，版本: {SECOND_PROCESSOR_VERSION}")
                
                # 确保使用配置文件中的设置
                config_path = os.path.join(os.path.dirname(__file__), "config.toml")
                if os.path.exists(config_path):
                    logger.warning(f"[ToolMsgForwarder] 主配置文件存在: {os.path.abspath(config_path)}")
                    # 重新加载配置
                    if hasattr(second_processor, '_load_config') and callable(second_processor._load_config):
                        second_processor._load_config()
                        logger.warning(f"[ToolMsgForwarder] 已重新加载SecondProcessor配置")
                else:
                    logger.warning(f"[ToolMsgForwarder] 主配置文件不存在: {os.path.abspath(config_path)}")
                
                # 调用注册方法
                logger.warning("[ToolMsgForwarder] 调用register_to_forwarder方法")
                success = second_processor.register_to_forwarder(self)
                
                if success:
                    logger.warning(f"[ToolMsgForwarder] SecondProcessor注册成功，版本: {SECOND_PROCESSOR_VERSION}")
                else:
                    logger.warning("[ToolMsgForwarder] SecondProcessor注册失败")
                    
                # 检查注册的处理器，确保没有重复
                if "before_forward" in self.msg_processors:
                    current_processors = [p.__name__ for p in self.msg_processors.get("before_forward", [])]
                    logger.warning(f"[ToolMsgForwarder] 当前before_forward处理器数量: {len(self.msg_processors['before_forward'])}")
                    logger.warning(f"[ToolMsgForwarder] before_forward处理器列表: {current_processors}")
                    
                    # 检查重复
                    duplicates = []
                    seen = set()
                    for p_name in current_processors:
                        if p_name in seen:
                            duplicates.append(p_name)
                        else:
                            seen.add(p_name)
                    
                    if duplicates:
                        logger.warning(f"[ToolMsgForwarder] 检测到重复处理器: {duplicates}，尝试移除")
                        # 创建新的处理器列表，保留每个处理器的第一个实例
                        unique_processors = []
                        seen_names = set()
                        for p in self.msg_processors["before_forward"]:
                            if p.__name__ not in seen_names:
                                unique_processors.append(p)
                                seen_names.add(p.__name__)
                                
                        # 更新处理器列表
                        self.msg_processors["before_forward"] = unique_processors
                        logger.warning(f"[ToolMsgForwarder] 移除重复处理器后的数量: {len(self.msg_processors['before_forward'])}")
            except ImportError as e:
                logger.error(f"[ToolMsgForwarder] 无法导入SecondProcessor模块: {e}")
                # 回退到直接使用京东转链功能
                self._init_jd_converter()
        
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 加载SecondProcessor失败: {e}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
            # 错误发生时，回退到直接初始化
            self._init_jd_converter()

    def _init_jd_converter(self):
        """初始化京东转链处理器"""
        try:
            logger.warning("[ToolMsgForwarder] 尝试注册京东转链处理器")
            # 确保使用配置文件中的设置
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            second_processor_enabled = False
            jd_rebate_config = None
            
            if os.path.exists(config_path):
                try:
                    with open(config_path, "rb") as f:
                        config_data = tomllib.load(f)
                    
                    # 检查配置是否启用了二次处理器
                    if "ToolMsgForwarder" in config_data and "second_processor" in config_data["ToolMsgForwarder"]:
                        sp_config = config_data["ToolMsgForwarder"]["second_processor"]
                        second_processor_enabled = sp_config.get("enable", False)
                        logger.warning(f"[ToolMsgForwarder] 配置中二次处理器启用状态: {second_processor_enabled}")
                        
                        # 提取京东转链配置
                        if "jd_rebate" in sp_config:
                            jd_rebate_config = sp_config["jd_rebate"]
                            logger.warning(f"[ToolMsgForwarder] 找到京东转链配置: {jd_rebate_config}")
                            
                            # 特别检查prepend_converted_tag
                            if "prepend_converted_tag" in jd_rebate_config:
                                logger.warning(f"[ToolMsgForwarder] 配置中的prepend_converted_tag: {jd_rebate_config['prepend_converted_tag']}, 类型: {type(jd_rebate_config['prepend_converted_tag'])}")
                except Exception as e:
                    logger.error(f"[ToolMsgForwarder] 读取配置文件失败: {e}")
            
            if not second_processor_enabled:
                logger.warning("[ToolMsgForwarder] 配置中未启用二次处理器，跳过")
                return
            
            # 使用导入的转链处理器
            from .SecondProcessor import SecondProcessor
            processor = SecondProcessor()
            
            # 直接设置配置，避免读取文件
            if jd_rebate_config:
                logger.warning("[ToolMsgForwarder] 直接设置京东转链配置")
                if not hasattr(processor, 'config') or processor.config is None:
                    processor.config = {
                        "enable": True,
                        "jd_rebate": {}
                    }
                
                # 复制配置，并确保布尔值类型正确
                for key, value in jd_rebate_config.items():
                    # 特殊处理布尔值
                    if key == "prepend_converted_tag":
                        if isinstance(value, str):
                            if value.lower() == "true":
                                processor.config["jd_rebate"][key] = True
                            elif value.lower() == "false":
                                processor.config["jd_rebate"][key] = False
                            else:
                                processor.config["jd_rebate"][key] = bool(value)
                        else:
                            processor.config["jd_rebate"][key] = bool(value)
                        logger.warning(f"[ToolMsgForwarder] 设置prepend_converted_tag: {value} -> {processor.config['jd_rebate'][key]}, 类型: {type(processor.config['jd_rebate'][key])}")
                    else:
                        processor.config["jd_rebate"][key] = value
                        logger.warning(f"[ToolMsgForwarder] 设置配置项: {key} = {value}, 类型: {type(value)}")
                
                # 特别检查prepend_converted_tag
                if "prepend_converted_tag" in processor.config["jd_rebate"]:
                    logger.warning(f"[ToolMsgForwarder] 设置后的prepend_converted_tag: {processor.config['jd_rebate']['prepend_converted_tag']}, 类型: {type(processor.config['jd_rebate']['prepend_converted_tag'])}")
                
                # 日志输出最终配置
                logger.warning(f"[ToolMsgForwarder] 直接设置后的京东转链配置: appkey='{processor.config['jd_rebate'].get('appkey', '')}', union_id='{processor.config['jd_rebate'].get('union_id', '')}'")
                logger.warning(f"[ToolMsgForwarder] 完整的jd_rebate配置: {processor.config['jd_rebate']}")
            
            # 注册处理器
            self.register_processor("before_forward", processor.convert_links)
            logger.warning("[ToolMsgForwarder] 成功注册京东转链处理器!")
            
            # 检查处理器
            if "before_forward" in self.msg_processors:
                processor_names = [p.__name__ for p in self.msg_processors.get("before_forward", [])]
                logger.warning(f"[ToolMsgForwarder] 当前before_forward处理器: {processor_names}")
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 注册京东转链处理器失败: {e}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")


