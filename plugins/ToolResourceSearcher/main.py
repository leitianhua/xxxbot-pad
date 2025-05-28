# encoding:utf-8
import threading
import requests
import time
from concurrent.futures import ThreadPoolExecutor
import os
import json
import sqlite3
from typing import List, Dict, Any, Optional
from loguru import logger
import tomllib

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase
from .utils.search import ResourceSearch
from .utils.quark import Quark
from .utils.baidu import Baidu


class ToolResourceSearcher(PluginBase):
    description = "网盘资源搜索"
    author = "lei"
    version = "1.0"

    def __init__(self):
        super().__init__()
        try:
            # 加载配置
            self._load_config()
            
            # 开启一个线程每分钟清除过期资源
            self.clear_expired_resources_thread = threading.Thread(target=self.clear_expired_resources)
            self.clear_expired_resources_thread.daemon = True  # 设置为守护线程，防止主线程退出时子线程还在运行
            self.clear_expired_resources_thread.start()
            
            logger.info("[ToolResourceSearcher] 初始化成功")
        except Exception as e:
            logger.warning(f"[ToolResourceSearcher] 初始化失败: {e}")
            raise e
            
    def _load_config(self):
        """加载配置文件"""
        try:
            # 首先尝试加载config.toml
            conf_path = os.path.join(os.path.dirname(__file__), "config.toml")
            if os.path.exists(conf_path):
                with open(conf_path, "rb") as f:
                    self.conf = tomllib.load(f)
            else:
                # 如果toml不存在，尝试加载config.json
                conf_path = os.path.join(os.path.dirname(__file__), "config.json")
                if os.path.exists(conf_path):
                    with open(conf_path, "r", encoding="utf-8") as conf_file:
                        self.conf = json.loads(conf_file.read())
                else:
                    logger.error("[ToolResourceSearcher] 配置文件不存在")
                    self.conf = {}
                    return
            
            # 初始化配置项
            general_conf = self.conf.get("general", {})
            self.expired_time = general_conf.get("expired_time", 30)
            
            # 获取广告配置
            ad_conf = self.conf.get("advertisement", {})
            self.ad_keywords = ad_conf.get("keywords", [])
            
            # 获取账号配置
            self.accounts = self.conf.get("accounts", [])
                
            # 获取启用的夸克和百度账号
            quark_account = next((acc for acc in self.accounts if acc.get("type") == "quark" and acc.get("enable")), None)
            baidu_account = next((acc for acc in self.accounts if acc.get("type") == "baidu" and acc.get("enable")), None)
            
            # 设置网盘账号信息
            self.quark_cookie = quark_account.get("cookie") if quark_account else ""
            self.quark_save_dir = quark_account.get("save_dir") if quark_account else ""
            self.baidu_cookie = baidu_account.get("cookie") if baidu_account else ""
            self.baidu_save_dir = baidu_account.get("save_dir") if baidu_account else ""
            
            # 验证夸克网盘cookie有效性
            if self.quark_cookie:
                if self._verify_quark_account():
                    logger.info("[ToolResourceSearcher] 夸克网盘账号验证成功")
                else:
                    logger.error("[ToolResourceSearcher] 夸克网盘账号验证失败，请检查cookie是否有效")
            
        except Exception as e:
            logger.error(f"[ToolResourceSearcher] 加载配置文件失败: {e}")
            self.conf = {}
            
    def _verify_quark_account(self):
        """验证夸克网盘账号有效性
        Returns:
            bool: True表示账号有效，False表示账号无效
        """
        try:
            # 构建验证所需的请求头
            headers = {
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'accept': 'application/json, text/plain, */*',
                'content-type': 'application/json',
                'sec-ch-ua-mobile': '?0',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'sec-ch-ua-platform': '"Windows"',
                'origin': 'https://pan.quark.cn',
                'sec-fetch-site': 'same-site',
                'sec-fetch-mode': 'cors',
                'sec-fetch-dest': 'empty',
                'referer': 'https://pan.quark.cn/',
                'accept-encoding': 'gzip, deflate, br',
                'accept-language': 'zh-CN,zh;q=0.9',
                'cookie': self.quark_cookie
            }
            
            # 调用获取账户信息的API
            url = "https://pan.quark.cn/account/info"
            params = {"fr": "pc", "platform": "pc"}
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            account_info = response.json()
            
            # 检查响应中是否包含账户信息
            if account_info and account_info.get("data"):
                nickname = account_info["data"].get("nickname", "")
                logger.info(f"[ToolResourceSearcher] 夸克网盘账号: {nickname}")
                return True
            else:
                logger.error(f"[ToolResourceSearcher] 夸克网盘账号验证失败: {account_info.get('message', '未知错误')}")
                return False
        except Exception as e:
            logger.error(f"[ToolResourceSearcher] 验证夸克账号时发生错误: {str(e)}")
            return False

    # 每分钟清除过期资源
    def clear_expired_resources(self):
        while True:
            try:
                quark = Quark(self.conf)
                quark.del_expired_resources(self.expired_time)
                time.sleep(60)  # 每分钟执行一次
            except Exception as e:
                logger.error(f"[ToolResourceSearcher] 清除过期资源失败: {e}")
                time.sleep(60)

    @on_text_message(priority=88)
    async def handle_search(self, bot: WechatAPIClient, message: dict):
        # 只处理文本类型消息
        content = message.get("Content", "").strip()
        if not content:
            return True
            
        logger.debug(f"[ToolResourceSearcher] 当前监听信息： {content}")

        # 处理搜索指令
        if any(content.startswith(prefix) for prefix in ["搜", "搜索"]):

            # 移除前缀，获取搜索内容
            def remove_prefix(text, prefixes):
                for prefix in prefixes:
                    if text.startswith(prefix):
                        return text[len(prefix):].strip()
                return text.strip()

            # 搜索内容
            search_content = remove_prefix(content, ["搜", "搜索"]).strip()
            
            # 通知用户正在进行搜索
            if message.get("IsGroup", False):
                await bot.send_at_message(
                    message["FromWxid"], 
                    " 🔍正在获取资源，请稍等...", 
                    [message["SenderWxid"]]
                )
            else:
                await bot.send_text_message(message["FromWxid"], " 🔍正在获取资源，请稍等...")
            
            # 执行搜索
            results = self.search_and_store(search_content)
            
            # 构建回复内容
            if not results:
                reply_text = f"搜索内容：{search_content}"
                reply_text += "\n⚠未找到，可换个关键词尝试哦"
                reply_text += "\n————————————"
                reply_text += "\n⚠搜索指令：搜:XXX 或 搜索:XXX"
            else:
                reply_text = f"搜索内容：{search_content}\n————————————"
                for item in results:
                    reply_text += f"\n🌐️{item.get('title', '未知标题')}"
                    reply_text += f"\n{item.get('url', '未知URL')}"
                    reply_text += "\n————————————"
                
                if any(item.get('is_time') == 1 for item in results):
                    reply_text += "\n⚠资源来源网络，30分钟后删除"
                    reply_text += "\n⚠避免失效，请及时保存~💾"
            
            # 发送回复
            if message.get("IsGroup", False):
                await bot.send_at_message(
                    message["FromWxid"], 
                    reply_text, 
                    [message["SenderWxid"]]
                )
            else:
                await bot.send_text_message(message["FromWxid"], reply_text)
                
            return False  # 阻止其他插件处理
            
        return True  # 允许其他插件处理

    # 多线程全网搜索并转存
    def search_and_store(self, keyword: str) -> List[dict]:
        """
        搜索资源并转存到网盘
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            包含转存后资源信息的列表
        """
        logger.info(f'[ToolResourceSearcher] 搜索关键字: {keyword}')
        start_time = time.time()
        
        # 创建资源搜索对象
        rs = ResourceSearch(self.conf)
        
        # 获取所有搜索方法并并行执行，
        search_methods = [
            'search_source1',
            'search_source2',
            'search_source3',
            'search_source4',
            'search_source5'  # 添加瓦力搜索
        ]
        
        # 使用线程池并行搜索
        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(getattr(rs, method), keyword)
                for method in search_methods
            ]
        
        # 创建转存工具
        quark = Quark(self.conf)
        baidu = Baidu(self.conf)
        
        # 存储结果
        unique_results = []
        count = 0
        
        # 处理搜索结果
        for future in futures:
            results = future.result()
            logger.debug(f"[ToolResourceSearcher] 搜索结果: {len(results) if results else 0}条")
            if not results:
                continue
                
            for item in results:
                # 限制结果数量
                if count >= 5:
                    logger.debug(f"[ToolResourceSearcher] 结果已达到5条上限，停止处理")
                    break
                    
                url = item.get('url')
                if not url:
                    logger.debug(f"[ToolResourceSearcher] 跳过没有URL的项: {item}")
                    continue
                
                logger.debug(f"[ToolResourceSearcher] 处理搜索结果: {item.get('title', '未知')} - {url}")
                    
                try:
                    file_not_exist = False
                    file_name = ''
                    share_link = ''
                    
                    # 根据链接类型选择相应的网盘处理
                    if 'quark' in url:
                        logger.info(f"[ToolResourceSearcher] 转存夸克链接: {url}")
                        file_not_exist, file_name, share_link = quark.store(url)
                    elif 'baidu' in url:
                        logger.info(f"[ToolResourceSearcher] 转存百度链接: {url}")
                        pass
                        # 忽略百度
                        # file_not_exist, file_name, share_link = baidu.store(url)
                    else:
                        logger.warning(f"[ToolResourceSearcher] 未知链接类型，跳过: {url}")
                        continue
                        
                    # 如果成功处理，添加到结果
                    if file_name and share_link:
                        logger.info(f'[ToolResourceSearcher] {"新转存" if file_not_exist else "已存在"}: {file_name} - {share_link}')
                        item['url'] = share_link
                        item['is_time'] = 1
                        unique_results.append(item)
                        count += 1
                    else:
                        logger.warning(f"[ToolResourceSearcher] 链接处理结果不完整: file_name={file_name}, share_link={share_link}")
                        
                except Exception as e:
                    logger.error(f'[ToolResourceSearcher] 转存失败 "{item.get("title", "未知")}" {url}: {e}')
                    continue
        
        # 记录执行时间
        execution_time = time.time() - start_time
        logger.info(f"[ToolResourceSearcher] 搜索执行耗时: {execution_time:.2f} 秒, 找到结果: {len(unique_results)}")
        
        return unique_results 