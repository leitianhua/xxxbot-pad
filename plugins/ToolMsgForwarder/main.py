from loguru import logger
import os
import tomllib
from utils.plugin_base import PluginBase
from utils.decorators import on_text_message, on_image_message, on_file_message, on_video_message
import json
import re
import urllib.parse
import requests
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ToolMsgForwarder(PluginBase):
    description = "消息转发插件，可根据配置转发指定来源的文本、图片、文件、视频消息到指定目标(支持多目标和群内指定人)。需要手动配置才能使用，无默认配置。"
    author = "ai"
    version = "1.0.0"  # 重大版本升级，仅支持统一规则配置

    def __init__(self):
        super().__init__()
        self.plugin_config = {}
        self.enable = True  # 默认启用
        # 通用规则数组
        self.unified_rules = []
        
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
        
        # 初始化转链功能
        self._init_link_converter()
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
                self._disable_plugin()
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
                logger.info(f"[ToolMsgForwarder] 已加载转链配置: 启用={self.rebate_config['enable']}, appkey={self.rebate_config['appkey'][:5] if self.rebate_config.get('appkey') else '未设置'}...")
            
            # 加载统一规则 - 修复加载逻辑
            if "rules" in config:
                # 直接从plugin_config中加载rules
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
        # 记录统一规则
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
                logger.debug(f"[ToolMsgForwarder] 统一规则 #{i+1}: 来源 {from_wxid}(别名:{from_name}) {sender_info} -> 转发到 {len(to_wxids)} 个目标, 消息类型: {msg_types}, 转链: {'启用' if enable_rebate else '禁用'}")

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

    async def _process_forwarding(
        self, bot, message: dict, msg_content_key: str, 
        msg_type_rules_key: str, send_action, is_media: bool = False, 
        filename_key: str = None
    ):
        """转发消息处理逻辑，现在只使用统一规则"""
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
        
        # 记录收到的消息基本信息
        logger.debug(
            f"[ToolMsgForwarder] 收到{msg_type}消息: "
            f"ID={msg_id}, 来源={from_wxid}, "
            f"发送者={sender_wxid if sender_wxid != from_wxid else '与来源相同'}, "
            f"是否群聊={is_group}"
        )
        
        # 如果插件被禁用，直接返回
        if not self.enable:
            logger.debug(f"[ToolMsgForwarder] 插件已禁用，不处理消息")
            return True
            
        # 获取对应类型的规则
        rules = self.unified_rules
        rule_count = len(rules)
        if not rules:
            logger.debug(f"[ToolMsgForwarder] 没有配置统一规则，跳过处理")
            return True

        # 检查消息内容是否存在
        original_content = message.get(msg_content_key)
        if original_content is None or (is_media and not original_content):
            logger.warning(f"[ToolMsgForwarder] {msg_type}消息内容为空，消息ID: {msg_id}")
            return True

        logger.debug(f"[ToolMsgForwarder] 开始匹配{rule_count}条统一规则")
        matched_count = 0
        processed_count = 0

        # 遍历规则进行匹配
        for i, rule in enumerate(rules):
            rule_id = f"unified-{i+1}"
            
            # 检查规则是否启用
            if not rule.get("enabled", False):
                logger.debug(f"[ToolMsgForwarder] 规则{rule_id}已禁用，跳过")
                continue
                
            # 检查消息类型是否匹配
            rule_msg_types = rule.get("msg_types", ["text"])
            if msg_type not in rule_msg_types:
                logger.debug(f"[ToolMsgForwarder] 规则{rule_id}不处理{msg_type}类型的消息，跳过")
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
            
            # 获取消息内容
            original_content = message.get(msg_content_key)
            
            # 准备转发消息
            prepend_info = rule.get("prepend_info", True)
            prefix = self._get_forward_prefix(message, bot) if prepend_info else ""
            
            # 转发给每个目标
            for target_wxid in targets:
                try:
                    content_to_send = original_content
                    
                    # 处理前缀信息（仅用于文本消息）
                    if prepend_info and msg_type == "text":
                        content_to_send = f"{prefix}{original_content}"
                        logger.debug(f"[ToolMsgForwarder] 已添加前缀到文本消息")
                    
                    # 获取目标名称（显示）
                    target_names = rule.get("target_names", {})
                    target_name = target_names.get(target_wxid, target_wxid)
                    
                    # 对文本消息进行转链处理
                    if msg_type == "text" and self.rebate_config.get("enable", False):
                        enable_rebate = rule.get("enable_rebate", True)
                        if enable_rebate:
                            try:
                                # 检查是否有匹配的内容需要转链
                                has_match, match_type = self.check_for_matches(content_to_send)
                                if has_match:
                                    logger.info(f"[ToolMsgForwarder] 检测到匹配类型: {match_type}，开始转链")
                                    converted_content = self.convert_taobao_link(content_to_send)
                                    if converted_content and converted_content != content_to_send:
                                        if self.rebate_config.get("prepend_converted_tag", True):
                                            if not converted_content.startswith("[已转链]"):
                                                converted_content = "[已转链] " + converted_content
                                        content_to_send = converted_content
                                        logger.info(f"[ToolMsgForwarder] 转链成功: {content_to_send[:50]}...")
                            except Exception as e:
                                logger.error(f"[ToolMsgForwarder] 转换链接时发生错误: {str(e)}")
                    
                    # 发送实际内容
                    logger.debug(
                        f"[ToolMsgForwarder] 发送{msg_type}内容到 {target_name}, "
                        f"{'带文件名' if filename_key else '无附加参数'}"
                    )
                    
                    if filename_key:
                        file_name = message.get(filename_key, "未知文件")
                        logger.debug(f"[ToolMsgForwarder] 文件名: {file_name}")
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
                    
                    processed_count += 1
                    logger.debug(f"[ToolMsgForwarder] 成功转发到 {target_name}")
                        
                except Exception as e:
                    logger.error(f"[ToolMsgForwarder] 转发消息到 {target_wxid} 失败: {e}")
                    import traceback
                    logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
        
        logger.debug(
            f"[ToolMsgForwarder] {msg_type}消息处理完成: "
            f"规则总数={rule_count}, 匹配规则数={matched_count}, 成功转发数={processed_count}"
        )
        return True

    @on_text_message(priority=99)
    async def handle_text_forward(self, bot, message: dict):
        """处理文本消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到文本消息，准备处理")
        # 使用统一规则处理文本消息
        return await self._process_forwarding(bot, message, "Content", "unified_rules", bot.send_text_message)

    @on_image_message(priority=99)
    async def handle_image_forward(self, bot, message: dict):
        """处理图片消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到图片消息，准备处理")
        # 使用统一规则处理图片消息，设置禁用前缀
        message["DisableMediaPrefix"] = True  # 添加标记，禁用媒体消息前缀
        return await self._process_forwarding(bot, message, "Content", "unified_rules", bot.send_image_message, is_media=True)

    @on_file_message(priority=99)
    async def handle_file_forward(self, bot, message: dict):
        """处理文件消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到文件消息，准备处理")
        # 使用统一规则处理文件消息，设置禁用前缀
        message["DisableMediaPrefix"] = True  # 添加标记，禁用媒体消息前缀
        return await self._process_forwarding(bot, message, "File", "unified_rules", bot.send_file_message, is_media=True, filename_key="Filename")

    @on_video_message(priority=99)
    async def handle_video_forward(self, bot, message: dict):
        """处理视频消息转发"""
        logger.debug(f"[ToolMsgForwarder] 收到视频消息，准备处理")
        # 使用统一规则处理视频消息，设置禁用前缀
        message["DisableMediaPrefix"] = True  # 添加标记，禁用媒体消息前缀
        return await self._process_forwarding(bot, message, "Video", "unified_rules", bot.send_video_message, is_media=True)

    def _init_link_converter(self):
        """初始化转链功能"""
        try:
            logger.info(f"[ToolMsgForwarder] 正在初始化转链功能...")
            
            # 检查转链功能是否启用
            if not self.rebate_config.get("enable", False):
                logger.info(f"[ToolMsgForwarder] 全局转链功能未启用")
                return
            
            # 检查必要参数
            if not self.rebate_config.get("appkey") or not self.rebate_config.get("pid"):
                logger.error(f"[ToolMsgForwarder] 转链功能缺少必要参数: appkey或pid")
                return
                
            logger.info(f"[ToolMsgForwarder] 转链功能初始化成功")
            
        except Exception as e:
            logger.error(f"[ToolMsgForwarder] 初始化转链功能失败: {e}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")

    def check_for_matches(self, content):
        """
        检查内容中是否包含需要转链的模式
        返回: (bool, str) - 是否匹配到，匹配到的类型描述
        """
        logger.info(f"[ToolMsgForwarder] 开始检查内容匹配: {content}")

        # 淘口令匹配模式1：匹配类似￥...￥的格式
        pattern_tkl1 = re.compile(r"([¥￥$].*?[¥￥$])")  # 以货币符号开头和结尾的淘口令
        tkl1_matches = pattern_tkl1.findall(content)
        if tkl1_matches:
            logger.info(f"[ToolMsgForwarder] 匹配到淘口令模式1: {tkl1_matches}")
            return True, "淘口令模式1"

        # 淘口令匹配模式2：匹配类似￥.../的格式
        pattern_tkl2 = re.compile(r"([¥￥$].*?[/\\])")  # 以货币符号开头，以斜杠结尾的淘口令
        tkl2_matches = pattern_tkl2.findall(content)
        logger.info(f"[ToolMsgForwarder] 淘口令模式2匹配结果: {tkl2_matches}")
        if tkl2_matches:
            logger.info(f"[ToolMsgForwarder] 匹配到淘口令模式2: {tkl2_matches}")
            return True, "淘口令模式2"

        # 淘口令匹配模式3：匹配类似((...://的格式
        pattern_tkl3 = re.compile(r"(\(\(.*?://)")  # 以双括号开头，包含://的淘口令
        tkl3_matches = pattern_tkl3.findall(content)
        if tkl3_matches:
            logger.info(f"[ToolMsgForwarder] 匹配到淘口令模式3: {tkl3_matches}")
            return True, "淘口令模式3"

        # 淘口令匹配模式4：匹配类似(MQ1Vdv5zF2C) CZ000的格式
        pattern_tkl4 = re.compile(r"\(([a-zA-Z0-9]{10,})\)")  # 括号内的10位以上字母数字组合
        tkl4_matches = pattern_tkl4.findall(content)
        if tkl4_matches:
            logger.info(f"[ToolMsgForwarder] 匹配到淘口令模式4: {tkl4_matches}")
            return True, "淘口令模式4"

        # 链接匹配模式1：匹配淘宝链接
        pattern_taobao_link = re.compile(r"https?://(s\.click\.taobao\.com|m\.tb\.cn)/[^\s<]*")  # 淘宝短链接或移动端链接
        taobao_links = pattern_taobao_link.findall(content)
        if taobao_links:
            logger.info(f"[ToolMsgForwarder] 匹配到淘宝链接: {taobao_links}")
            return True, "淘宝链接"

        # 链接匹配模式2：匹配京东链接
        pattern_jd_link = re.compile(r"https?://u\.jd\.com/[A-Za-z0-9]+")  # 京东短链接
        jd_links = pattern_jd_link.findall(content)
        if jd_links:
            logger.info(f"[ToolMsgForwarder] 匹配到京东链接: {jd_links}")
            return True, "京东链接"

        logger.info(f"[ToolMsgForwarder] 未匹配到任何模式")
        return False, "无匹配"
    
    def convert_taobao_link(self, text):
        """
        调用折淘客API进行批量转链
        """
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

            logger.info(f"[ToolMsgForwarder] 发送转链请求: {url}")

            # 发送请求
            response = requests.get(url, params=params, verify=False)

            # 处理响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"[ToolMsgForwarder] API响应结果: {result}")
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
            logger.error(f"[ToolMsgForwarder] 批量转链时发生错误: {str(e)}")
            import traceback
            logger.error(f"[ToolMsgForwarder] 错误堆栈: {traceback.format_exc()}")
            return text


