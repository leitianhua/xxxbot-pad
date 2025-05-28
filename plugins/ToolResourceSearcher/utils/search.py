import requests
import re
import logging
from typing import List, Dict, Any, Optional
from loguru import logger  # 替换为loguru
from bs4 import BeautifulSoup


class ResourceSearch:
    """资源搜索类，用于从多个来源搜索网盘资源"""

    def __init__(self, conf):
        """初始化资源搜索类
        Args:
            conf: 配置信息
        """
        # 通用请求头
        self.quark_headers = {
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
            'accept-language': 'zh-CN,zh;q=0.9'
        }
        
        self.waliso_headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'zh-CN,zh;q=0.9',
            'content-length': '147',
            'content-type': 'application/json',
            'origin': 'https://waliso.com',
            'priority': 'u=1, i',
            'referer': 'https://waliso.com/',
            'sec-ch-ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        }

    def get_id_from_url(self, url: str) -> tuple:
        """从夸克网盘分享链接中提取分享ID
        Args:
            url: 分享链接，如 https://pan.quark.cn/s/3a1b2c3d
        Returns:
            tuple: (pwd_id, pdir_fid)
        """
        url = url.replace("https://pan.quark.cn/s/", "")
        pattern = r"(\w+)(#/list/share.*/(\w+))?"
        match = re.search(pattern, url)
        if match:
            pwd_id = match.group(1)
            if match.group(2):
                pdir_fid = match.group(3)
            else:
                pdir_fid = 0
            return pwd_id, pdir_fid
        else:
            return None, None

    def get_stoken(self, pwd_id: str) -> tuple:
        """验证夸克网盘分享资源是否有效
        Args:
            pwd_id: 分享ID
        Returns:
            tuple: (是否有效, stoken或错误信息)
        """
        url = "https://drive-m.quark.cn/1/clouddrive/share/sharepage/token"
        querystring = {"pr": "ucpro", "fr": "h5"}
        payload = {"pwd_id": pwd_id, "passcode": ""}
        try:
            response = requests.post(url, json=payload, headers=self.quark_headers, params=querystring, timeout=3).json()
            if response.get("data"):
                return True, response["data"]["stoken"]
            else:
                return False, response["message"]
        except Exception as e:
            logger.error(f"验证夸克链接失败: {e}")
            return False, str(e)

    def search_source1(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索来源1 - 从kkkob.com获取资源
        Args:
            keyword: 搜索关键词
        Returns:
            list: 搜索结果列表
        """
        url_default = "http://s.kkkob.com"
        items_json = []
        
        try:
            logger.info(f"搜索来源1: {keyword}")
            
            # 获取token
            token_response = requests.get(f"{url_default}/v/api/getToken", headers=self.quark_headers, timeout=5)
            if token_response.status_code != 200:
                logger.warning(f"搜索来源1获取token失败: {token_response.status_code}")
                return items_json
                
            token_data = token_response.json()
            token = token_data.get('token', '')
            
            if not token:
                logger.warning("搜索来源1获取token为空")
                return items_json
                
            logger.info(f"搜索来源1获取token成功: {token[:10]}...")
            
            # 准备搜索数据
            search_data = {
                'name': keyword,
                'token': token
            }
            search_headers = {
                'Content-Type': 'application/json'
            }
            
            # 定义正则表达式模式
            pattern = r'https://pan\.quark\.cn/[^\s]*'
            
            # 尝试线路2
            logger.info("搜索来源1尝试线路2")
            juzi_response = requests.post(
                f"{url_default}/v/api/getJuzi", 
                json=search_data, 
                headers=search_headers, 
                timeout=5
            )
            
            if juzi_response.status_code == 200:
                juzi_data = juzi_response.json()
                if juzi_data.get('list'):
                    for item in juzi_data['list']:
                        if re.search(pattern, item.get('answer', '')):
                            match = re.search(pattern, item['answer'])
                            if match:
                                link = match.group(0)
                                title = re.sub(r'\s*[\(（]?(夸克)?[\)）]?\s*', '', item.get('question', ''))
                                
                                logger.info(f"搜索来源1线路2找到资源: {title}")
                                logger.info(f"搜索来源1线路2找到链接: {link}")
                                
                                items_json.append({
                                    'title': title,
                                    'url': link
                                })
                                break
            
            # 如果线路2没有结果，尝试线路4
            if not items_json:
                logger.info("搜索来源1尝试线路4")
                xiaoyu_response = requests.post(
                    f"{url_default}/v/api/getXiaoyu", 
                    json=search_data, 
                    headers=search_headers, 
                    timeout=5
                )
                
                if xiaoyu_response.status_code == 200:
                    xiaoyu_data = xiaoyu_response.json()
                    if xiaoyu_data.get('list'):
                        for item in xiaoyu_data['list']:
                            if re.search(pattern, item.get('answer', '')):
                                match = re.search(pattern, item['answer'])
                                if match:
                                    link = match.group(0)
                                    title = re.sub(r'\s*[\(（]?(夸克)?[\)）]?\s*', '', item.get('question', ''))
                                    
                                    logger.info(f"搜索来源1线路4找到资源: {title}")
                                    logger.info(f"搜索来源1线路4找到链接: {link}")
                                    
                                    items_json.append({
                                        'title': title,
                                        'url': link
                                    })
                                    break
            
        except Exception as e:
            logger.error(f"搜索来源1失败: {e}")
        
        # 记录最终的有效记录数量和内容
        logger.info(f"搜索来源1过滤后: 得到{len(items_json)}条有效记录")
        for index, item in enumerate(items_json):
            logger.info(f"搜索来源1最终结果[{index}]: 标题={item['title']}, URL={item['url']}")
        
        return items_json

    def search_source2(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索来源2
        Args:
            keyword: 搜索关键词
        Returns:
            list: 搜索结果列表
        """
        url = "https://www.hhlqilongzhu.cn/api/ziyuan_nanfeng.php"
        params = {"keysearch": keyword}
        items_json = []
        
        try:
            logger.info(f"搜索来源2: {keyword}")
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                total_items = len(data.get("data", []))
                logger.info(f"搜索来源2结果: 状态码={response.status_code}, 总共{total_items}条记录")
                
                if data.get("data") and isinstance(data.get("data"), list) and len(data.get("data")) > 0:
                    for index, item in enumerate(data['data']):
                        logger.info(f"搜索来源2原始数据[{index}]: {item}")
                        if ('quark' in str(item) or 'baidu' in str(item)):
                            if 'data_url' in item and '链接：' in item['data_url']:
                                url = item['data_url'].split("链接：")[1].strip()
                                title = item['title']
                                logger.info(f"搜索来源2提取链接[{index}]: {url}")
                                logger.info(f"搜索来源2提取标题[{index}]: {title}")
                                
                                # 检查URL格式
                                if not url.startswith("http"):
                                    logger.warning(f"搜索来源2无效URL格式[{index}]: {url}")
                                    continue
                                
                                item_dict = {
                                    'title': title,
                                    'url': url
                                }
                                items_json.append(item_dict)
                                if len(items_json) >= 5:
                                    logger.info("搜索来源2已达到5条记录上限，停止处理")
                                    break
                            else:
                                logger.warning(f"搜索来源2记录缺少链接信息[{index}]: {item}")
                        else:
                            logger.info(f"搜索来源2记录不包含夸克或百度链接[{index}]")
            else:
                logger.warning(f"搜索来源2响应状态码异常: {response.status_code}")
        except Exception as e:
            logger.error(f"搜索来源2失败: {e}")
        
        # 记录最终的有效记录数量和内容
        logger.info(f"搜索来源2过滤后: 得到{len(items_json)}条有效记录")
        for index, item in enumerate(items_json):
            logger.info(f"搜索来源2最终结果[{index}]: 标题={item['title']}, URL={item['url']}")
        
        return items_json
        
    def search_source3(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索来源3 - 从qileso.com获取资源
        Args:
            keyword: 搜索关键词
        Returns:
            list: 搜索结果列表
        """
        url = f'https://www.qileso.com/tag/quark?s={keyword}'
        items_json = []
        
        try:
            logger.info(f"搜索来源3: {keyword}")
            response = requests.get(url, headers=self.quark_headers, timeout=5)
            if response.status_code == 200:
                logger.info(f"搜索来源3返回状态码: {response.status_code}")
                
                # 解析第一页结果，获取第一条链接
                soup = BeautifulSoup(response.text, 'html.parser')
                post_list = soup.find('div', class_='list-group post-list mt-3')
                
                if post_list:
                    # 找到第一个链接
                    first_link = post_list.find('a')
                    if first_link and 'href' in first_link.attrs:
                        detail_url = first_link['href']
                        logger.info(f"搜索来源3找到详情页链接: {detail_url}")
                        
                        # 访问详情页
                        detail_response = requests.get(detail_url, headers=self.quark_headers, timeout=5)
                        if detail_response.status_code == 200:
                            detail_soup = BeautifulSoup(detail_response.text, 'html.parser')
                            
                            # 提取页面标题
                            title_tag = detail_soup.find('title')
                            title = title_tag.text if title_tag else "未知标题"
                            # 去掉 " - 奇乐搜" 部分
                            title = re.sub(r' - 奇乐搜|网盘|夸克', '', title)
                            title = f"②{title}"
                            
                            # 寻找夸克网盘链接
                            links = detail_soup.find_all('a')
                            for link in links:
                                href = link.get('href', '')
                                if href and href.startswith('https://pan.quark.cn/s/'):
                                    logger.info(f"搜索来源3找到资源链接: {href}")
                                    
                                    item_dict = {
                                        'title': title,
                                        'url': href
                                    }
                                    items_json.append(item_dict)
                                    break
                    else:
                        logger.warning("搜索来源3未找到有效链接")
                else:
                    logger.warning("搜索来源3未找到资源列表")
            else:
                logger.warning(f"搜索来源3响应状态码异常: {response.status_code}")
        except Exception as e:
            logger.error(f"搜索来源3失败: {e}")
        
        # 记录最终的有效记录数量和内容
        logger.info(f"搜索来源3过滤后: 得到{len(items_json)}条有效记录")
        for index, item in enumerate(items_json):
            logger.info(f"搜索来源3最终结果[{index}]: 标题={item['title']}, URL={item['url']}")
        
        return items_json
        
    def search_source4(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索来源4 - 从pansearch.me获取资源
        Args:
            keyword: 搜索关键词
        Returns:
            list: 搜索结果列表
        """
        url = f'https://www.pansearch.me/search?keyword={keyword}&pan=quark'
        items_json = []
        
        try:
            logger.info(f"搜索来源4: {keyword}")
            response = requests.get(url, headers=self.quark_headers, timeout=5)
            if response.status_code == 200:
                logger.info(f"搜索来源4返回状态码: {response.status_code}")
                
                # 使用BeautifulSoup解析HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 查找包含资源信息的div元素
                resource_divs = soup.find_all('div', class_=lambda x: x and 'whitespace-pre-wrap' in x and 'break-all' in x)
                
                for index, div in enumerate(resource_divs):
                    content = div.get_text()
                    
                    # 提取标题和URL
                    title_match = re.search(r'名称：(.*?)\n\n描述：', content, re.DOTALL)
                    url_match = re.search(r'链接：(https://pan\.quark\.cn/s/[a-zA-Z0-9]+)', content)
                    
                    if title_match and url_match:
                        title = f"「推荐」{title_match.group(1).strip()}"
                        url = url_match.group(1).strip()
                        
                        logger.info(f"搜索来源4提取标题[{index}]: {title}")
                        logger.info(f"搜索来源4提取链接[{index}]: {url}")
                        
                        item_dict = {
                            'title': title,
                            'url': url
                        }
                        items_json.append(item_dict)
                        
                        if len(items_json) >= 3:
                            logger.info("搜索来源4已达到3条记录上限，停止处理")
                            break
                    else:
                        logger.warning(f"搜索来源4无法提取标题或链接[{index}]")
            else:
                logger.warning(f"搜索来源4响应状态码异常: {response.status_code}")
        except Exception as e:
            logger.error(f"搜索来源4失败: {e}")
        
        # 记录最终的有效记录数量和内容
        logger.info(f"搜索来源4过滤后: 得到{len(items_json)}条有效记录")
        for index, item in enumerate(items_json):
            logger.info(f"搜索来源4最终结果[{index}]: 标题={item['title']}, URL={item['url']}")
        
        return items_json

    def search_source5(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索来源5 - 从waliso.com获取资源
        Args:
            keyword: 搜索关键词
        Returns:
            list: 搜索结果列表
        """
        url = "https://waliso.com/v1/search/disk"
        headers = self.waliso_headers.copy()
        
        # 搜索参数
        params = {
            "page": 1,
            "q": keyword,
            "user": "",
            "exact": False,
            "format": [],
            "share_time": "",
            "size": 15,
            "type": "QUARK",  # 只搜索夸克网盘
            "exclude_user": [],
            "adv_params": {"wechat_pwd": ""}
        }
        
        result_json = []
        try:
            logger.info(f"[QURAK] 开始瓦力搜索: {keyword}")
            
            # 禁用SSL警告
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # 使用不验证SSL证书的方式访问API
            response = requests.post(
                url, 
                json=params, 
                headers=headers, 
                timeout=15,
                verify=False,  # 不验证SSL证书
                allow_redirects=True  # 允许重定向
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    if data.get("code") == 200 and data.get("data") and data["data"].get("list"):
                        items = data["data"]["list"]
                        logger.info(f"[QURAK] 瓦力搜索找到 {len(items)} 个结果")
                        
                        i = 1
                        for item in items:
                            if i > 5:  # 最多返回5个结果
                                break
                                
                            title = item.get("disk_name", "未知标题").replace("<em>", "").replace("</em>", "")
                            url = item.get("link", "")
                            
                            if not url:
                                continue
                                
                            # 验证资源有效性
                            if "quark" in url:
                                item_dict = {
                                    'title': title,
                                    'url': url
                                }
                                result_json.append(item_dict)
                                i += 1

                        logger.info(f"[QURAK] 瓦力搜索验证后有效结果: {len(result_json)} 个")
                    else:
                        logger.warning(f"[QURAK] 瓦力搜索结果为空或API返回错误: {data.get('msg')}")
                except ValueError as json_err:
                    logger.error(f"[QURAK] 瓦力搜索JSON解析错误: {json_err}")
            else:
                logger.error(f"[QURAK] 瓦力搜索请求失败，状态码: {response.status_code}")
                
        except Exception as e:
            logger.error(f"[QURAK] 瓦力搜索异常: {e}")
            
        return result_json 