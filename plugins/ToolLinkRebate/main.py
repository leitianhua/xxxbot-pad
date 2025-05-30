import os
import re
import json
import aiohttp
import tomllib
import urllib.parse
import requests
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message
from utils.plugin_base import PluginBase


class ToolLinkRebate(PluginBase):
    """商品转链返利插件"""
    description = "商品转链返利插件 - 自动识别淘宝、京东链接并生成带返利的推广链接"
    author = "lei"
    version = "1.3.0"

    def __init__(self):
        super().__init__()
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")

        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)  # 是否启用插件
            self.appkey = basic_config.get("appkey", "")  # 折淘客appkey
            self.sid = basic_config.get("sid", "")  # 折淘客sid
            self.union_id = basic_config.get("union_id", "")  # 京东联盟ID
            self.pid = basic_config.get("pid", "")  # 淘宝联盟pid
            self.group_mode = basic_config.get("group_mode", "all")  # 群组控制模式
            self.group_list = basic_config.get("group_list", [])  # 群组/用户列表

            # 编译正则表达式
            self.link_patterns = {
                "taobao": re.compile(r"https?://(s\.click\.taobao\.com|m\.tb\.cn)/[^\s<]*"),  # 淘宝链接
                "jd": re.compile(r"https?://u\.jd\.com/[A-Za-z0-9]+"),  # 京东链接
                "tkl1": re.compile(r"([¥￥$].*?[¥￥$])"),  # 淘口令模式1
                "tkl2": re.compile(r"([¥￥$].*?[/\\])"),  # 淘口令模式2
                "tkl3": re.compile(r"(\(\(.*?://)"),  # 淘口令模式3
                "tkl4": re.compile(r"\(([a-zA-Z0-9]{10,})\)")  # 淘口令模式4
            }

            logger.success(f"商品转链返利插件配置加载成功")
            logger.info(f"群组控制模式: {self.group_mode}")
            logger.info(f"群组/用户列表: {self.group_list}")
        except Exception as e:
            logger.error(f"加载商品转链返利插件配置失败: {str(e)}")
            self.enable = False

    @on_text_message(priority=90)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息，检测并转换链接"""
        if not self.enable:
            logger.debug("转链插件未启用")
            return True

        content = message.get("Content", "")
        from_user = message.get("FromWxid", "")

        logger.debug(f"转链插件收到文本消息: {content}")

        # 检查消息来源是否在允许的范围内
        if not await self._check_allowed_source(from_user):
            return True

        # 处理文本中的链接
        return await self._process_links_in_text(bot, from_user, content)

    async def _check_allowed_source(self, from_user: str) -> bool:
        """检查消息来源是否在允许的范围内"""
        is_group_message = from_user.endswith("@chatroom")

        if self.group_mode == "all":
            return True
        elif self.group_mode == "whitelist":
            return from_user in self.group_list
        elif self.group_mode == "blacklist":
            return from_user not in self.group_list
        else:
            logger.warning(f"未知的群组控制模式: {self.group_mode}，默认允许所有来源")
            return True

    async def _process_links_in_text(self, bot: WechatAPIClient, from_user: str, content: str) -> bool:
        """处理文本中的链接"""
        # 查找所有匹配的链接
        found_links = {}
        for link_type, pattern in self.link_patterns.items():
            matches = pattern.findall(content)
            if matches:
                found_links[link_type] = matches

        if not found_links:
            logger.debug("没有找到需要处理的链接")
            return True

        logger.info(f"检测到链接: {found_links}")

        # 使用折淘客API进行批量转链
        converted_content = self.convert_links(content)
        
        if converted_content and converted_content != content:
            # 如果转换成功且内容不同，发送转换后的内容
            await bot.send_text_message(from_user, converted_content)
            logger.success(f"成功发送转链结果到 {from_user}")
            return False

        return True

    def convert_links(self, text: str) -> str:
        """
        调用折淘客API进行批量转链
        API文档: https://api.zhetaoke.com:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx
        """
        try:
            url = "https://api.zhetaoke.com:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

            # 必填参数
            params = {
                "appkey": self.appkey,  # 折淘客的对接秘钥appkey
                "sid": self.sid,  # 添加sid参数
                "unionId": self.union_id, # 京东联盟ID
                "pid": self.pid,  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
                "tkl": urllib.parse.quote(text),  # 需要转换的文本，进行URL编码
            }

            logger.info(f"发送转链请求: {url}")
            
            # 发送请求
            response = requests.get(url, params=params)

            # 处理响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"API响应结果: {result}")
                    if result.get("status") == 200:
                        return result.get("content", "")
                    else:
                        error_msg = result.get('content', '未知错误')
                        logger.error(f"转链失败: {result.get('status')}, 消息: {error_msg}")
                        # 根据不同的错误状态返回不同的提示信息
                        if result.get("status") == 301:
                            return f"【转链失败】\n\n{text}"
                        else:
                            return f"【转链失败】状态码: {result.get('status')}, {error_msg}\n\n{text}"
                except json.JSONDecodeError:
                    logger.error(f"响应解析失败")
                    return f"【转链失败】响应解析错误\n\n{text}"
            else:
                logger.error(f"请求失败: {response.status_code}")
                return f"【转链失败】HTTP请求失败: {response.status_code}\n\n{text}"
        except Exception as e:
            logger.error(f"批量转链时发生错误: {str(e)}")
            import traceback
            logger.error(f"错误堆栈: {traceback.format_exc()}")
            return f"【转链失败】系统错误: {str(e)}\n\n{text}"