# encoding:utf-8
import threading
import requests
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel import channel_factory
from channel.gewechat.gewechat_channel import GeWeChatChannel
from channel.wechat.wechat_channel import WechatChannel
from common.log import logger
from typing import List, Any
import time
from concurrent.futures import ThreadPoolExecutor
import os
import json
import plugins
from plugins import *
from plugins.rs.utils.search import ResourceSearch
from plugins.rs.utils.quark import Quark
from plugins.rs.utils.baidu import Baidu


@plugins.register(
    name="rs",
    namecn="网盘资源搜索",
    desire_priority=100,
    desc="搜索并转存网盘资源",
    version="1.0",
    author="lei",
)
class ResourceSearcher(Plugin):
    def __init__(self):
        super().__init__()
        try:
            # 加载配置
            self.conf = super().load_config()
            if not self.conf:
                logger.info("[rs] 读取其他配置")
                self.conf = self._load_self_config()
            
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
                    logger.info("[rs] 夸克网盘账号验证成功")
                else:
                    logger.error("[rs] 夸克网盘账号验证失败，请检查cookie是否有效")
            
            # 验证百度网盘cookie有效性（如果需要可以实现）
            
            # 注册事件处理器
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context

            # 开启一个线程每分钟清除过期资源
            self.clear_expired_resources_thread = threading.Thread(target=self.clear_expired_resources)
            self.clear_expired_resources_thread.daemon = True  # 设置为守护线程，防止主线程退出时子线程还在运行
            self.clear_expired_resources_thread.start()
            
            logger.info("[rs] 初始化成功")
        except Exception as e:
            logger.warn(f"[rs] 初始化失败: {e}")
            raise e
            
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
                logger.info(f"[rs] 夸克网盘账号: {nickname}")
                return True
            else:
                logger.error(f"[rs] 夸克网盘账号验证失败: {account_info.get('message', '未知错误')}")
                return False
        except Exception as e:
            logger.error(f"[rs] 验证夸克账号时发生错误: {str(e)}")
            return False

    # 每分钟清除过期资源
    def clear_expired_resources(self):
        while True:
            try:
                quark = Quark(self.conf)
                quark.del_expired_resources(self.expired_time)
                time.sleep(60)  # 每分钟执行一次
            except Exception as e:
                logger.error(f"[rs] 清除过期资源失败: {e}")
                time.sleep(60)

    # 处理上下文信息
    def on_handle_context(self, e_context: EventContext):
        # 只处理文本类型消息
        if e_context["context"].type not in [ContextType.TEXT]:
            return

        # 获取消息内容
        msg_content = e_context["context"].content.strip()
        logger.debug(f"[rs] 当前监听信息： {msg_content}")

        # 发送文本回复的函数
        def send_text_reply(reply_content):
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = reply_content
            e_context['reply'] = reply
            decorated_reply = e_context["channel"]._decorate_reply(e_context['context'], reply)
            e_context["channel"].send(decorated_reply, e_context['context'])  # 立即发送消息

        # 处理搜索指令
        if any(msg_content.startswith(prefix) for prefix in ["搜", "搜索"]):

            # 移除前缀，获取搜索内容
            def remove_prefix(content, prefixes):
                for prefix in prefixes:
                    if content.startswith(prefix):
                        return content[len(prefix):].strip()
                return content.strip()

            # 搜索内容
            search_content = remove_prefix(msg_content, ["搜", "搜索"]).strip()
            
            # 构建回复内容
            def build_reply(response_data):
                if not response_data:
                    reply_text = f"搜索内容：{search_content}"
                    reply_text += "\n⚠未找到，可换个关键词尝试哦"
                    reply_text += "\n————————————"
                    reply_text += "\n⚠搜索指令：搜:XXX 或 搜索:XXX"
                else:
                    reply_text = f"搜索内容：{search_content}\n————————————"
                    for item in response_data:
                        reply_text += f"\n🌐️{item.get('title', '未知标题')}"
                        reply_text += f"\n{item.get('url', '未知URL')}"
                        reply_text += "\n————————————"
                    
                    if any(item.get('is_time') == 1 for item in response_data):
                        reply_text += "\n⚠资源来源网络，30分钟后删除"
                        reply_text += "\n⚠避免失效，请及时保存~💾"

                send_text_reply(reply_text)

            # 执行搜索
            def perform_search():
                # 通知用户正在进行搜索
                send_text_reply(f" 🔍正在获取资源，请稍等...")
                
                # 启动线程进行全网搜索
                threading.Thread(target=lambda: build_reply(self.search_and_store(search_content))).start()

            # 启动搜索线程
            threading.Thread(target=perform_search).start()
            
            # 告诉框架我们已经处理了这个消息
            e_context["reply"] = None
            e_context.action = EventAction.BREAK_PASS
            return

    # 多线程全网搜索并转存
    def search_and_store(self, keyword: str) -> List[dict]:
        """
        搜索资源并转存到网盘
        
        Args:
            keyword: 搜索关键词
            
        Returns:
            包含转存后资源信息的列表
        """
        logger.info(f'[rs] 搜索关键字: {keyword}')
        start_time = time.time()
        
        # 创建资源搜索对象
        rs = ResourceSearch(self.conf)
        
        # 获取所有搜索方法并并行执行，
        search_methods = [
            'search_source1',
            'search_source2',
            'search_source3',
            'search_source4'
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
            logger.debug(f"[rs] 搜索结果: {len(results) if results else 0}条")
            if not results:
                continue
                
            for item in results:
                # 限制结果数量
                if count >= 5:
                    logger.debug(f"[rs] 结果已达到5条上限，停止处理")
                    break
                    
                url = item.get('url')
                if not url:
                    logger.debug(f"[rs] 跳过没有URL的项: {item}")
                    continue
                
                logger.debug(f"[rs] 处理搜索结果: {item.get('title', '未知')} - {url}")
                    
                try:
                    file_not_exist = False
                    file_name = ''
                    share_link = ''
                    
                    # 根据链接类型选择相应的网盘处理
                    if 'quark' in url:
                        logger.info(f"[rs] 转存夸克链接: {url}")
                        file_not_exist, file_name, share_link = quark.store(url)
                    elif 'baidu' in url:
                        logger.info(f"[rs] 转存百度链接: {url}")
                        pass
                        # 忽略百度
                        # file_not_exist, file_name, share_link = baidu.store(url)
                    else:
                        logger.warning(f"[rs] 未知链接类型，跳过: {url}")
                        continue
                        
                    # 如果成功处理，添加到结果
                    if file_name and share_link:
                        logger.info(f'[rs] {"新转存" if file_not_exist else "已存在"}: {file_name} - {share_link}')
                        item['url'] = share_link
                        item['is_time'] = 1
                        unique_results.append(item)
                        count += 1
                    else:
                        logger.warning(f"[rs] 链接处理结果不完整: file_name={file_name}, share_link={share_link}")
                        
                except Exception as e:
                    logger.error(f'[rs] 转存失败 "{item.get("title", "未知")}" {url}: {e}')
                    continue
        
        # 记录执行时间
        execution_time = time.time() - start_time
        logger.info(f"[rs] 搜索执行耗时: {execution_time:.2f} 秒, 找到结果: {len(unique_results)}")
        
        return unique_results

    def _load_self_config(self):
        """加载自身配置"""
        try:
            conf_path = os.path.join(os.path.dirname(__file__), "config.json")
            if os.path.exists(conf_path):
                with open(conf_path, "r", encoding="utf-8") as conf_file:
                    return json.loads(conf_file.read())
            return {}
        except Exception as e:
            logger.error(f"[rs] 加载配置文件失败: {e}")
            return {} 