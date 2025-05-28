# encoding:utf-8
import json
import requests
import re
import os
import time
import tomllib
import urllib.parse
from datetime import datetime
from loguru import logger
import tempfile

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase

# 替代 TmpDir 的简单实现
class SimpleTmpDir:
    def __init__(self):
        self.path = os.path.join(tempfile.gettempdir(), "funmusic_tmp")
        if not os.path.exists(self.path):
            os.makedirs(self.path)
            logger.info(f"[FunMusic] 创建临时目录: {self.path}")
        
    def get_path(self):
        return self.path

class FunMusic(PluginBase):
    description = "点歌和听歌插件"
    author = "Lingyuzhou, adapted by chatgpt"
    version = "4.0.0"

    def __init__(self):
        super().__init__()
        
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        try:
            # 加载配置文件
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enabled", True)  # 注意这里使用了"enabled"而非"enable"
            
            # API设置
            api_config = config.get("api", {})
            self.timeout = api_config.get("timeout", 10)
            self.disable_ssl_verify = api_config.get("disable_ssl_verify", True)
            
            # 平台设置
            platforms_config = config.get("platforms", {})
            self.kugou_enabled = platforms_config.get("kugou_enabled", True)
            self.netease_enabled = platforms_config.get("netease_enabled", True)
            self.qishui_enabled = platforms_config.get("qishui_enabled", True)
            self.random_enabled = platforms_config.get("random_enabled", True)
            
            logger.info(f"[FunMusic] 插件已初始化, 启用状态: {self.enable}")
            
            # 禁用urllib3的InsecureRequestWarning警告
            if self.disable_ssl_verify:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                logger.debug("[FunMusic] 已禁用SSL验证警告")
            
        except Exception as e:
            logger.error(f"[FunMusic] 加载配置失败: {str(e)}")
            self.enable = False  # 如果加载失败，禁用插件

    async def async_init(self):
        return
        
    def construct_music_appmsg(self, title, singer, url, thumb_url="", platform=""):
        """
        构造音乐分享卡片的appmsg XML
        :param title: 音乐标题
        :param singer: 歌手名
        :param url: 音乐播放链接
        :param thumb_url: 封面图片URL（可选）
        :param platform: 音乐平台（酷狗/网易/抖音）
        :return: appmsg XML字符串
        """
        # 处理封面URL
        if thumb_url:
            # 确保URL是以http或https开头的
            if not thumb_url.startswith(("http://", "https://")):
                thumb_url = "https://" + thumb_url.lstrip("/")
            
            # 确保URL没有特殊字符
            thumb_url = thumb_url.replace("&", "&amp;")
                
        # 根据平台在标题中添加前缀
        if platform.lower() == "kugou":
            display_title = f"[酷狗] {title}"
            source_display_name = "酷狗音乐"
        elif platform.lower() == "netease":
            display_title = f"[网易] {title}"
            source_display_name = "网易云音乐"
        elif platform.lower() == "qishui":
            display_title = f"[汽水] {title}"
            source_display_name = "汽水音乐"
        else:
            display_title = title
            source_display_name = "音乐分享"
        
        # 确保URL没有特殊字符
        url = url.replace("&", "&amp;")
        
        # 使用更简化的XML结构，但保留关键标签
        xml = f"""<appmsg appid="" sdkver="0">
    <title>{display_title}</title>
    <des>{singer}</des>
    <action>view</action>
    <type>3</type>
    <showtype>0</showtype>
    <soundtype>0</soundtype>
    <mediatagname>音乐</mediatagname>
    <messageaction></messageaction>
    <content></content>
    <contentattr>0</contentattr>
    <url>{url}</url>
    <lowurl>{url}</lowurl>
    <dataurl>{url}</dataurl>
    <lowdataurl>{url}</lowdataurl>
    <appattach>
        <totallen>0</totallen>
        <attachid></attachid>
        <emoticonmd5></emoticonmd5>
        <fileext></fileext>
        <cdnthumburl>{thumb_url}</cdnthumburl>
        <cdnthumbaeskey></cdnthumbaeskey>
        <aeskey></aeskey>
    </appattach>
    <extinfo></extinfo>
    <sourceusername></sourceusername>
    <sourcedisplayname>{source_display_name}</sourcedisplayname>
    <thumburl>{thumb_url}</thumburl>
    <songalbumurl>{thumb_url}</songalbumurl>
    <songlyric></songlyric>
</appmsg>"""
        
        # 记录生成的XML，便于调试
        logger.debug(f"[FunMusic] 生成的音乐卡片XML: {xml}")
        
        return xml

    def get_music_cover(self, platform, detail_url, song_name="", singer=""):
        """
        尝试获取歌曲封面图片URL
        :param platform: 平台名称（酷狗/网易/汽水）
        :param detail_url: 歌曲详情页URL
        :param song_name: 歌曲名称（可选，用于日志）
        :param singer: 歌手名称（可选，用于日志）
        :return: 封面图片URL，如果获取失败则返回默认封面
        """
        # 默认封面图片
        default_cover = "https://y.qq.com/mediastyle/global/img/album_300.png"
        
        try:
            # 根据不同平台使用不同的获取方式
            if platform == "kugou":
                # 尝试从酷狗音乐详情页获取封面
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(detail_url, headers=headers, timeout=self.timeout, verify=not self.disable_ssl_verify)
                if response.status_code == 200:
                    # 使用正则表达式提取封面图片URL
                    cover_pattern = r'<img.*?class="albumImg".*?src="(.*?)"'
                    match = re.search(cover_pattern, response.text)
                    if match:
                        cover_url = match.group(1)
                        if cover_url and cover_url.startswith('http'):
                            logger.info(f"[FunMusic] 成功获取酷狗音乐封面: {cover_url}")
                            return cover_url
            
            elif platform == "netease":
                # 尝试从网易云音乐详情页获取封面
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(detail_url, headers=headers, timeout=self.timeout, verify=not self.disable_ssl_verify)
                if response.status_code == 200:
                    # 使用正则表达式提取封面图片URL
                    cover_pattern = r'<img.*?class="j-img".*?src="(.*?)"'
                    match = re.search(cover_pattern, response.text)
                    if match:
                        cover_url = match.group(1)
                        if cover_url and cover_url.startswith('http'):
                            logger.info(f"[FunMusic] 成功获取网易音乐封面: {cover_url}")
                            return cover_url
            
            elif platform == "qishui":
                # 尝试从汽水音乐详情页获取封面
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.get(detail_url, headers=headers, timeout=self.timeout, verify=not self.disable_ssl_verify)
                if response.status_code == 200:
                    try:
                        # 尝试解析JSON响应
                        data = json.loads(response.text)
                        if "cover" in data and data["cover"]:
                            cover_url = data["cover"]
                            # 检查是否是抖音域名的图片
                            if "douyinpic.com" in cover_url or "douyincdn.com" in cover_url:
                                logger.warning(f"[FunMusic] 汽水音乐使用抖音域名图片，可能无法在微信中正常显示: {cover_url}")
                                # 不再使用备用图片
                                return cover_url
                            logger.info(f"[FunMusic] 成功获取汽水音乐封面: {cover_url}")
                            return cover_url
                    except json.JSONDecodeError:
                        # 如果不是JSON，尝试使用正则表达式提取
                        cover_pattern = r'<img.*?class="cover".*?src="(.*?)"'
                        match = re.search(cover_pattern, response.text)
                        if match:
                            cover_url = match.group(1)
                            if cover_url and cover_url.startswith('http'):
                                # 检查是否是抖音域名的图片
                                if "douyinpic.com" in cover_url or "douyincdn.com" in cover_url:
                                    logger.warning(f"[FunMusic] 汽水音乐使用抖音域名图片，可能无法在微信中正常显示: {cover_url}")
                                    # 不再使用备用图片
                                    return cover_url
                                logger.info(f"[FunMusic] 成功获取汽水音乐封面: {cover_url}")
                                return cover_url
            
            # 对于汽水音乐，如果没有获取到封面，直接使用默认封面
            if platform == "qishui":
                logger.warning(f"[FunMusic] 无法获取汽水音乐封面图片，使用默认封面: {song_name} - {singer}")
                return default_cover
                
            # 对于其他平台，尝试使用歌曲名称和歌手名称搜索封面
            if song_name and singer:
                # 尝试使用QQ音乐搜索API获取封面
                try:
                    search_url = f"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w={urllib.parse.quote(f'{song_name} {singer}')}&format=json&p=1&n=1"
                    response = requests.get(search_url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                    if response.status_code == 200:
                        data = json.loads(response.text)
                        if "data" in data and "song" in data["data"] and "list" in data["data"]["song"] and data["data"]["song"]["list"]:
                            song_info = data["data"]["song"]["list"][0]
                            if "albummid" in song_info:
                                albummid = song_info["albummid"]
                                cover_url = f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{albummid}.jpg"
                                logger.info(f"[FunMusic] 使用QQ音乐API获取到封面: {cover_url}")
                                return cover_url
                except Exception as e:
                    logger.error(f"[FunMusic] 使用QQ音乐API获取封面时出错: {e}")
            
            logger.warning(f"[FunMusic] 无法获取封面图片，使用默认封面: {song_name} - {singer}")
            return default_cover
            
        except Exception as e:
            logger.error(f"[FunMusic] 获取封面图片时出错: {e}")
            return default_cover

    def extract_cover_from_response(self, response_text):
        """
        从API返回的内容中提取封面图片URL
        :param response_text: API返回的文本内容
        :return: 封面图片URL或None
        """
        try:
            # 尝试解析为JSON格式（汽水音乐API）
            try:
                data = json.loads(response_text)
                if "cover" in data and data["cover"]:
                    cover_url = data["cover"]
                    # 检查是否是抖音域名的图片
                    if "douyinpic.com" in cover_url or "douyincdn.com" in cover_url:
                        logger.warning(f"[FunMusic] 检测到抖音域名图片，可能无法在微信中正常显示: {cover_url}")
                        # 不再使用备用图片
                    logger.info(f"[FunMusic] 从JSON中提取到封面URL: {cover_url}")
                    return cover_url
            except json.JSONDecodeError:
                # 不是JSON格式，继续使用文本解析方法
                pass
                
            # 查找 ±img=URL± 格式的封面图片（抖音API格式）
            img_pattern = r'±img=(https?://[^±]+)±'
            match = re.search(img_pattern, response_text)
            if match:
                cover_url = match.group(1)
                # 检查是否是抖音域名的图片
                if "douyinpic.com" in cover_url or "douyincdn.com" in cover_url:
                    logger.warning(f"[FunMusic] 检测到抖音域名图片，可能无法在微信中正常显示: {cover_url}")
                    # 不再使用备用图片
                # 不再移除后缀，保留完整的URL
                logger.info(f"[FunMusic] 从API响应中提取到封面图片: {cover_url}")
                return cover_url
            return None
        except Exception as e:
            logger.error(f"[FunMusic] 提取封面图片时出错: {e}")
            return None

    def download_music(self, music_url, platform):
        """
        下载音乐文件到临时目录
        :param music_url: 音乐文件URL
        :param platform: 平台名称（用于日志）
        :return: 音乐文件本地路径，失败则返回None
        """
        # 创建临时目录用于存储下载的音乐文件
        try:
            # 使用系统临时目录
            tmp_dir_obj = SimpleTmpDir()
            tmp_dir = tmp_dir_obj.get_path()
            music_path = os.path.join(tmp_dir, f"{platform}_{int(time.time())}.mp3")
            
            logger.info(f"[FunMusic] 开始下载音乐: {music_url}")
            logger.debug(f"[FunMusic] 下载目标路径: {music_path}")
            
            # 下载音乐文件
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            }
            
            response = requests.get(music_url, headers=headers, stream=True, timeout=self.timeout, verify=not self.disable_ssl_verify)
            response.raise_for_status()  # 如果状态码不是200，将引发HTTPError异常
            
            # 检查Content-Type
            content_type = response.headers.get('Content-Type', '')
            logger.debug(f"[FunMusic] 音乐文件Content-Type: {content_type}")
            
            if 'audio' not in content_type and 'application/octet-stream' not in content_type:
                logger.warning(f"[FunMusic] 下载的内容可能不是音频文件: {content_type}")
                # 继续尝试下载，因为有些API可能未正确设置Content-Type
            
            # 写入文件
            with open(music_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # 获取文件大小
            total_size = os.path.getsize(music_path)
            
            # 验证文件大小
            if total_size == 0:
                logger.error("[FunMusic] 下载的文件大小为0")
                os.remove(music_path)  # 删除空文件
                return None
                
            # 最小文件大小验证 (1KB)
            if total_size < 1024:
                logger.warning(f"[FunMusic] 下载的文件小于1KB，可能不是有效音频: {total_size} 字节")
            
            # 检查文件头，确认是否为MP3文件
            try:
                with open(music_path, 'rb') as f:
                    header = f.read(4)
                
                # 检查MP3文件头标识 (通常以ID3或FFFB开头)
                is_valid_mp3 = False
                if header.startswith(b'ID3') or header.startswith(b'\xFF\xFB') or header.startswith(b'\xFF\xF3') or header.startswith(b'\xFF\xFA'):
                    is_valid_mp3 = True
                
                if not is_valid_mp3:
                    logger.warning(f"[FunMusic] 文件可能不是有效的MP3格式，文件头: {header.hex()}")
                    # 继续尝试使用，因为有些MP3文件可能没有标准的文件头
            except Exception as e:
                logger.error(f"[FunMusic] 检查MP3文件头时出错: {e}")
                
            logger.info(f"[FunMusic] 音乐下载完成: {music_path}, 大小: {total_size/1024:.2f}KB")
            return music_path
            
        except Exception as e:
            logger.error(f"[FunMusic] 下载音乐文件时出错: {e}")
            # 如果文件已创建，清理它
            if 'music_path' in locals() and os.path.exists(music_path):
                try:
                    os.remove(music_path)
                except Exception as clean_error:
                    logger.error(f"[FunMusic] 清理失败的下载文件时出错: {clean_error}")
            return None
        
    @on_text_message(priority=88)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        """处理文本消息"""
        if not self.enable:
            return True  # 允许其他插件处理
        
        content = message.get("Content", "").strip()
        logger.debug(f"[FunMusic] 收到消息: {content}")
        
        # 检查对应平台功能是否启用
        platform_map = {
            "酷狗": self.kugou_enabled,
            "网易": self.netease_enabled,
            "汽水": self.qishui_enabled
        }
        
        # 随机点歌命令
        if content == "随机点歌":
            if not self.random_enabled:
                await self.send_reply_text(bot, message, "随机点歌功能已禁用")
                return False
            await self.handle_random_music(bot, message, is_voice=False)
            return False  # 阻止其他插件处理
        
        # 处理单独的"点歌"命令，默认使用酷狗点歌
        elif content == "点歌":
            if not self.kugou_enabled:
                await self.send_reply_text(bot, message, "酷狗音乐功能已禁用，请指定其他音乐平台")
                return False
            await self.send_reply_text(bot, message, "请输入要搜索的歌曲名称，例如：酷狗点歌 歌曲名")
            return False  # 阻止其他插件处理
        
        # 处理"点歌 歌曲名"的格式，默认使用酷狗点歌
        elif content.startswith("点歌 "):
            if not self.kugou_enabled:
                await self.send_reply_text(bot, message, "酷狗音乐功能已禁用，请指定其他音乐平台")
                return False
            # 将命令转换为酷狗点歌命令
            song_name = content[3:].strip()
            if not song_name:
                await self.send_reply_text(bot, message, "请输入要搜索的歌曲名称")
                return False
            
            # 创建一个新的消息对象，修改Content为酷狗点歌命令
            new_message = message.copy()
            new_message["Content"] = f"酷狗点歌 {song_name}"
            await self.handle_kugou_music(bot, new_message, is_voice=False)
            return False  # 阻止其他插件处理
        
        # 帮助命令
        elif content == "音乐帮助" or content == "点歌帮助":
            help_text = await self.help_text()
            await bot.send_text_message(message["FromWxid"], help_text)
            return False  # 阻止其他插件处理
        
        # 处理点歌和听歌命令
        for platform in platform_map:
            # 点歌命令
            if content.startswith(f"{platform}点歌 "):
                if not platform_map[platform]:
                    await self.send_reply_text(bot, message, f"{platform}音乐功能已禁用")
                    return False
                
                if platform == "酷狗":
                    await self.handle_kugou_music(bot, message, is_voice=False)
                elif platform == "网易":
                    await self.handle_netease_music(bot, message, is_voice=False)
                elif platform == "汽水":
                    await self.handle_qishui_music(bot, message, is_voice=False)
                
                return False  # 阻止其他插件处理
            
            # 听歌命令
            elif content.startswith(f"{platform}听歌 "):
                if not platform_map[platform]:
                    await self.send_reply_text(bot, message, f"{platform}音乐功能已禁用")
                    return False
                
                if platform == "酷狗":
                    await self.handle_kugou_music(bot, message, is_voice=True)
                elif platform == "网易":
                    await self.handle_netease_music(bot, message, is_voice=True)
                elif platform == "汽水":
                    await self.handle_qishui_music(bot, message, is_voice=True)
                
                return False  # 阻止其他插件处理
        
        return True  # 不是音乐命令，继续让其他插件处理
        
    async def handle_random_music(self, bot: WechatAPIClient, message: dict, is_voice=False):
        """处理随机点歌功能"""
        if not self.random_enabled:
            await self.send_reply_text(bot, message, "随机点歌功能已禁用")
            return
        
        from_wxid = message.get("FromWxid", "")
        
        url = "https://hhlqilongzhu.cn/api/wangyi_hot_review.php"
        try:
            response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
            if response.status_code == 200:
                try:
                    data = json.loads(response.text)
                    if "code" in data and data["code"] == 200:
                        # 提取歌曲信息
                        title = data.get("song", "未知歌曲")
                        singer = data.get("singer", "未知歌手")
                        music_url = data.get("url", "")
                        thumb_url = data.get("img", "")
                        
                        # 记录获取到的随机歌曲信息
                        logger.info(f"[FunMusic] 随机点歌获取成功: {title} - {singer}")
                        
                        # 构造音乐分享卡片
                        appmsg = self.construct_music_appmsg(title, singer, music_url, thumb_url, "netease")
                        
                        # 发送应用消息
                        await bot.send_app_message(from_wxid, appmsg, type=3)
                    else:
                        await self.send_reply_text(bot, message, "随机点歌失败，请稍后重试")
                except json.JSONDecodeError:
                    logger.error(f"[FunMusic] 随机点歌API返回的不是有效的JSON: {response.text[:100]}...")
                    await self.send_reply_text(bot, message, "随机点歌失败，请稍后重试")
            else:
                await self.send_reply_text(bot, message, "随机点歌失败，请稍后重试")
        except Exception as e:
            logger.error(f"[FunMusic] 随机点歌错误: {e}")
            await self.send_reply_text(bot, message, "随机点歌失败，请稍后重试")
                
    async def send_reply_text(self, bot: WechatAPIClient, message: dict, reply_text: str):
        """发送文本回复，根据是否为群聊决定发送方式"""
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        is_group = message.get("IsGroup", False)
        
        if is_group:
            await bot.send_at_message(from_wxid, reply_text, [sender_wxid])
        else:
            await bot.send_text_message(from_wxid, reply_text)

    async def handle_kugou_music(self, bot: WechatAPIClient, message: dict, is_voice=False):
        """处理酷狗点歌/听歌功能"""
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        is_group = message.get("IsGroup", False)
        
        # 获取命令内容
        content = message.get("Content", "").strip()
        command_prefix = "酷狗听歌 " if is_voice else "酷狗点歌 "
        song_name = content[len(command_prefix):].strip()
        
        if not song_name:
            await self.send_reply_text(bot, message, "请输入要搜索的歌曲名称")
            return
            
        # 检查是否包含序号（详情获取功能）
        params = song_name.split()
        if len(params) == 2 and params[1].isdigit():
            song_name, song_number = params
            url = f"https://www.hhlqilongzhu.cn/api/dg_kgmusic.php?gm={song_name}&n={song_number}"
            try:
                response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                content = response.text
                song_info = content.split('\n')
                
                if len(song_info) >= 4:  # 确保有足够的信息行
                    # 提取歌曲信息
                    title = song_info[1].replace("歌名：", "").strip()
                    singer = song_info[2].replace("歌手：", "").strip()
                    detail_url = song_info[3].replace("歌曲详情页：", "").strip()
                    music_url = song_info[4].replace("播放链接：", "").strip()
                    
                    if is_voice:
                        # 下载音乐文件
                        music_path = self.download_music(music_url, "kugou")
                        
                        if music_path:
                            try:
                                # 读取音乐文件
                                with open(music_path, "rb") as f:
                                    voice_data = f.read()
                                
                                logger.debug(f"[FunMusic] 准备发送语音消息，文件大小: {len(voice_data)} 字节")
                                
                                # 发送语音消息
                                result = await self.send_voice(bot, from_wxid, music_path)
                                logger.info(f"[FunMusic] 语音消息发送结果: {result}")
                                
                                # 删除临时文件
                                try:
                                    os.remove(music_path)
                                    logger.debug(f"[FunMusic] 已删除临时文件: {music_path}")
                                except Exception as e:
                                    logger.warning(f"[FunMusic] 删除临时文件失败: {e}")
                            except Exception as e:
                                logger.error(f"[FunMusic] 发送语音消息出错: {e}")
                                await self.send_reply_text(bot, message, "发送语音消息失败，请稍后重试")
                        else:
                            await self.send_reply_text(bot, message, "音乐文件下载失败，请稍后重试")
                    else:
                        # 尝试从响应中提取封面图片URL
                        thumb_url = self.extract_cover_from_response(content)
                        
                        # 如果从响应中没有提取到封面，尝试从详情页获取
                        if not thumb_url:
                            thumb_url = self.get_music_cover("kugou", detail_url, title, singer)
                        
                        # 构造音乐分享卡片
                        appmsg = self.construct_music_appmsg(title, singer, music_url, thumb_url, "kugou")
                        
                        # 发送应用消息
                        await bot.send_app_message(from_wxid, appmsg, type=3)
                        
                else:
                    await self.send_reply_text(bot, message, "未找到该歌曲，请确认歌名和序号是否正确")
            except Exception as e:
                logger.error(f"[FunMusic] 酷狗详情错误: {e}")
                await self.send_reply_text(bot, message, "获取失败，请稍后重试")
        else:
            # 原有的搜索歌曲列表功能
            url = f"https://www.hhlqilongzhu.cn/api/dg_kgmusic.php?gm={song_name}&n="
            try:
                response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                songs = response.text.strip().split('\n')
                if songs and len(songs) > 1:  # 确保有搜索结果
                    reply_content = " 为你在酷狗音乐库中找到以下歌曲：\n\n"
                    for song in songs:
                        if song.strip():  # 确保不是空行
                            reply_content += f"{song}\n"
                    reply_content += f"\n请发送「酷狗点歌 {song_name} 序号」获取歌曲详情\n或发送「酷狗听歌 {song_name} 序号」来播放对应歌曲"
                else:
                    reply_content = "未找到相关歌曲，请换个关键词试试"
                
                await self.send_reply_text(bot, message, reply_content)
            except Exception as e:
                logger.error(f"[FunMusic] 酷狗点歌错误: {e}")
                await self.send_reply_text(bot, message, "搜索失败，请稍后重试")

    async def handle_netease_music(self, bot: WechatAPIClient, message: dict, is_voice=False):
        """处理网易点歌/听歌功能"""
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        is_group = message.get("IsGroup", False)
        
        # 获取命令内容
        content = message.get("Content", "").strip()
        command_prefix = "网易听歌 " if is_voice else "网易点歌 "
        song_name = content[len(command_prefix):].strip()
        
        if not song_name:
            await self.send_reply_text(bot, message, "请输入要搜索的歌曲名称")
            return
            
        # 检查是否包含序号（详情获取功能）
        params = song_name.split()
        if len(params) == 2 and params[1].isdigit():
            song_name, song_number = params
            url = f"https://www.hhlqilongzhu.cn/api/dg_wyymusic.php?gm={song_name}&n={song_number}"
            try:
                response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                content = response.text
                song_info = content.split('\n')
                
                if len(song_info) >= 4:  # 确保有足够的信息行
                    # 提取歌曲信息
                    title = song_info[1].replace("歌名：", "").strip()
                    singer = song_info[2].replace("歌手：", "").strip()
                    detail_url = song_info[3].replace("歌曲详情页：", "").strip()
                    music_url = song_info[4].replace("播放链接：", "").strip()
                    
                    if is_voice:
                        # 下载音乐文件
                        music_path = self.download_music(music_url, "netease")
                        
                        if music_path:
                            try:
                                # 读取音乐文件
                                with open(music_path, "rb") as f:
                                    voice_data = f.read()
                                
                                logger.debug(f"[FunMusic] 准备发送语音消息，文件大小: {len(voice_data)} 字节")
                                
                                # 发送语音消息
                                result = await self.send_voice(bot, from_wxid, music_path)
                                logger.info(f"[FunMusic] 语音消息发送结果: {result}")
                                
                                # 删除临时文件
                                try:
                                    os.remove(music_path)
                                    logger.debug(f"[FunMusic] 已删除临时文件: {music_path}")
                                except Exception as e:
                                    logger.warning(f"[FunMusic] 删除临时文件失败: {e}")
                            except Exception as e:
                                logger.error(f"[FunMusic] 发送语音消息出错: {e}")
                                await self.send_reply_text(bot, message, "发送语音消息失败，请稍后重试")
                        else:
                            await self.send_reply_text(bot, message, "音乐文件下载失败，请稍后重试")
                    else:
                        # 尝试从响应中提取封面图片URL
                        thumb_url = self.extract_cover_from_response(content)
                        
                        # 如果从响应中没有提取到封面，尝试从详情页获取
                        if not thumb_url:
                            thumb_url = self.get_music_cover("netease", detail_url, title, singer)
                        
                        # 构造音乐分享卡片
                        appmsg = self.construct_music_appmsg(title, singer, music_url, thumb_url, "netease")
                        
                        # 发送应用消息
                        await bot.send_app_message(from_wxid, appmsg, type=3)
                        
                else:
                    await self.send_reply_text(bot, message, "未找到该歌曲，请确认歌名和序号是否正确")
            except Exception as e:
                logger.error(f"[FunMusic] 网易详情错误: {e}")
                await self.send_reply_text(bot, message, "获取失败，请稍后重试")
        else:
            # 原有的搜索歌曲列表功能
            url = f"https://www.hhlqilongzhu.cn/api/dg_wyymusic.php?gm={song_name}&n=&num=20"
            try:
                response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                songs = response.text.strip().split('\n')
                if songs and len(songs) > 1:  # 确保有搜索结果
                    reply_content = " 为你在网易云音乐库中找到以下歌曲：\n\n"
                    for song in songs:
                        if song.strip():  # 确保不是空行
                            reply_content += f"{song}\n"
                    reply_content += f"\n请发送「网易点歌 {song_name} 序号」获取歌曲详情\n或发送「网易听歌 {song_name} 序号」来播放对应歌曲"
                else:
                    reply_content = "未找到相关歌曲，请换个关键词试试"
                
                await self.send_reply_text(bot, message, reply_content)
            except Exception as e:
                logger.error(f"[FunMusic] 网易点歌错误: {e}")
                await self.send_reply_text(bot, message, "搜索失败，请稍后重试")

    async def handle_qishui_music(self, bot: WechatAPIClient, message: dict, is_voice=False):
        """处理汽水点歌/听歌功能"""
        from_wxid = message.get("FromWxid", "")
        sender_wxid = message.get("SenderWxid", "")
        is_group = message.get("IsGroup", False)
        
        # 获取命令内容
        content = message.get("Content", "").strip()
        command_prefix = "汽水听歌 " if is_voice else "汽水点歌 "
        song_name = content[len(command_prefix):].strip()
        
        if not song_name:
            await self.send_reply_text(bot, message, "请输入要搜索的歌曲名称")
            return
            
        # 检查是否包含序号（详情获取功能）
        params = song_name.split()
        if len(params) == 2 and params[1].isdigit():
            song_name, song_number = params
            url = f"https://hhlqilongzhu.cn/api/dg_qishuimusic.php?msg={song_name}&n={song_number}"
            try:
                response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                content = response.text
                
                # 尝试解析JSON响应
                try:
                    data = json.loads(content)
                    if "title" in data and "singer" in data and "music" in data:
                        title = data["title"]
                        singer = data["singer"]
                        music_url = data["music"]
                        
                        if is_voice:
                            # 下载音乐文件
                            music_path = self.download_music(music_url, "qishui")
                            
                            if music_path:
                                try:
                                    # 读取音乐文件
                                    with open(music_path, "rb") as f:
                                        voice_data = f.read()
                                    
                                    logger.debug(f"[FunMusic] 准备发送语音消息，文件大小: {len(voice_data)} 字节")
                                    
                                    # 发送语音消息
                                    result = await self.send_voice(bot, from_wxid, music_path)
                                    logger.info(f"[FunMusic] 语音消息发送结果: {result}")
                                    
                                    # 删除临时文件
                                    try:
                                        os.remove(music_path)
                                        logger.debug(f"[FunMusic] 已删除临时文件: {music_path}")
                                    except Exception as e:
                                        logger.warning(f"[FunMusic] 删除临时文件失败: {e}")
                                except Exception as e:
                                    logger.error(f"[FunMusic] 发送语音消息出错: {e}")
                                    await self.send_reply_text(bot, message, "发送语音消息失败，请稍后重试")
                            else:
                                await self.send_reply_text(bot, message, "音乐文件下载失败，请稍后重试")
                        else:
                            # 提取封面图片URL
                            thumb_url = ""
                            if "cover" in data and data["cover"]:
                                thumb_url = data["cover"]
                            
                            # 如果没有提取到封面，尝试获取默认封面
                            if not thumb_url:
                                thumb_url = self.get_music_cover("qishui", "", title, singer)
                            
                            # 构造音乐分享卡片
                            appmsg = self.construct_music_appmsg(title, singer, music_url, thumb_url, "qishui")
                            
                            # 发送应用消息
                            await bot.send_app_message(from_wxid, appmsg, type=3)
                    else:
                        await self.send_reply_text(bot, message, "未找到该歌曲，请确认歌名和序号是否正确")
                except json.JSONDecodeError:
                    logger.error(f"[FunMusic] 汽水音乐API返回的不是有效的JSON: {content[:100]}...")
                    await self.send_reply_text(bot, message, "获取失败，请稍后重试")
                    
            except Exception as e:
                logger.error(f"[FunMusic] 汽水音乐详情错误: {e}")
                await self.send_reply_text(bot, message, "获取失败，请稍后重试")
        else:
            # 搜索歌曲列表功能
            url = f"https://hhlqilongzhu.cn/api/dg_qishuimusic.php?msg={song_name}"
            try:
                response = requests.get(url, timeout=self.timeout, verify=not self.disable_ssl_verify)
                content = response.text.strip()
                
                # 尝试解析JSON响应
                try:
                    data = json.loads(content)
                    # 检查是否返回了歌曲列表
                    if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                        # 新格式：包含完整歌曲列表的JSON
                        reply_content = " 为你在汽水音乐库中找到以下歌曲：\n\n"
                        for song in data["data"]:
                            if "n" in song and "title" in song and "singer" in song:
                                reply_content += f"{song['n']}. {song['title']} - {song['singer']}\n"
                        
                        reply_content += f"\n请发送「汽水点歌 {song_name} 序号」获取歌曲详情\n或发送「汽水听歌 {song_name} 序号」来播放对应歌曲"
                    elif "title" in data and "singer" in data:
                        # 旧格式：只返回单个歌曲的JSON
                        reply_content = " 为你在汽水音乐库中找到以下歌曲：\n\n"
                        reply_content += f"1. {data['title']} - {data['singer']}\n"
                        reply_content += f"\n请发送「汽水点歌 {song_name} 1」获取歌曲详情\n或发送「汽水听歌 {song_name} 1」来播放对应歌曲"
                    else:
                        reply_content = "未找到相关歌曲，请换个关键词试试"
                except json.JSONDecodeError:
                    # 如果不是JSON，尝试使用正则表达式解析文本格式的结果
                    pattern = r"(\d+)\.\s+(.*?)\s+-\s+(.*?)$"
                    matches = re.findall(pattern, content, re.MULTILINE)
                    
                    if matches:
                        reply_content = " 为你在汽水音乐库中找到以下歌曲：\n\n"
                        for match in matches:
                            number, title, singer = match
                            reply_content += f"{number}. {title} - {singer}\n"
                        
                        reply_content += f"\n请发送「汽水点歌 {song_name} 序号」获取歌曲详情\n或发送「汽水听歌 {song_name} 序号」来播放对应歌曲"
                    else:
                        logger.error(f"[FunMusic] 汽水音乐API返回格式无法解析: {content[:100]}...")
                        reply_content = "搜索结果解析失败，请稍后重试"
                
                await self.send_reply_text(bot, message, reply_content)
            except Exception as e:
                logger.error(f"[FunMusic] 汽水点歌错误: {e}")
                await self.send_reply_text(bot, message, "搜索失败，请稍后重试")
    
    async def help_text(self):
        """返回插件帮助信息"""
        return """📱 FunMusic 音乐点歌插件 📱

🎵 点歌功能（发送音乐卡片）:

1. 酷狗音乐：
   - 搜索歌单：发送「酷狗点歌 歌曲名称」
   - 音乐卡片：发送「酷狗点歌 歌曲名称 序号」

2. 网易音乐：
   - 搜索歌单：发送「网易点歌 歌曲名称」
   - 音乐卡片：发送「网易点歌 歌曲名称 序号」

3. 汽水音乐：
   - 搜索歌单：发送「汽水点歌 歌曲名称」
   - 音乐卡片：发送「汽水点歌 歌曲名称 序号」

4. 快捷点歌：
   - 直接发送「点歌 歌曲名称」将默认使用酷狗音乐

🎧 听歌功能（以语音消息形式播放）:
发送以下命令接收语音消息（需先搜索获取序号）：
 • 「酷狗听歌 歌曲名称 序号」
 • 「网易听歌 歌曲名称 序号」
 • 「汽水听歌 歌曲名称 序号」

🎲 随机点歌：
发送「随机点歌」获取随机热门歌曲

💡 注：序号在搜索结果中获取，语音功能受微信限制可能不稳定
"""

    async def send_voice(self, bot, from_wxid, music_path):
        """
        发送语音消息，处理不同的音频格式
        :param bot: 微信API客户端
        :param from_wxid: 接收者微信ID
        :param music_path: 音频文件路径
        :return: bool 是否成功发送
        """
        try:
            if not os.path.exists(music_path):
                logger.error(f"[FunMusic] 要发送的音频文件不存在: {music_path}")
                return False
                
            file_size = os.path.getsize(music_path)
            if file_size == 0:
                logger.error("[FunMusic] 音频文件大小为0")
                return False
                
            # 检查文件大小限制 (微信一般限制音频文件为几MB)
            max_size = 5 * 1024 * 1024  # 5MB上限
            if file_size > max_size:
                logger.warning(f"[FunMusic] 音频文件过大 ({file_size/1024/1024:.2f}MB)，超过5MB限制，可能发送失败")
            
            logger.debug(f"[FunMusic] 准备发送语音消息，文件大小: {file_size} 字节 ({file_size/1024:.2f}KB)")
            
            # 尝试多种方式发送语音消息
            # 方式1: 使用API的语音消息发送功能
            try:
                with open(music_path, "rb") as f:
                    voice_data = f.read()
                
                # 尝试发送语音消息
                result = await bot.send_voice_message(from_wxid, voice=voice_data, format="mp3")
                if isinstance(result, dict) and result.get("Status") == "Success":
                    logger.info(f"[FunMusic] 语音消息发送成功")
                    return True
                else:
                    logger.warning(f"[FunMusic] 语音消息发送结果不明确: {result}")
                    # 继续尝试其他方法
                    raise Exception("语音消息发送失败，尝试其他方法")
                
            except Exception as e:
                logger.error(f"[FunMusic] 方法1发送语音消息失败: {e}")
                
                # 方式2: 尝试作为文件发送
                try:
                    result = await bot.send_file_message(from_wxid, music_path)
                    if isinstance(result, dict) and result.get("Status") == "Success":
                        logger.info(f"[FunMusic] 作为文件发送成功")
                        return True
                    else:
                        logger.warning(f"[FunMusic] 作为文件发送结果不明确: {result}")
                        raise Exception("作为文件发送失败")
                except Exception as e2:
                    logger.error(f"[FunMusic] 方法2发送语音消息失败: {e2}")
                    
                    # 最后的备用方案: 发送文本消息
                    await bot.send_text_message(
                        from_wxid, 
                        f"很抱歉，语音消息发送失败，可能是音频格式不支持。\n建议使用点歌功能获取音乐卡片。"
                    )
                    return False
                
        except Exception as e:
            logger.error(f"[FunMusic] 发送语音消息出错: {e}")
            try:
                # 发送一条提示消息
                await bot.send_text_message(
                    from_wxid,
                    f"语音发送出错，请使用点歌功能代替。错误: {str(e)[:50]}"
                )
            except:
                pass
            return False
