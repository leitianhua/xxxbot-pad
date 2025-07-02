import os
import re
import json
import aiohttp
import tomllib
import urllib.parse
import requests
import asyncio
import sqlite3
import datetime
import traceback
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger
from pathlib import Path
from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message, schedule
from utils.plugin_base import PluginBase
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 全局变量，用于存储bot实例引用
_bot_instance = None


# 设置bot实例的函数
def set_bot_instance(bot):
    global _bot_instance
    _bot_instance = bot
    logger.info(f"已设置全局bot实例: {bot}")


class ToolLinkRebate(PluginBase):
    """商品转链返利插件"""
    description = "商品转链，线报推送（淘宝、京东）"
    author = "lei"
    version = "1.3.0"

    def __init__(self):
        super().__init__()
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        logger.debug(f"正在加载配置文件: {config_path}")

        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            logger.debug(f"配置文件加载成功: {config}")
            # 初始化临时目录
            self.plugin_dir = Path(os.path.dirname(os.path.abspath(__file__)))
            self.temp_dir = self.plugin_dir / "temp"
            self._ensure_temp_dir()

            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)  # 是否启用插件
            self.appkey = basic_config.get("appkey", "")  # 折淘客appkey
            self.sid = basic_config.get("sid", "")  # 折淘客sid
            self.union_id = basic_config.get("union_id", "")  # 京东联盟ID
            self.pid = basic_config.get("pid", "")  # 淘宝联盟pid
            self.group_mode = basic_config.get("group_mode", "all")  # 群组控制模式
            self.group_list = basic_config.get("group_list", [])  # 群组/用户列表
            self.send_message_on_success = basic_config.get("send_message_on_success", True)  # 基础转链成功后是否发送消息

            # 线报监听配置
            xianbao_config = config.get("xianbao", {})
            self.xianbao_enable = xianbao_config.get("enable", False)  # 是否启用线报监听
            self.xianbao_interval = xianbao_config.get("interval", 300)  # 线报监听间隔（秒）
            self.xianbao_keywords = xianbao_config.get("keywords", [])  # 线报关键词
            self.xianbao_receivers = xianbao_config.get("receivers", [])  # 线报接收者列表
            # 线报过滤关键词，包含这些关键词的线报将被跳过
            self.xianbao_filter_keywords = xianbao_config.get("filter_keywords", [])
            # 线报数据保留分钟数
            self.data_retention_minutes = xianbao_config.get("data_retention_minutes", 180)  # 默认3小时
            # 线报转链成功后是否发送消息
            self.xianbao_send_message_on_success = xianbao_config.get("send_message_on_success", True)

            # 记录上次执行时间
            self.last_execution_time = datetime.datetime.now()

            # 编译正则表达式
            self.link_patterns = {
                "taobao": re.compile(r"https?://(s\.click\.taobao\.com|m\.tb\.cn)/[^\s<]*"),  # 淘宝链接
                "jd": re.compile(r"https?://u\.jd\.com/[A-Za-z0-9]+"),  # 京东链接
                "tkl1": re.compile(r"[¥￥$/].*?[¥￥$/]"),  # 淘口令模式1
                # "tkl2": re.compile(r"([¥￥$].*?[/\\])"),  # 淘口令模式2
                "tkl3": re.compile(r"(\(\(.*?://)"),  # 淘口令模式3
                "tkl4": re.compile(r"\(([a-zA-Z0-9]{10,})\)")  # 淘口令模式4
            }

            logger.success(f"商品转链返利插件配置加载成功")
            logger.info(f"群组控制模式: {self.group_mode}")
            logger.info(f"群组/用户列表: {self.group_list}")
            logger.info(f"基础转链成功后是否发送消息: {self.send_message_on_success}")

            if self.xianbao_enable:
                logger.success(f"线报监听已启用，监听间隔: {self.xianbao_interval}秒")
                logger.success(f"线报关键词: {self.xianbao_keywords}")
                logger.success(f"线报接收者: {self.xianbao_receivers}")
                logger.success(f"线报过滤关键词: {self.xianbao_filter_keywords}")
                logger.success(f"线报数据保留分钟数: {self.data_retention_minutes}")
                logger.success(f"线报转链成功后是否发送消息: {self.xianbao_send_message_on_success}")

                # 初始化线报数据库
                self._init_xianbao_database()
            else:
                logger.warning("线报监听功能未启用")
        except Exception as e:
            logger.error(f"加载商品转链返利插件配置失败: {str(e)}")
            logger.error(traceback.format_exc())
            self.enable = False
            self.xianbao_enable = False

    def _ensure_temp_dir(self):
        """确保临时目录存在"""
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[ToolParser] 创建临时目录失败: {e}")

    def _init_xianbao_database(self):
        """初始化线报数据库"""
        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
            logger.debug(f"初始化线报数据库: {db_path}")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 创建表（如果不存在）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS xianbao (
                pic TEXT PRIMARY KEY,
                content TEXT,
                content_converted TEXT,
                urls TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_pushed INTEGER DEFAULT 0
            )
            ''')

            # 尝试清理过期的数据
            self._clean_old_xianbao_data(conn)

            conn.commit()
            conn.close()
            logger.success("线报数据库初始化成功")
        except Exception as e:
            logger.error(f"初始化线报数据库失败: {str(e)}")
            logger.error(traceback.format_exc())

    def _clean_old_xianbao_data(self, conn=None):
        """清理过期的线报数据"""
        try:
            # 如果没有传入连接，则创建新连接
            close_conn = False
            if conn is None:
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
                conn = sqlite3.connect(db_path)
                close_conn = True

            cursor = conn.cursor()

            # 获取配置的分钟数前的日期
            minutes_ago = (datetime.datetime.now() - datetime.timedelta(minutes=self.data_retention_minutes)).strftime('%Y-%m-%d %H:%M:%S')

            # 查询要删除的记录数量
            cursor.execute("SELECT COUNT(*) FROM xianbao WHERE created_at < ?", (minutes_ago,))
            count = cursor.fetchone()[0]

            # 删除过期的数据
            cursor.execute("DELETE FROM xianbao WHERE created_at < ?", (minutes_ago,))

            # 提交事务
            conn.commit()

            if count > 0:
                logger.info(f"已清理 {count} 条{self.data_retention_minutes}分钟前的线报数据")

            # 如果是新创建的连接，则关闭
            if close_conn:
                conn.close()

        except Exception as e:
            logger.error(f"清理线报数据时发生错误: {str(e)}")
            logger.error(traceback.format_exc())

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
            return True

        # 使用折淘客API进行批量转链
        success, converted_content, error_msg = self.convert_links(content)

        # 根据转链结果决定是否发送消息
        if success:
            # 转链成功，检查是否需要发送转换后的内容
            if self.send_message_on_success:
                await bot.send_text_message(from_user, converted_content)
            return False
        else:
            # 转链失败，发送错误消息
            await bot.send_text_message(from_user, f"【转链失败】{error_msg}\n\n{content}")
            return False

    def convert_links(self, text: str) -> Tuple[bool, str, str]:
        """
        调用折淘客API进行批量转链
        
        返回值:
        - Tuple[bool, str, str]: (是否成功, 转链内容/原内容, 错误消息)
          - 成功时: (True, 转链内容, "")
          - 失败时: (False, 原内容, 错误消息)
        """
        # 如果是拼多多不转链
        if 'pinduoduo' in text:
            return False, text, "不支持pdd"
        try:
            url = "https://api.zhetaoke.cn:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

            # 必填参数
            params = {
                "appkey": self.appkey,  # 折淘客的对接秘钥appkey
                "sid": self.sid,  # 添加sid参数
                "unionId": self.union_id,  # 京东联盟ID
                "pid": self.pid,  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
                "tkl": urllib.parse.quote(text),  # 需要转换的文本，进行URL编码
            }

            # 发送请求
            response = requests.get(url, params=params, verify=False)

            # 处理响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get("status") == 200:
                        converted_content = result.get("content", "")
                        # 检查转换后的内容是否与原内容不同
                        if converted_content and converted_content != text:
                            return True, converted_content, ""
                        else:
                            return False, text, "转链后内容无变化"
                    else:
                        error_msg = result.get('content', '未知错误')
                        logger.error(f"转链失败: {result.get('status')}, 消息: {error_msg}")
                        if result.get("status") == 301:
                            return False, text, "无法识别链接"
                        else:
                            return False, text, f"状态码: {result.get('status')}, {error_msg}"
                except json.JSONDecodeError:
                    logger.error(f"响应解析失败")
                    return False, text, "响应解析错误"
            else:
                logger.error(f"请求失败: {response.status_code}")
                return False, text, f"HTTP请求失败: {response.status_code}"
        except Exception as e:
            logger.error(f"批量转链时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return False, text, f"系统错误: {str(e)}"

    def get_xianbao_data(self, keyword):
        """获取线报数据"""
        url = "https://api.zhetaoke.com:20001/api/api_xianbao.ashx"

        # 必填参数
        params = {
            "appkey": self.appkey,
            "id": None,
            "type": None,
            "page": 1,
            "page_size": 1000,
            "msg": 1,
            "interval": self.data_retention_minutes - 20,
            "q": keyword,
        }

        try:
            # 发送请求，禁用SSL验证
            response = requests.get(url, params=params, verify=False)

            # 处理响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    # logger.debug(f"线报API响应: {result}")
                    if result.get("status") == 200:
                        data = result.get("msg", [])
                        return data
                    else:
                        # 301 表示没有数据
                        if result.get("status") != 301:
                            logger.error(f"获取[{keyword}]线报失败: {result.get('status')}, 消息: {result.get('content', '')}")
                        return []
                except json.JSONDecodeError:
                    logger.error("线报响应解析失败")
                    logger.error(traceback.format_exc())
                    return []
            else:
                logger.error(f"线报请求失败: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"获取线报数据时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def _process_xianbao_content(self, content):
        """
        处理线报内容：提取URL、格式化内容、转换链接
        
        返回:
            Tuple[List[str], str, bool, str, str]: (图片URL列表, URL的JSON字符串, 是否转换成功, 格式化后的内容, 转换后的内容)
        """
        # 提取图片URL
        urls = re.findall(r'\[url=(.*?)\]', content)
        urls_json = json.dumps(urls) if urls else ""

        # 格式化原始内容，去除图片标签等
        formatted_content = self.format_xianbao_content(content)

        # 进行内容转换
        success, converted_content, error_msg = self.convert_links(formatted_content)

        if not success:
            logger.warning(f"线报内容转换失败: {error_msg}, 内容: {formatted_content}")
            converted_content = ""  # 转换失败时设为空字符串

        return urls, urls_json, success, formatted_content, converted_content

    def save_xianbao_to_database(self, data_list):
        """保存线报数据到数据库，返回新增的线报数量"""
        if not data_list:
            return 0

        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            new_count = 0

            for item in data_list:
                pic = item.get('pic', '')

                # 如果pic为空，则跳过该记录
                if not pic:
                    continue

                content = item.get('content', '')

                # 检查记录是否已存在
                cursor.execute("SELECT content_converted, is_pushed FROM xianbao WHERE pic = ?", (pic,))
                existing_record = cursor.fetchone()

                if existing_record:
                    # 记录已存在，检查是否未推送且没有已转文本内容
                    existing_content_converted, is_pushed = existing_record
                    if is_pushed == 0 and (not existing_content_converted or existing_content_converted == ""):
                        # 需要更新记录，处理内容
                        urls, urls_json, success, formatted_content, converted_content = self._process_xianbao_content(content)

                        # 只有转换成功时才更新
                        if success:
                            try:
                                cursor.execute('''
                                UPDATE xianbao SET 
                                    content = ?,
                                    content_converted = ?,
                                    urls = ?
                                WHERE pic = ?
                                ''', (
                                    formatted_content,
                                    converted_content,
                                    urls_json,
                                    pic
                                ))
                                logger.info(f"更新未推送且无已转文本内容的记录: {pic}")
                                # 更新记录不计入新增数量
                            except Exception as e:
                                logger.error(f"更新记录失败: {str(e)}, pic: {pic}")
                    else:
                        # 记录已存在且不需要更新
                        logger.debug(f"线报已存在且不需要更新: {content[:80]}")
                else:
                    # 记录不存在，处理内容并插入新记录
                    urls, urls_json, success, formatted_content, converted_content = self._process_xianbao_content(content)

                    # 无论转换是否成功，都插入记录
                    try:
                        cursor.execute('''
                        INSERT INTO xianbao (
                            pic, content, content_converted, urls, created_at, is_pushed
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ''', (
                            pic,
                            formatted_content,
                            converted_content,
                            urls_json,
                            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            0  # 初始未推送
                        ))
                        # 只有新增记录才计入新增数量
                        new_count += 1
                    except sqlite3.IntegrityError as e:
                        # 如果出现主键冲突，跳过此条记录
                        logger.warning(f"数据库插入冲突: {str(e)}, 线报内容: {formatted_content[:30]}...")

            conn.commit()
            conn.close()
            return new_count
        except Exception as e:
            logger.error(f"保存线报数据时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return 0

    def format_xianbao_content(self, content, keyword=""):
        """
        格式化线报内容：
        1. 将<br />替换为\n
        2. 去除[emoji=XXX]格式的内容
        3. 去除[url=XXX]格式的内容
        """
        # 替换<br />为换行符
        formatted_content = content.replace("<br />", "\n")

        # 去除[emoji=XXX]格式的内容
        formatted_content = re.sub(r'\[emoji=[A-Za-z0-9]+\]', '', formatted_content)

        # 去除[url=XXX]格式的内容
        formatted_content = re.sub(r'\[url=.*?\]', '', formatted_content)

        return formatted_content

    def should_filter_xianbao(self, content):
        """
        检查线报内容是否包含过滤关键词
        
        返回值:
        - Tuple[bool, str]: (是否应该过滤, 匹配的关键词)
          - 应该过滤: (True, 匹配的关键词)
          - 不应该过滤: (False, "")
        """
        if not self.xianbao_filter_keywords:
            return False, ""

        for keyword in self.xianbao_filter_keywords:
            if keyword in content:
                return True, keyword

        return False, ""

    def update_xianbao_push_status(self, pic):
        """更新线报的推送状态"""
        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 更新推送状态
            cursor.execute("UPDATE xianbao SET is_pushed = 1 WHERE pic = ?", (pic,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"更新线报推送状态时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    @schedule(trigger="interval", seconds=20)
    async def xianbao_monitor_task(self, bot):
        """线报监听定时任务"""
        # 计算自上次执行以来经过的时间
        now = datetime.datetime.now()
        time_elapsed = (now - self.last_execution_time).total_seconds()

        # 如果未达到配置的间隔时间，则跳过执行
        if time_elapsed < self.xianbao_interval:
            return

        # 更新上次执行时间
        self.last_execution_time = now

        # 如果线报监听功能未启用，直接返回
        if not self.xianbao_enable:
            logger.warning("线报监听功能未启用，不执行监听任务")
            return

        # 清理过期的数据
        self._clean_old_xianbao_data()
        # 清理缓存图片
        self._clear_temp_cache()

        # 确保接收者列表不为空
        if not self.xianbao_receivers:
            logger.error("线报接收者列表为空，无法发送线报，请检查配置")
            return

        # 1. 获取线报数据并保存到数据库（同时进行内容转换）
        # 在保存过程中会自动检查并更新未推送且无已转文本内容的记录
        new_data_count = 0
        for keyword in self.xianbao_keywords:
            # 调用API获取线报数据
            xianbao_data = self.get_xianbao_data(keyword)

            # 保存到数据库并获取新增的有效线报数量
            new_items_count = self.save_xianbao_to_database(xianbao_data)
            new_data_count += new_items_count
            logger.debug(f"{keyword}-线报数量：{len(xianbao_data)}-新数量：{new_items_count}")

        logger.success(f"共获取到 {new_data_count} 条新线报数据")

        # 2. 获取未推送的线报数据并推送
        unpushed_items = self.get_unpushed_xianbao()
        if unpushed_items:
            logger.success(f"找到 {len(unpushed_items)} 条待推送的线报数据")

            # 处理每条未推送的线报数据
            for item in unpushed_items:
                pic = item['pic']
                content_converted = item['content_converted']
                urls = item['urls']

                # 检查是否包含过滤关键词
                should_filter, filter_keyword = self.should_filter_xianbao(content_converted)
                if should_filter:
                    logger.info(f"线报包含过滤关键词 '{filter_keyword}'，跳过推送并标记为已推送")
                    self.update_xianbao_push_status(pic)
                    continue

                # 构建完整的线报消息
                message = content_converted

                # 发送给所有接收者
                push_success = True
                for receiver in self.xianbao_receivers:
                    try:
                        # 发送文本
                        await bot.send_text_message(receiver, message)

                        # 发送图片
                        for url in urls:
                            image_byte = self._download_http_image(url)
                            if image_byte:
                                await bot.send_image_message(receiver, image_byte)

                    except Exception as e:
                        logger.error(f"发送线报到 {receiver} 失败: {str(e)}")
                        logger.error(traceback.format_exc())
                        push_success = False

                    # 避免发送过快
                    await asyncio.sleep(1)

                # 更新推送状态
                if push_success:
                    self.update_xianbao_push_status(pic)
                    logger.success(f"线报推送成功: {pic}")
        else:
            logger.debug("没有待推送的线报数据")

    def _download_http_image(self, http_url) -> Optional[bytes]:
        """下载图片,返回图片二进制数据"""
        try:
            # 解析图片文件名
            import hashlib
            import base64
            local_path = self.temp_dir / f"""{base64.b32encode(hashlib.sha256(http_url.encode('utf-8')).digest()).decode('ascii').rstrip('=')}.jpg"""

            # 检查本地缓存
            if local_path.exists():
                logger.debug(f"从缓存加载图片: {local_path}")
                return local_path.read_bytes()

            # 网络下载
            logger.debug(f"从网络下载图片: {http_url}")
            response = requests.get(http_url, timeout=10, verify=False)
            response.raise_for_status()

            # 保存到本地
            local_path.write_bytes(response.content)
            return response.content
        except Exception as e:
            logger.error(f"下载图片失败: {e}")
            return None

    def _clear_temp_cache(self):
        """删除temp目录下的所有缓存文件"""
        try:
            if self.temp_dir.exists():
                import shutil
                shutil.rmtree(self.temp_dir)
                self.temp_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"已清空缓存目录: {self.temp_dir}")
        except Exception as e:
            logger.error(f"清空缓存目录失败: {e}")

    def get_unpushed_xianbao(self):
        """获取未推送的线报数据"""
        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 获取所有已转换但未推送的线报数据
            cursor.execute("""
                SELECT pic, content, content_converted, urls 
                FROM xianbao 
                WHERE is_pushed = 0 AND content_converted != ''
            """)
            rows = cursor.fetchall()

            result = []
            for pic, content, content_converted, urls_json in rows:
                urls = json.loads(urls_json) if urls_json else []
                result.append({
                    'pic': pic,
                    'content': content,
                    'content_converted': content_converted,
                    'urls': urls
                })

            conn.close()
            return result
        except Exception as e:
            logger.error(f"获取未推送线报数据时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return []
