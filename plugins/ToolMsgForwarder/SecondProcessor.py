# SecondProcessor.py - ToolMsgForwarder插件的二次处理扩展
from loguru import logger
import json
import datetime
import os
import re
import tomllib
import urllib.parse
import aiohttp
import requests
from utils.plugin_base import PluginBase

# 添加版本号常量，每次修改代码后递增
SECOND_PROCESSOR_VERSION = "1.6.5"  # 修复淘口令匹配和重复处理器问题

import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SecondProcessor(PluginBase):
    """
    ToolMsgForwarder的消息二次处理插件
    
    功能：
    1. 通用链接自动转链（返利功能）- 支持淘宝、京东等多种链接
    """
    description = "微信消息转发处理器 - 使用ToolMsgForwarder钩子系统进行消息二次处理"
    author = "ai"
    version = "1.5.0"

    def __init__(self):
        super().__init__()
        self.forwarder = None
        self.config = None
        self._initialized = False

        self._load_config()
        self._initialized = True
        logger.info(f"[SecondProcessor] 初始化完成，版本: {SECOND_PROCESSOR_VERSION}")

    def _load_config(self):
        """加载配置文件"""
        try:
            # 初始化默认配置
            self.config = {
                "enable": True,
                "rebate": {
                    "enable": True,  # 是否启用转链功能
                    "prepend_converted_tag": True,  # 是否在转链消息前添加[已转链]标签
                    "appkey": "2a77607fa088417a8fcb257d1fbb3088",  # 折淘客的对接秘钥appkey
                    "sid": "185073",  # 添加sid参数
                    "union_id": "2036757202",  # 京东联盟ID
                    "pid": "mm_375930105_2518750017_111777500003",  # 淘宝联盟pid
                }
            }
            main_config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            logger.info(f"[SecondProcessor] 尝试从主配置文件加载: {os.path.abspath(main_config_path)}")

            if os.path.exists(main_config_path):
                with open(main_config_path, "rb") as f:
                    toml_data = tomllib.loads(f.read().decode('utf-8'))
                tmf_config = toml_data.get("ToolMsgForwarder", {})
                main_sp_config = tmf_config.get("second_processor", {})
                if "enable" in main_sp_config:
                    self.config["enable"] = main_sp_config["enable"]
                rebate_config = main_sp_config.get("rebate", {})
                for key in ["appkey", "sid", "union_id", "pid", "prepend_converted_tag"]:
                    if key in rebate_config:
                        self.config["rebate"][key] = rebate_config[key]
        except Exception as e:
            logger.error(f"[SecondProcessor] 加载配置文件时发生错误: {str(e)}")
            import traceback
            logger.error(f"[SecondProcessor] 错误堆栈: {traceback.format_exc()}")

    async def on_plugins_loaded(self, plugins_map):
        """当所有插件加载完成后，注册处理器"""
        if "ToolMsgForwarder" not in plugins_map:
            logger.error("[SecondProcessor] 未找到ToolMsgForwarder插件，无法注册处理器")
            return

        self.forwarder = plugins_map["ToolMsgForwarder"]
        logger.info(f"[SecondProcessor] 找到ToolMsgForwarder插件")

        # 检查是否有需要注册的处理器
        if not self.config or not self.config["enable"]:
            logger.info("[SecondProcessor] 插件已禁用，不注册处理器")
            return

        # 检查转链必要参数
        if self.config["rebate"]["enable"] and (not self.config["rebate"]["appkey"] or not self.config["rebate"]["pid"]):
            logger.error(f"[SecondProcessor] 转链功能已启用，但缺少必要参数: appkey='{self.config['rebate']['appkey']}', pid='{self.config['rebate']['pid']}'")
            logger.error(f"[SecondProcessor] 请检查配置文件中的appkey和pid设置")

        # 注册处理器
        self.register_to_forwarder(self.forwarder)

    def register_to_forwarder(self, forwarder):
        """主动向ToolMsgForwarder注册处理器"""
        logger.info(f"[SecondProcessor] 正在注册处理器")

        try:
            if not hasattr(forwarder, 'register_processor'):
                logger.error(f"[SecondProcessor] ToolMsgForwarder没有register_processor方法")
                return False

            # 确保转链配置有效
            if not self.config or not self.config.get("rebate", {}).get("enable", False):
                logger.warning(f"[SecondProcessor] 转链功能未启用，不注册处理器")
                return False

            # 检查必要的配置参数
            rebate_config = self.config["rebate"]
            missing_params = []

            if not rebate_config.get("appkey"):
                missing_params.append("appkey")
            if not rebate_config.get("pid"):
                missing_params.append("pid")

            if missing_params:
                logger.error(f"[SecondProcessor] 缺少必要的转链参数: {', '.join(missing_params)}")
                return False

            # 先取消注册，避免重复
            if hasattr(forwarder, 'unregister_processor'):
                forwarder.unregister_processor("before_forward", self.convert_links)
                logger.info(f"[SecondProcessor] 已取消之前的注册（如果有）")

            # 注册转链处理器
            forwarder.register_processor("before_forward", self.convert_links)
            logger.info(f"[SecondProcessor] 注册转链钩子成功")

            # 检查是否注册成功
            if hasattr(forwarder, 'msg_processors'):
                before_forward_processors = forwarder.msg_processors.get("before_forward", [])
                processor_names = [p.__name__ for p in before_forward_processors]
                logger.info(f"[SecondProcessor] 当前 before_forward 处理器: {processor_names}")

            # 保存forwarder引用，用于后续卸载
            self.forwarder = forwarder
            return True
        except Exception as e:
            logger.error(f"[SecondProcessor] 注册处理器时出错: {e}")
            return False

    def check_for_matches(self, content):
        """
        检查内容中是否包含需要转链的模式
        返回: (bool, str) - 是否匹配到，匹配到的类型描述
        """
        logger.info(f"[SecondProcessor] 开始检查内容匹配: {content}")

        # 淘口令匹配模式1：匹配类似￥...￥的格式
        pattern_tkl1 = re.compile(r"([¥￥$].*?[¥￥$])")  # 以货币符号开头和结尾的淘口令
        tkl1_matches = pattern_tkl1.findall(content)
        if tkl1_matches:
            logger.info(f"[SecondProcessor] 匹配到淘口令模式1: {tkl1_matches}")
            return True, "淘口令模式1"

        # 淘口令匹配模式2：匹配类似￥.../的格式
        pattern_tkl2 = re.compile(r"([¥￥$].*?[/\\])")  # 以货币符号开头，以斜杠结尾的淘口令
        tkl2_matches = pattern_tkl2.findall(content)
        logger.info(f"[SecondProcessor] 淘口令模式2匹配结果: {tkl2_matches}")
        if tkl2_matches:
            logger.info(f"[SecondProcessor] 匹配到淘口令模式2: {tkl2_matches}")
            return True, "淘口令模式2"

        # 淘口令匹配模式3：匹配类似((...://的格式
        pattern_tkl3 = re.compile(r"(\(\(.*?://)")  # 以双括号开头，包含://的淘口令
        tkl3_matches = pattern_tkl3.findall(content)
        if tkl3_matches:
            logger.info(f"[SecondProcessor] 匹配到淘口令模式3: {tkl3_matches}")
            return True, "淘口令模式3"

        # 淘口令匹配模式4：匹配类似(MQ1Vdv5zF2C) CZ000的格式
        pattern_tkl4 = re.compile(r"\(([a-zA-Z0-9]{10,})\)")  # 括号内的10位以上字母数字组合
        tkl4_matches = pattern_tkl4.findall(content)
        if tkl4_matches:
            logger.info(f"[SecondProcessor] 匹配到淘口令模式4: {tkl4_matches}")
            return True, "淘口令模式4"

        # 链接匹配模式1：匹配淘宝链接
        pattern_taobao_link = re.compile(r"https?://(s\.click\.taobao\.com|m\.tb\.cn)/[^\s<]*")  # 淘宝短链接或移动端链接
        taobao_links = pattern_taobao_link.findall(content)
        if taobao_links:
            logger.info(f"[SecondProcessor] 匹配到淘宝链接: {taobao_links}")
            return True, "淘宝链接"

        # 链接匹配模式2：匹配京东链接
        pattern_jd_link = re.compile(r"https?://u\.jd\.com/[A-Za-z0-9]+")  # 京东短链接
        jd_links = pattern_jd_link.findall(content)
        if jd_links:
            logger.info(f"[SecondProcessor] 匹配到京东链接: {jd_links}")
            return True, "京东链接"

        logger.info(f"[SecondProcessor] 未匹配到任何模式")
        return False, "无匹配"

    async def convert_links(self, bot, context, rule):
        """监听转发消息并转链"""
        logger.info(f"[SecondProcessor] convert_links被调用! context类型: {type(context)}")

        if not self.config or not self.config["rebate"]["enable"]:
            logger.info(f"[SecondProcessor] 转链功能未启用，跳过处理")
            return context

        # 检查是否包含内容
        if not isinstance(context, dict) or "content_to_send" not in context:
            logger.info(f"[SecondProcessor] context不是字典或不包含content_to_send，跳过处理")
            return context

        # 检查是否为文本消息
        if context.get("msg_type") != "text":
            logger.info(f"[SecondProcessor] 不是文本消息，跳过处理")
            return context

        content = context["content_to_send"]
        logger.info(f"[SecondProcessor] 原始内容: {content}")

        # 检查消息是否已经被处理过
        if content.startswith("[已转链]"):
            logger.info(f"[SecondProcessor] 消息已经被处理过，跳过处理")
            return context

        try:
            # 检查是否有匹配的内容需要转链
            has_match, match_type = self.check_for_matches(content)
            logger.info(f"[SecondProcessor] 匹配结果: has_match={has_match}, match_type={match_type}")

            # 如果没有匹配到任何模式，跳过处理
            if not has_match:
                logger.info(f"[SecondProcessor] 未检测到任何指定格式的链接或淘口令，跳过处理")
                return context

            logger.info(f"[SecondProcessor] 检测到匹配类型: {match_type}，开始转链")

            # 一次性转换所有链接
            converted_content = self.convert_taobao_link(content)
            logger.info(f"[SecondProcessor] 转链结果: {converted_content}")

            if converted_content and converted_content != content:
                if self.config["rebate"].get("prepend_converted_tag", True):
                    # 检查是否已经有[已转链]标签，避免重复添加
                    if not converted_content.startswith("[已转链]"):
                        converted_content = "[已转链] " + converted_content
                context["content_to_send"] = converted_content
                logger.info(f"[SecondProcessor] 最终处理结果: {converted_content}")
            else:
                logger.info(f"[SecondProcessor] 转链结果与原文相同或为空，保持原文不变")
        except Exception as e:
            logger.error(f"[SecondProcessor] 转换链接时发生错误: {str(e)}")
            import traceback
            logger.error(f"[SecondProcessor] 错误堆栈: {traceback.format_exc()}")
        return context

    def convert_taobao_link(self, text):
        """
        调用折淘客API进行批量转链
        """
        try:
            url = "https://api.zhetaoke.cn:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

            # 必填参数
            params = {
                "appkey": self.config["rebate"]["appkey"],  # 折淘客的对接秘钥appkey
                "sid": self.config["rebate"]["sid"],  # 添加sid参数
                "unionId": self.config["rebate"]["union_id"],  # 京东联盟ID
                "pid": self.config["rebate"]["pid"],  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
                "tkl": urllib.parse.quote(text),  # 需要转换的文本，进行URL编码
            }

            logger.info(f"[SecondProcessor] 发送转链请求: {url}")

            # 发送请求
            response = requests.get(url, params=params, verify=False)

            # 处理响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    logger.info(f"[SecondProcessor] API响应结果: {result}")
                    if result.get("status") == 200:
                        return result.get("content", "")
                    else:
                        logger.error(f"[SecondProcessor] 转链失败: {result.get('status')}, 消息: {result.get('content', '')}")
                        return text  # 转链失败，返回原文
                except json.JSONDecodeError:
                    logger.error(f"[SecondProcessor] 响应解析失败")
                    return text
            else:
                logger.error(f"[SecondProcessor] 请求失败: {response.status_code}")
                return text
        except Exception as e:
            logger.error(f"[SecondProcessor] 批量转链时发生错误: {str(e)}")
            import traceback
            logger.error(f"[SecondProcessor] 错误堆栈: {traceback.format_exc()}")
            return text

    def on_unload(self):
        """插件卸载时，取消注册处理器"""
        logger.info(f"[SecondProcessor] 开始卸载插件")

        try:
            if not self.forwarder:
                logger.info(f"[SecondProcessor] 没有已注册的forwarder，无需卸载")
                return

            # 取消注册转链处理器
            if hasattr(self.forwarder, 'unregister_processor'):
                self.forwarder.unregister_processor("before_forward", self.convert_links)
                logger.info(f"[SecondProcessor] 已取消注册转链处理器")
            else:
                logger.warning(f"[SecondProcessor] forwarder没有unregister_processor方法，无法卸载处理器")
        except Exception as e:
            logger.error(f"[SecondProcessor] 卸载插件时发生错误: {e}")
        finally:
            # 清理资源
            self.forwarder = None
            logger.info(f"[SecondProcessor] 插件卸载完成")
