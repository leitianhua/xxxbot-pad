from loguru import logger
import tomllib
import os
import json
import asyncio
import aiohttp

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase


class ToolGroupForbidden(PluginBase):
    description = "群发言白名单 - 只允许白名单成员在群中发言"
    author = "xxxbot"
    version = "1.0.0"

    def __init__(self):
        super().__init__()

        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)  # 读取插件开关
            self.notify_receiver = basic_config.get("notify_receiver", "")  # 读取通知接收人
            
            # 读取白名单规则
            whitelist_rules = config.get("whitelist_rules", [])
            
            # 处理白名单规则，转换为字典格式 {group_id: {"name": name, "whitelist": [members]}}
            self.whitelist_rules = {}
            for rule in whitelist_rules:
                if rule.get("enabled", True):
                    group_id = rule.get("group_id", "")
                    if group_id:
                        self.whitelist_rules[group_id] = {
                            "name": rule.get("name", group_id),
                            "whitelist": rule.get("whitelist", [])
                        }
            
            logger.info(f"ToolGroupForbidden 插件加载成功，白名单规则: {json.dumps(self.whitelist_rules, ensure_ascii=False)}")

        except Exception as e:
            logger.error(f"加载 ToolGroupForbidden 配置文件失败: {str(e)}")
            self.enable = False  # 如果加载失败，禁用插件
            self.whitelist_rules = {}
            self.notify_receiver = ""

    # 异步初始化
    async def async_init(self):
        return

    def get_group_name(self, group_id):
        """获取群名称，如果没有配置则返回原ID"""
        if group_id in self.whitelist_rules:
            return self.whitelist_rules[group_id]["name"]
        return group_id

    async def del_chatroom_member(self, bot: WechatAPIClient, chatroom: str, wxid: str) -> bool:
        """删除群成员

        Args:
            bot: 机器人API客户端
            chatroom: 群聊ID
            wxid: 要删除的成员wxid

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            # 使用HTTP API删除群成员
            async with aiohttp.ClientSession() as session:
                json_param = {"Wxid": bot.wxid, "ChatRoomName": chatroom, "ToWxids": wxid}
                api_url = f'http://{bot.ip}:{bot.port}/api/Group/DelChatRoomMember'
                
                logger.debug(f"删除群成员API调用: {api_url}, 参数: {json_param}")
                
                response = await session.post(api_url, json=json_param)
                json_resp = await response.json()

                if json_resp.get("Success"):
                    group_name = self.get_group_name(chatroom)
                    logger.info(f"成功从群 {group_name}({chatroom}) 中移除成员 {wxid}")
                    return True
                else:
                    group_name = self.get_group_name(chatroom)
                    logger.error(f"从群 {group_name}({chatroom}) 中移除成员 {wxid} 失败: {json_resp}")
                    return False
        except Exception as e:
            logger.error(f"删除群成员时发生异常: {str(e)}")
            return False

    async def send_notification(self, bot: WechatAPIClient, group_id: str, member_id: str, message_type: str, success: bool = True):
        """发送通知消息
        
        Args:
            bot: 机器人API客户端
            group_id: 群聊ID
            member_id: 成员ID
            message_type: 消息类型
            success: 是否成功移除
        """
        # 如果没有配置通知接收人，则不发送通知
        if not self.notify_receiver:
            return
            
        group_name = self.get_group_name(group_id)
        
        if success:
            notification = (
                f"【群成员移除通知】\n"
                f"群名称: {group_name}\n"
                f"成员ID: {member_id}\n"
                f"消息类型: {message_type}\n"
                f"处理结果: 已成功移除"
            )
        else:
            notification = (
                f"【群成员移除失败】\n"
                f"群名称: {group_name}\n"
                f"成员ID: {member_id}\n"
                f"消息类型: {message_type}\n"
                f"处理结果: 移除失败"
            )
            
        await bot.send_text_message(self.notify_receiver, notification)

    async def process_message(self, bot: WechatAPIClient, message: dict, msg_type: str):
        """处理消息的通用方法

        Args:
            bot: 机器人API客户端
            message: 消息数据
            msg_type: 消息类型描述（用于日志）
        
        Returns:
            bool: 是否继续处理消息
        """
        if not self.enable:
            return True  # 如果插件未启用，继续执行后续处理
        
        # 检查是否是群消息
        from_wxid = message.get("FromWxid", "")
        if not from_wxid.endswith("@chatroom"):
            return True  # 不是群消息，继续执行后续处理
        
        # 获取发送者wxid
        sender_wxid = message.get("SenderWxid", "")
        if not sender_wxid:
            return True  # 无法获取发送者，继续执行后续处理
        
        # 检查群ID是否在白名单规则中
        if from_wxid not in self.whitelist_rules:
            return True  # 群不在白名单规则中，继续执行后续处理
        
        # 获取白名单成员列表
        whitelist_members = self.whitelist_rules[from_wxid]["whitelist"]
        
        # 获取群名称
        group_name = self.get_group_name(from_wxid)
        
        # 检查发送者是否不在白名单中
        if sender_wxid not in whitelist_members:
            logger.info(f"检测到非白名单成员 {sender_wxid} 在群 {group_name}({from_wxid}) 中发送{msg_type}")
            
            # 移除该成员
            success = await self.del_chatroom_member(bot, from_wxid, sender_wxid)
         
                    
            # 发送详细通知给通知接收人
            await self.send_notification(bot, from_wxid, sender_wxid, msg_type, success)
        else:
            logger.info(f"检测到白名单成员 {sender_wxid} 在群 {group_name}({from_wxid}) 中发送{msg_type}")
        return False  # 不继续执行后续处理

    @on_text_message
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        return await self.process_message(bot, message, "文本消息")

    @on_image_message
    async def handle_image(self, bot: WechatAPIClient, message: dict):
        """处理图片消息"""
        return await self.process_message(bot, message, "图片")

    @on_video_message
    async def handle_video(self, bot: WechatAPIClient, message: dict):
        """处理视频消息"""
        return await self.process_message(bot, message, "视频")

    @on_file_message
    async def handle_file(self, bot: WechatAPIClient, message: dict):
        """处理文件消息"""
        return await self.process_message(bot, message, "文件")
        
    @on_voice_message
    async def handle_voice(self, bot: WechatAPIClient, message: dict):
        """处理语音消息"""
        return await self.process_message(bot, message, "语音")
        
    @on_emoji_message
    async def handle_emoji(self, bot: WechatAPIClient, message: dict):
        """处理表情消息"""
        return await self.process_message(bot, message, "表情")
        
    @on_quote_message
    async def handle_quote(self, bot: WechatAPIClient, message: dict):
        """处理引用消息"""
        return await self.process_message(bot, message, "引用消息")
        
    @on_pat_message
    async def handle_pat(self, bot: WechatAPIClient, message: dict):
        """处理拍一拍消息"""
        return await self.process_message(bot, message, "拍一拍") 