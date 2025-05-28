import tomllib
import xml.etree.ElementTree as ET
from datetime import datetime
import os

from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import on_system_message
from utils.plugin_base import PluginBase


class ToolGroupWelcome(PluginBase):
    description = "进群欢迎"
    author = "xxxbot"
    version = "1.5.5"  # 更新版本号，添加调试日志

    def __init__(self):
        super().__init__()

        with open("plugins/ToolGroupWelcome/config.toml", "rb") as f:
            plugin_config = tomllib.load(f)

        config = plugin_config["ToolGroupWelcome"]

        self.enable = config["enable"]
        logger.debug(f"插件状态: {'启用' if self.enable else '禁用'}")
        
        # 加载群聊配置
        self.group_configs = config.get("groups", {})
        logger.debug(f"已配置的群聊数量: {len(self.group_configs)}")
        for group_id, group_config in self.group_configs.items():
            logger.debug(f"群 {group_id} 配置: {group_config}")
                
        # 读取协议版本
        try:
            with open("main_config.toml", "rb") as f:
                main_config = tomllib.load(f)
                self.protocol_version = main_config.get("Protocol", {}).get("version", "855")
                logger.debug(f"当前协议版本: {self.protocol_version}")
        except Exception as e:
            logger.warning(f"读取协议版本失败，将使用默认版本849: {e}")
            self.protocol_version = "849"

    def _get_group_config(self, group_id: str) -> dict:
        """获取群聊配置，如果不存在则返回None"""
        if group_id not in self.group_configs:
            logger.debug(f"群 {group_id} 未配置欢迎语")
            return None
            
        group_config = self.group_configs[group_id]
        config = {
            "welcome-message": group_config["welcome-message"],
            "url": group_config["url"],
            "message-type": group_config.get("message-type", "text")  # 默认使用文字消息
        }
        logger.debug(f"获取到群 {group_id} 的配置: {config}")
        return config

    @on_system_message
    async def group_welcome(self, bot: WechatAPIClient, message: dict):
        logger.debug(f"收到系统消息: {message}")

        if not self.enable:
            logger.debug("插件未启用，继续执行其他插件")
            return True

        if not message["IsGroup"]:
            logger.debug("非群聊消息，继续执行其他插件")
            return True

        # 获取群聊配置，如果群聊未配置则继续执行其他插件
        group_config = self._get_group_config(message["FromWxid"])
        if group_config is None:
            logger.debug(f"群 {message['FromWxid']} 未配置欢迎语，继续执行其他插件")
            return True

        xml_content = str(message["Content"]).strip().replace("\n", "").replace("\t", "")
        logger.debug(f"解析XML内容: {xml_content}")
        
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logger.error(f"XML解析失败: {e}")
            return True

        if root.tag != "sysmsg":
            logger.debug("非系统消息，继续执行其他插件")
            return True

        # 检查是否是进群消息
        if root.attrib.get("type") == "sysmsgtemplate":
            sys_msg_template = root.find("sysmsgtemplate")
            if sys_msg_template is None:
                logger.debug("未找到sysmsgtemplate节点")
                return True

            template = sys_msg_template.find("content_template")
            if template is None:
                logger.debug("未找到content_template节点")
                return True

            template_type = template.attrib.get("type")
            logger.debug(f"模板类型: {template_type}")
            
            if template_type not in ["tmpl_type_profile", "tmpl_type_profilewithrevoke"]:
                logger.debug(f"不支持的模板类型: {template_type}")
                return True

            template_text = template.find("template").text
            logger.debug(f"模板文本: {template_text}")

            if '"$names$"加入了群聊' in template_text:  # 直接加入群聊
                logger.debug("检测到直接加入群聊")
                new_members = self._parse_member_info(root, "names")
            elif '"$username$"邀请"$names$"加入了群聊' in template_text:  # 通过邀请加入群聊
                logger.debug("检测到通过邀请加入群聊")
                new_members = self._parse_member_info(root, "names")
            elif '你邀请"$names$"加入了群聊' in template_text:  # 自己邀请成员加入群聊
                logger.debug("检测到自己邀请成员加入群聊")
                new_members = self._parse_member_info(root, "names")
            elif '"$adder$"通过扫描"$from$"分享的二维码加入群聊' in template_text:  # 通过二维码加入群聊
                logger.debug("检测到通过二维码加入群聊")
                new_members = self._parse_member_info(root, "adder")
            elif '"$adder$"通过"$from$"的邀请二维码加入群聊' in template_text:
                logger.debug("检测到通过邀请二维码加入群聊")
                new_members = self._parse_member_info(root, "adder")
            else:
                logger.warning(f"未知的入群方式: {template_text}")
                return True

            if not new_members:
                logger.debug("未找到新成员信息")
                return True

            logger.debug(f"找到新成员: {new_members}")
            message_type = group_config["message-type"]
            logger.debug(f"消息类型: {message_type}")

            for member in new_members:
                wxid = member["wxid"]
                nickname = member["nickname"]
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logger.debug(f"处理新成员: {nickname}({wxid})")

                try:
                    if message_type == "card":
                        logger.debug("发送卡片欢迎消息")
                        await self._send_welcome_card(bot, message["FromWxid"], nickname, group_config, now)
                    else:
                        logger.debug("发送文字欢迎消息")
                        await self._send_welcome_text(bot, message["FromWxid"], nickname, group_config, now)
                except Exception as e:
                    logger.error(f"发送欢迎消息失败: {e}")
                    return True

            logger.debug("欢迎消息发送完成，停止执行其他插件")
            return False

        logger.debug("其他系统消息，继续执行其他插件")
        return True

    async def _send_welcome_card(self, bot: WechatAPIClient, to_wxid: str, nickname: str, group_config: dict, now: str):
        """发送卡片欢迎消息"""
        try:
            # 获取用户头像
            logger.debug(f"开始获取用户 {nickname} 的头像")
            avatar_url = await self._get_member_avatar(bot, to_wxid, nickname)
            logger.debug(f"获取到头像URL: {avatar_url}")
            
            title = f"👏欢迎 {nickname} 加入群聊！🎉"
            description = f"{group_config['welcome-message']}\n⌚时间：{now}"
            
            logger.debug(f"准备发送卡片消息: 标题=「{title}」 描述=「{description}」 链接=「{group_config['url']}」")
            
            simple_xml = f"""<appmsg><title>{title}</title><des>{description}</des><type>5</type><url>{group_config['url']}</url><thumburl>{avatar_url}</thumburl></appmsg>"""
            
            await self._send_app_message_direct(bot, to_wxid, simple_xml, 5)
            logger.debug("卡片消息发送成功")
        except Exception as e:
            logger.error(f"发送卡片欢迎消息失败: {e}")
            # 如果卡片发送失败，尝试发送文字消息
            logger.debug("尝试发送文字消息作为备选")
            await self._send_welcome_text(bot, to_wxid, nickname, group_config, now)

    async def _send_welcome_text(self, bot: WechatAPIClient, to_wxid: str, nickname: str, group_config: dict, now: str):
        """发送文字欢迎消息"""
        try:
            # 只发送welcome-message，并将{nickname}替换为实际昵称
            welcome_text = group_config['welcome-message'].replace("{nickname}", nickname)
            
            logger.debug(f"准备发送文字消息: {welcome_text}")
            await bot.send_text_message(to_wxid, welcome_text)
            logger.debug("文字消息发送成功")
        except Exception as e:
            logger.error(f"发送文字欢迎消息失败: {e}")

    async def _get_member_avatar(self, bot: WechatAPIClient, group_id: str, nickname: str) -> str:
        """获取群成员头像"""
        try:
            import aiohttp
            import json

            json_param = {"QID": group_id, "Wxid": bot.wxid}
            api_base = f"http://{bot.ip}:{bot.port}"
            api_prefix = "/api" if self.protocol_version != "849" else "/VXAPI"
            
            logger.debug(f"请求群成员信息: {json_param}")
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"{api_base}{api_prefix}/Group/GetChatRoomMemberDetail",
                    json=json_param,
                    headers={"Content-Type": "application/json"}
                )

                if response.status == 200:
                    json_resp = await response.json()
                    if json_resp.get("Success"):
                        group_data = json_resp.get("Data", {})
                        if "NewChatroomData" in group_data and "ChatRoomMember" in group_data["NewChatroomData"]:
                            group_members = group_data["NewChatroomData"]["ChatRoomMember"]
                            if isinstance(group_members, list) and group_members:
                                for member_data in group_members:
                                    member_wxid = member_data.get("UserName") or member_data.get("Wxid") or member_data.get("wxid") or ""
                                    if member_wxid == nickname:
                                        avatar_url = member_data.get("BigHeadImgUrl") or member_data.get("SmallHeadImgUrl") or ""
                                        logger.debug(f"找到成员头像: {avatar_url}")
                                        return avatar_url
                    else:
                        logger.warning(f"获取群成员信息失败: {json_resp}")
                else:
                    logger.warning(f"获取群成员信息请求失败: HTTP {response.status}")
        except Exception as e:
            logger.warning(f"获取用户头像失败: {e}")
        return ""

    async def _send_app_message_direct(self, bot: WechatAPIClient, to_wxid: str, xml: str, msg_type: int):
        """直接调用SendApp API发送消息"""
        try:
            # 确定API基础路径
            api_base = f"http://{bot.ip}:{bot.port}"
            
            # 根据协议版本选择正确的API前缀
            api_prefix = "/api" if self.protocol_version != "849" else "/VXAPI"
            
            # 构造请求参数
            import aiohttp
            import json
            
            data = {
                "ToWxid": to_wxid,
                "Type": msg_type,
                "Wxid": bot.wxid,
                "Xml": xml
            }
            
            logger.debug(f"调用SendApp API发送卡片消息: {data}")
            
            async with aiohttp.ClientSession() as session:
                response = await session.post(
                    f"{api_base}{api_prefix}/Msg/SendApp",
                    json=data,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status == 200:
                    resp_data = await response.json()
                    logger.debug(f"发送卡片消息成功: {resp_data}")
                    return resp_data
                else:
                    logger.error(f"发送卡片消息失败: HTTP状态码 {response.status}")
                    response_text = await response.text()
                    logger.error(f"错误详情: {response_text}")
                    return None
        except Exception as e:
            logger.error(f"调用SendApp API发送卡片消息失败: {e}")
            return None

    @staticmethod
    def _parse_member_info(root: ET.Element, link_name: str = "names") -> list[dict]:
        """解析新成员信息"""
        new_members = []
        try:
            # 查找指定链接中的成员列表
            names_link = root.find(f".//link[@name='{link_name}']")
            if names_link is None:
                logger.debug(f"未找到link节点: {link_name}")
                return new_members

            memberlist = names_link.find("memberlist")
            if memberlist is None:
                logger.debug("未找到memberlist节点")
                return new_members

            for member in memberlist.findall("member"):
                username = member.find("username").text
                nickname = member.find("nickname").text
                new_members.append({
                    "wxid": username,
                    "nickname": nickname
                })
                logger.debug(f"解析到成员: {nickname}({username})")

        except Exception as e:
            logger.warning(f"解析新成员信息失败: {e}")

        return new_members