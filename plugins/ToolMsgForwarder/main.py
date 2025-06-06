from loguru import logger
import os
import tomllib
from utils.plugin_base import PluginBase
from utils.decorators import on_text_message, on_image_message, on_file_message, on_video_message, on_xml_message
import json
import re
import urllib.parse
import requests
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ToolMsgForwarder(PluginBase):
    """
    消息转发插件，可根据配置转发指定来源的文本、图片、文件、视频消息到指定目标。
    支持提取XML消息中的商品信息，并可选择性地转换电商链接。
    """
    description = "消息转发插件，可根据配置转发指定来源的文本、图片、文件、视频消息到指定目标(支持多目标和群内指定人)。需要手动配置才能使用，无默认配置。"
    author = "ai"
    version = "1.1.0"  # 优化版本，支持XML消息提取和转发

    def __init__(self):
        super().__init__()
        self.plugin_config = {}
        self.enable = True  # 默认启用
        self.unified_rules = []  # 通用规则数组

        # 转链功能配置
        self.rebate_config = {
            "enable": True,  # 是否启用转链功能
            "prepend_converted_tag": True,  # 是否在转链消息前添加[已转链]标签
            "appkey": "",  # 折淘客的对接秘钥appkey
            "sid": "",  # 添加sid参数
            "union_id": "",  # 京东联盟ID
            "pid": "",  # 淘宝联盟pid
        }

        logger.info(f"[ToolMsgForwarder] 插件初始化")
        self._load_config()
        logger.info(f"[ToolMsgForwarder] 初始化完成")

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
                self.enable = False
                return

            config = toml_data[plugin_name]
            self.plugin_config = config
            logger.debug(f"[ToolMsgForwarder] 已读取配置: {list(config.keys())}")

            # 加载插件状态
            self.enable = config.get("enable", True)
            logger.debug(f"[ToolMsgForwarder] 插件状态: {'启用' if self.enable else '禁用'}")

            # 加载转链配置
            if "rebate" in config:
                rebate_config = config["rebate"]
                self.rebate_config.update(rebate_config)
                logger.info(f"[ToolMsgForwarder] 已加载转链配置: 启用={self.rebate_config['enable']}")

            # 加载统一规则
            if "rules" in config:
                self.unified_rules = config["rules"]
                logger.info(f"[ToolMsgForwarder] 已加载统一规则: {len(self.unified_rules)}条")
            else:
                # 尝试旧式路径
                rules_key = f"{plugin_name}.rules"
                if rules_key in toml_data:
                    self.unified_rules = toml_data[rules_key]
                    logger.info(f"[ToolMsgForwarder] 已通过 {rules_key} 加载统一规则: {len(self.unified_rules)}条")
                else:
                    logger.warning(f"[ToolMsgForwarder] 未找到统一规则配置，请检查配置文件格式")

            # 更新插件配置
            self.plugin_config["unified_rules"] = self.unified_rules

            # 检查并打印规则详情（调试用）
            self._log_rules_details()

        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 加载配置文件 {config_path} 时发生错误: {e}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
            return

    def _log_rules_details(self):
        """记录所有规则的详细信息"""
        if not self.unified_rules:
            logger.warning(f"[ToolMsgForwarder] 没有配置统一规则，插件可能无法正常工作")
            return

        for i, rule in enumerate(self.unified_rules):
            if rule.get("enabled", False):
                from_wxid = rule.get("from_wxid", "未指定")
                from_name = rule.get("name", from_wxid)  # 获取别名
                to_wxids = rule.get("to_wxids", [])
                specific_senders = rule.get("listen_specific_senders_in_group", [])
                msg_types = rule.get("msg_types", ["text"])
                enable_rebate = rule.get("enable_rebate", self.rebate_config.get("enable", False))

                # 获取发送者别名
                sender_names = rule.get("sender_names", {})
                sender_names_info = ""
                if sender_names and specific_senders:
                    sender_names_list = [f"{wxid}({sender_names.get(wxid, '无别名')})" for wxid in specific_senders if wxid in sender_names]
                    if sender_names_list:
                        sender_names_info = f", 别名: {', '.join(sender_names_list)}"

                sender_info = f"(监听群内特定用户: {len(specific_senders)}人{sender_names_info})" if specific_senders else ""
                logger.debug(
                    f"[ToolMsgForwarder] 统一规则 #{i + 1}: 来源 {from_wxid}(别名:{from_name}) {sender_info} -> 转发到 {len(to_wxids)} 个目标, 消息类型: {msg_types}, 转链: {'启用' if enable_rebate else '禁用'}")

    def _get_forward_prefix(self, message: dict) -> str:
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

    async def _process_forwarding(
            self, bot, message: dict, msg_content_key: str,
            send_action, is_media: bool = False, filename_key: str = None,
            skip_rule_matching: bool = False
    ):
        """
        转发消息处理逻辑
        
        参数:
        - bot: 机器人实例
        - message: 消息字典
        - msg_content_key: 消息内容的键名
        - send_action: 发送消息的方法
        - is_media: 是否为媒体消息
        - filename_key: 文件名的键名
        - skip_rule_matching: 是否跳过规则匹配，直接转发给所有目标
        """
        # 如果插件被禁用，直接返回
        if not self.enable:
            return True
            
        # 获取消息基本信息
        msg_id = message.get('MsgId', '未知ID')
        from_wxid = message.get('FromWxid', '未知来源')
        sender_wxid = message.get('SenderWxid', '与来源相同')
        is_group = message.get('IsGroup', False)

        # 确定消息类型
        msg_type = "text"
        if msg_content_key == "File":
            msg_type = "file"
        elif msg_content_key == "Video":
            msg_type = "video"
        elif is_media:
            msg_type = "image"
        
        # 检查是否是XML消息或已转换的XML消息
        is_xml_message = False
        content = message.get(msg_content_key, "")
        if isinstance(content, str) and content.strip().startswith("<"):
            is_xml_message = True
            msg_type = "xml"
        elif message.get("XmlConverted", False):
            # 这是已经转换过的XML消息
            is_xml_message = False
            msg_type = "text"  # 已转换为文本

        logger.debug(
            f"[ToolMsgForwarder] 收到{msg_type}消息: ID={msg_id}, 来源={from_wxid}, "
            f"发送者={sender_wxid if sender_wxid != from_wxid else '与来源相同'}, "
            f"是否群聊={is_group}"
        )

        # 获取规则
        rules = self.unified_rules
        if not rules:
            logger.debug(f"[ToolMsgForwarder] 没有配置统一规则，跳过处理")
            return True

        # 检查消息内容是否存在
        original_content = message.get(msg_content_key)
        if original_content is None or (is_media and not original_content):
            logger.warning(f"[ToolMsgForwarder] {msg_type}消息内容为空，消息ID: {msg_id}")
            return True

        # 初始化计数器
        matched_count = 0
        processed_count = 0
        
        # 处理消息转发
        if skip_rule_matching:
            # 跳过规则匹配，直接处理所有启用的规则
            logger.debug(f"[ToolMsgForwarder] 跳过规则匹配，直接处理消息")
            
            # 创建一个已处理的目标集合，避免重复转发
            processed_targets = set()
            
            for i, rule in enumerate(rules):
                if not rule.get("enabled", False):
                    continue
                    
                # 获取转发目标
                targets = rule.get("to_wxids", [])
                if not targets:
                    continue
                
                # 过滤掉已处理过的目标
                new_targets = [t for t in targets if t not in processed_targets]
                if not new_targets:
                    continue
                    
                # 规则匹配成功
                matched_count += 1
                rule_id = f"规则#{i + 1}"
                logger.debug(f"[ToolMsgForwarder] 使用{rule_id}，转发给{len(new_targets)}个目标")
                
                # 将匹配的规则添加到消息中，用于后续获取别名
                message["MatchedRule"] = rule
                
                # 转发给每个目标
                await self._forward_to_targets(
                    bot, message, rule, new_targets, msg_type, 
                    msg_content_key, original_content, 
                    is_xml_message, send_action, filename_key
                )
                
                # 记录已处理的目标
                processed_targets.update(new_targets)
                processed_count += len(new_targets)
                
        else:
            # 使用规则匹配
            logger.debug(f"[ToolMsgForwarder] 开始匹配{len(rules)}条规则")
            
            # 创建一个已处理的目标集合，避免重复转发
            processed_targets = set()
            
            # 遍历规则进行匹配
            for i, rule in enumerate(rules):
                rule_id = f"规则#{i + 1}"

                # 检查规则是否启用
                if not rule.get("enabled", False):
                    logger.debug(f"[ToolMsgForwarder] {rule_id}已禁用，跳过")
                    continue

                # 检查消息类型是否匹配
                rule_msg_types = rule.get("msg_types", ["text"])
                if msg_type not in rule_msg_types:
                    logger.debug(f"[ToolMsgForwarder] {rule_id}不处理{msg_type}类型的消息，跳过")
                    continue

                # 检查来源是否匹配
                rule_from_wxid = rule.get("from_wxid")
                if rule_from_wxid != from_wxid:
                    logger.debug(f"[ToolMsgForwarder] {rule_id}的来源与消息来源不匹配，跳过")
                    continue

                # 如果是群聊，检查发送者是否符合规则
                if is_group:
                    specific_senders = rule.get("listen_specific_senders_in_group", [])
                    if specific_senders and sender_wxid not in specific_senders:
                        logger.debug(f"[ToolMsgForwarder] {rule_id}指定了监听特定用户，但发送者不在列表中，跳过")
                        continue

                # 获取转发目标
                targets = rule.get("to_wxids", [])
                if not targets:
                    logger.debug(f"[ToolMsgForwarder] {rule_id}没有配置转发目标，跳过")
                    continue
                
                # 过滤掉已处理过的目标
                new_targets = [t for t in targets if t not in processed_targets]
                if not new_targets:
                    logger.debug(f"[ToolMsgForwarder] {rule_id}的目标已被其他规则处理，跳过")
                    continue

                # 规则匹配成功
                matched_count += 1
                logger.debug(f"[ToolMsgForwarder] {rule_id}匹配成功，准备转发给{len(new_targets)}个目标")

                # 将匹配的规则添加到消息中，用于后续获取别名
                message["MatchedRule"] = rule

                # 转发给每个目标
                await self._forward_to_targets(
                    bot, message, rule, new_targets, msg_type, 
                    msg_content_key, original_content, 
                    is_xml_message, send_action, filename_key
                )
                
                # 记录已处理的目标
                processed_targets.update(new_targets)
                processed_count += len(new_targets)

        logger.debug(
            f"[ToolMsgForwarder] {msg_type}消息处理完成: "
            f"匹配规则数={matched_count}, 成功转发数={processed_count}"
        )
        return True
        
    async def _forward_to_targets(
            self, bot, message, rule, targets, msg_type, 
            msg_content_key, original_content, is_xml_message, 
            send_action, filename_key=None
    ):
        """转发消息到目标列表"""
        prepend_info = rule.get("prepend_info", True)
        
        # XML消息不添加前缀信息
        prefix = ""
        if prepend_info and not is_xml_message and not message.get("DisableMediaPrefix", False):
            prefix = self._get_forward_prefix(message)
            
        # 转发给每个目标
        for target_wxid in targets:
            try:
                content_to_send = original_content

                # 处理前缀信息（仅用于文本消息且不是XML消息）
                if prepend_info and msg_type == "text" and not is_xml_message:
                    content_to_send = f"{prefix}{original_content}"

                # 获取目标名称（显示）
                target_names = rule.get("target_names", {})
                target_name = target_names.get(target_wxid, target_wxid)

                # 对文本消息进行转链处理
                if msg_type == "text" and self.rebate_config.get("enable", False):
                    enable_rebate = rule.get("enable_rebate", True)
                    if enable_rebate:
                        try:
                            # 检查是否有匹配的内容需要转链
                            has_match, match_type = self._check_for_matches(content_to_send)
                            if has_match:
                                logger.info(f"[ToolMsgForwarder] 检测到{match_type}，开始转链")
                                converted_content = self._convert_link(content_to_send)
                                if converted_content and converted_content != content_to_send:
                                    if self.rebate_config.get("prepend_converted_tag", True):
                                        if not converted_content.startswith("[已转链]"):
                                            converted_content = "[已转链] " + converted_content
                                    content_to_send = converted_content
                                    logger.info(f"[ToolMsgForwarder] 转链成功")
                        except Exception as e:
                            logger.error(f"[ToolMsgForwarder] 转换链接时发生错误: {e}")

                # 发送实际内容
                logger.debug(f"[ToolMsgForwarder] 发送{msg_type}内容到 {target_name}")

                if filename_key:
                    file_name = message.get(filename_key, "未知文件")
                    # 检查 send_action 是否直接是 bot 方法
                    if callable(send_action) and hasattr(bot, send_action.__name__):
                        await send_action(target_wxid, content_to_send, file_name)
                    else:
                        await send_action(bot, target_wxid, content_to_send, file_name)
                else:
                    # 检查 send_action 是否直接是 bot 方法
                    if callable(send_action) and hasattr(bot, send_action.__name__):
                        await send_action(target_wxid, content_to_send)
                    else:
                        await send_action(bot, target_wxid, content_to_send)

                logger.debug(f"[ToolMsgForwarder] 成功转发到 {target_name}")

            except Exception as e:
                logger.error(f"[ToolMsgForwarder] 转发消息到 {target_wxid} 失败: {e}")
                import traceback
                logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")

    @on_text_message(priority=99)
    async def handle_text_forward(self, bot, message: dict):
        """处理文本消息转发"""
        return await self._process_forwarding(bot, message, "Content", bot.send_text_message)

    @on_xml_message(priority=99)
    async def handle_xml_forward(self, bot, message: dict):
        """处理xml消息转发，提取标题、描述和链接"""
        try:
            # 尝试提取XML中的关键信息
            content = message.get("Content", "")
            import xml.etree.ElementTree as ET
            root = ET.fromstring(content)
            
            # 查找appmsg节点
            appmsg = root.find(".//appmsg")
            if appmsg is not None:
                # 提取标题、描述和URL
                title_elem = appmsg.find("title")
                des_elem = appmsg.find("des")
                url_elem = appmsg.find("url")
                
                if title_elem is not None and url_elem is not None:
                    # 提取基本信息
                    title = title_elem.text or "分享"
                    description = des_elem.text if des_elem is not None else ""
                    url = url_elem.text or ""
                    
                    if url:
                        logger.info(f"[ToolMsgForwarder] 从XML提取到信息: 标题={title}, URL={url}")
                        
                        # 检查是否需要转链
                        has_match, match_type = self._check_for_matches(url)
                        converted_url = url
                        
                        # 如果启用了转链且匹配到链接
                        if has_match and self.rebate_config.get("enable", False):
                            logger.info(f"[ToolMsgForwarder] 检测到{match_type}，尝试转链")
                            converted_url = self._convert_link(url)
                            if converted_url and converted_url != url:
                                logger.info(f"[ToolMsgForwarder] 转链成功")
                        
                        # 从描述中提取产品名称 - 针对特定格式
                        product_name = self._extract_product_name(description, title)
                        
                        # 创建指定格式的输出
                        extracted_content = f"{product_name}\n{converted_url}"
                        
                        # 修改原始消息内容为提取后的文本
                        message["Content"] = extracted_content
                        logger.debug(f"[ToolMsgForwarder] 将XML转换为指定格式: {extracted_content}")
                        
                        # 标记消息来源，用于后续规则匹配
                        message["XmlConverted"] = True
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 提取XML内容时出错: {e}")
            # 出错时继续使用原始XML
        
        # 使用统一规则处理转换后的消息，但不跳过规则匹配
        # 这样可以确保只有匹配的规则会被应用
        return await self._process_forwarding(bot, message, "Content", bot.send_text_message)

    @on_image_message(priority=99)
    async def handle_image_forward(self, bot, message: dict):
        """处理图片消息转发"""
        message["DisableMediaPrefix"] = True  # 添加标记，禁用媒体消息前缀
        return await self._process_forwarding(bot, message, "Content", bot.send_image_message, is_media=True)

    @on_file_message(priority=99)
    async def handle_file_forward(self, bot, message: dict):
        """处理文件消息转发"""
        message["DisableMediaPrefix"] = True  # 添加标记，禁用媒体消息前缀
        return await self._process_forwarding(bot, message, "File", bot.send_file_message, is_media=True, filename_key="Filename")

    @on_video_message(priority=99)
    async def handle_video_forward(self, bot, message: dict):
        """处理视频消息转发"""
        message["DisableMediaPrefix"] = True  # 添加标记，禁用媒体消息前缀
        return await self._process_forwarding(bot, message, "Video", bot.send_video_message, is_media=True)

    def _check_for_matches(self, content):
        """
        检查内容中是否包含需要转链的模式
        返回: (bool, str) - 是否匹配到，匹配到的类型描述
        """
        # 淘口令匹配模式
        patterns = [
            (re.compile(r"([¥￥$].*?[¥￥$])"), "淘口令模式1"),  # 以货币符号开头和结尾的淘口令
            (re.compile(r"([¥￥$].*?[/\\])"), "淘口令模式2"),   # 以货币符号开头，以斜杠结尾的淘口令
            (re.compile(r"(\(\(.*?://)"), "淘口令模式3"),       # 以双括号开头，包含://的淘口令
            (re.compile(r"\(([a-zA-Z0-9]{10,})\)"), "淘口令模式4"),  # 括号内的10位以上字母数字组合
            (re.compile(r"https?://(s\.click\.taobao\.com|m\.tb\.cn)/[^\s<]*"), "淘宝链接"),  # 淘宝短链接
            (re.compile(r"https?://u\.jd\.com/[A-Za-z0-9]+"), "京东链接"),  # 京东短链接
        ]
        
        for pattern, match_type in patterns:
            if pattern.search(content):
                return True, match_type
                
        return False, "无匹配"

    def _convert_link(self, text):
        """调用折淘客API进行批量转链"""
        try:
            url = "https://api.zhetaoke.cn:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

            # 必填参数
            params = {
                "appkey": self.rebate_config["appkey"],  # 折淘客的对接秘钥appkey
                "sid": self.rebate_config["sid"],  # 添加sid参数
                "unionId": self.rebate_config["union_id"],  # 京东联盟ID
                "pid": self.rebate_config["pid"],  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
                "tkl": urllib.parse.quote(text),  # 需要转换的文本，进行URL编码
            }

            # 发送请求
            response = requests.get(url, params=params, verify=False)

            # 处理响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get("status") == 200:
                        return result.get("content", "")
                    else:
                        logger.error(f"[ToolMsgForwarder] 转链失败: {result.get('status')}, 消息: {result.get('content', '')}")
                        return text  # 转链失败，返回原文
                except json.JSONDecodeError:
                    logger.error(f"[ToolMsgForwarder] 响应解析失败")
                    return text
            else:
                logger.error(f"[ToolMsgForwarder] 请求失败: {response.status_code}")
                return text
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 批量转链时发生错误: {e}")
            return text

    def _extract_product_name(self, description, default_title):
        """从描述中提取产品名称"""
        if not description:
            return default_title
            
        # 尝试提取"品名:xxx"格式
        if "品名:" in description:
            name_parts = description.split("品名:", 1)
            if len(name_parts) > 1:
                product_parts = name_parts[1].split("物品规格:", 1)
                if len(product_parts) > 1:
                    return product_parts[0].strip()
                else:
                    # 如果没有"物品规格:"，则尝试提取到下一个换行符
                    product_parts = name_parts[1].split("\n", 1)
                    if len(product_parts) > 0:
                        return product_parts[0].strip()
        
        # 如果没有从描述中提取到产品名称，则使用标题
        return default_title
