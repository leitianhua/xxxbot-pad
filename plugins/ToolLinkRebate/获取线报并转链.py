import os
import re
import json
import tomllib
import urllib.parse

import httpx
import requests
import sqlite3
import datetime
import traceback
from typing import List, Dict, Any, Tuple, Optional
from loguru import logger
from pathlib import Path
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
    description = "商品转链返利插件 - 自动识别淘宝、京东链接并生成带返利的推广链接"
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

            # 线报监听配置
            xianbao_config = config.get("xianbao", {})
            self.xianbao_enable = xianbao_config.get("enable", False)  # 是否启用线报监听
            self.xianbao_interval = xianbao_config.get("interval", 300)  # 线报监听间隔（秒）
            self.xianbao_keywords = xianbao_config.get("keywords", [])  # 线报关键词
            self.xianbao_receivers = xianbao_config.get("receivers", [])  # 线报接收者列表
            # 线报过滤关键词，包含这些关键词的线报将被跳过
            self.xianbao_filter_keywords = xianbao_config.get("filter_keywords", [])
            # 是否显示线报标题
            self.show_title = xianbao_config.get("show_title", False)

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

            if self.xianbao_enable:
                logger.success(f"线报监听已启用，监听间隔: {self.xianbao_interval}秒")
                logger.success(f"线报关键词: {self.xianbao_keywords}")
                logger.success(f"线报接收者: {self.xianbao_receivers}")
                logger.success(f"线报过滤关键词: {self.xianbao_filter_keywords}")
                logger.success(f"是否显示线报标题: {self.show_title}")

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
                code TEXT,
                add_time TEXT,
                type TEXT,
                id TEXT,
                content TEXT,
                plat TEXT,
                pic TEXT PRIMARY KEY,
                num_id TEXT,
                plat2 TEXT,
                type2 TEXT,
                cid1 TEXT,
                cid1_name TEXT,
                cid2 TEXT,
                cid2_name TEXT,
                cid3 TEXT,
                cid3_name TEXT,
                chunwenzi TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            # 尝试清理7天前的数据
            self._clean_old_xianbao_data(conn)

            conn.commit()
            conn.close()
            logger.success("线报数据库初始化成功")
        except Exception as e:
            logger.error(f"初始化线报数据库失败: {str(e)}")
            logger.error(traceback.format_exc())

    def _clean_old_xianbao_data(self, conn=None):
        """清理7天前的线报数据"""
        try:
            # 如果没有传入连接，则创建新连接
            close_conn = False
            if conn is None:
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
                conn = sqlite3.connect(db_path)
                close_conn = True

            cursor = conn.cursor()

            # 获取7天前的日期
            seven_days_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

            # 查询要删除的记录数量
            cursor.execute("SELECT COUNT(*) FROM xianbao WHERE created_at < ?", (seven_days_ago,))
            count = cursor.fetchone()[0]

            # 删除7天前的数据
            cursor.execute("DELETE FROM xianbao WHERE created_at < ?", (seven_days_ago,))

            # 提交事务
            conn.commit()

            if count > 0:
                logger.info(f"已清理 {count} 条7天前的线报数据")

            # 如果是新创建的连接，则关闭
            if close_conn:
                conn.close()

        except Exception as e:
            logger.error(f"清理线报数据时发生错误: {str(e)}")
            logger.error(traceback.format_exc())

    def convert_links(self, text: str) -> Tuple[bool, str, str]:
        """
        调用折淘客API进行批量转链

        返回值:
        - Tuple[bool, str, str]: (是否成功, 转链内容/原内容, 错误消息)
          - 成功时: (True, 转链内容, "")
          - 失败时: (False, 原内容, 错误消息)
        """
        try:
            url = "https://api.zhetaoke.cn:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

            # 必填参数
            params = {
                "appkey": self.appkey,  # 折淘客的对接秘钥appkey
                "sid": self.sid,  # 添加sid参数
                "unionId": self.union_id,  # 京东联盟ID
                "pid": self.pid,  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
                "tkl": text,  # 需要转换的文本，进行URL编码
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
                            logger.success(f"""转链成功:
                                           消息原始内容: {text}
                                           消息转后内容: {converted_content}
                                            """)
                            return True, converted_content, ""
                        else:
                            return False, text, "转链后内容无变化"
                    else:
                        error_msg = result.get('content', '未知错误')
                        logger.error(f"转链失败: {result.get('status')}, 消息: {error_msg}, 消息原始内容: {text}")
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
            "page_size": 200,
            "msg": 1,
            "interval": 1440,
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
                        logger.error(f"获取线报失败: {result.get('status')}, 消息: {result.get('content', '')}")
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

    def save_xianbao_to_database(self, data_list):
        """保存线报数据到数据库，返回新数据列表"""
        if not data_list:
            return []

        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
            # logger.debug(f"保存线报数据到数据库: {db_path}, 数据条数: {len(data_list)}")

            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            new_data_items = []

            for item in data_list:
                pic = item.get('pic', '')

                # 如果pic为空，则跳过该记录
                if not pic:
                    # logger.debug(f"跳过无图片的线报: {item.get('content', '')[:30]}...")
                    continue

                # 检查记录是否已存在（仅使用pic进行去重）
                cursor.execute("SELECT 1 FROM xianbao WHERE pic = ?", (pic,))
                if not cursor.fetchone():
                    try:
                        # 插入新记录
                        cursor.execute('''
                        INSERT INTO xianbao (
                            code, add_time, type, id, content, plat, pic, num_id, 
                            plat2, type2, cid1, cid1_name, cid2, cid2_name, cid3, cid3_name, chunwenzi,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            item.get('code', ''),
                            item.get('add_time', ''),
                            item.get('type', ''),
                            item.get('id', ''),
                            item.get('content', ''),
                            item.get('plat', ''),
                            pic,
                            item.get('num_id', ''),
                            item.get('plat2', ''),
                            item.get('type2', ''),
                            item.get('cid1', ''),
                            item.get('cid1_name', ''),
                            item.get('cid2', ''),
                            item.get('cid2_name', ''),
                            item.get('cid3', ''),
                            item.get('cid3_name', ''),
                            item.get('chunwenzi', ''),
                            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        ))
                        new_data_items.append(item)
                    except sqlite3.IntegrityError as e:
                        # 如果出现主键冲突，跳过此条记录
                        logger.warning(f"数据库插入冲突: {str(e)}, 线报内容: {item.get('content', '')[:30]}...")
                else:
                    # logger.debug(f"线报已存在，跳过: {item.get('content', '')[:30]}...")
                    pass

            conn.commit()
            conn.close()
            return new_data_items
        except Exception as e:
            logger.error(f"保存线报数据时发生错误: {str(e)}")
            logger.error(traceback.format_exc())
            return []

    def format_xianbao_content(self, content, keyword=""):
        """
        格式化线报内容：
        1. 将<br />替换为\n
        2. 去除图片内容
        3. 去除[emoji=XXX]格式的内容
        """
        # 替换<br />为换行符
        formatted_content = content.replace("<br />", "\n")

        # 去除[emoji=XXX]格式的内容
        formatted_content = re.sub(r'\[emoji=[A-Za-z0-9]+\]', '', formatted_content)

        # 根据配置决定是否显示标题
        if self.show_title:
            # 构建消息，使用匹配的关键词作为标题
            title = f"【{keyword}】" if keyword else "【新线报】"
            message = f"{title}\n\n{formatted_content}"
        else:
            # 不显示标题，直接返回格式化后的内容
            message = formatted_content

        return message

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

    def _download_http_image(self, http_url) -> Optional[bytes]:
        """下载图片,返回图片二进制数据"""
        try:
            # 解析图片文件名
            import hashlib
            import base64
            local_path = self.temp_dir / f"{base64.b32encode(hashlib.sha256(http_url.encode("utf-8")).digest()).decode("ascii").rstrip("=")}.jpg"

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


if __name__ == '__main__':

    self = ToolLinkRebate()

    # xianbao_keywords = ["锝物", "得物", "鍀物"]
    xianbao_keywords = ["滔搏阿迪SPEZIAL板鞋"]
    for keyword in xianbao_keywords:

        # 调用API获取线报数据
        xianbao_data = self.get_xianbao_data(keyword)

        # 保存到数据库并获取新数据列表
        # new_data_items = self.save_xianbao_to_database(xianbao_data)
        new_data_items = xianbao_data

        # 处理新线报数据
        if new_data_items:
            logger.success(f"关键词 '{keyword}' 发现 {len(new_data_items)} 条新线报数据")

            # 对每条新线报进行转链并发送给接收者
            for item in new_data_items:
                content = item.get('content', '')
                if content:
                    # 检查是否包含过滤关键词
                    should_filter, filter_keyword = self.should_filter_xianbao(content)
                    if should_filter:
                        logger.info(f"线报包含过滤关键词 '{filter_keyword}'，跳过: {content}")
                        continue

                    # 转链处理
                    success, converted_content, error_msg = self.convert_links(content)

                    # 只有转链成功时才发送消息
                    if success:
                        # 构建完整的线报消息，使用格式化函数，并传递匹配的关键词
                        message_text = self.format_xianbao_content(converted_content, keyword)

                        # 图片处理
                        urls = re.findall(r'\[url=(.*?)\]', content)
                        # 打印提取的 URL
                        for url in urls:
                            logger.info(f"图片地址:{url}")
                            self._download_http_image(url)
