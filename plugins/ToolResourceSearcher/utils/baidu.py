import time
import requests
import re
import random
import string
from typing import Any, Union, Tuple, List
from loguru import logger

# 常量定义
BASE_URL = "https://pan.baidu.com"
HEADERS = {
    'Host': 'pan.baidu.com',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Sec-Fetch-Site': 'same-site',
    'Sec-Fetch-Mode': 'navigate',
    'Referer': 'https://pan.baidu.com',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7,en-GB;q=0.6,ru;q=0.5',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
}
ERROR_CODES = {
    -1: '链接错误，链接失效或缺少提取码',
    -4: '转存失败，无效登录。请退出账号在其他地方的登录',
    -6: '转存失败，请用浏览器无痕模式获取 Cookie 后再试',
    -7: '转存失败，转存文件夹名有非法字符，不能包含 < > | * ? \\ :，请改正目录名后重试',
    -8: '转存失败，目录中已有同名文件或文件夹存在',
    -9: '链接错误，提取码错误',
    -10: '转存失败，容量不足',
    -12: '链接错误，提取码错误',
    -62: '转存失败，链接访问次数过多，请手动转存或稍后再试',
    0: '转存成功',
    2: '转存失败，目标目录不存在',
    4: '转存失败，目录中存在同名文件',
    12: '转存失败，转存文件数超过限制',
    20: '转存失败，容量不足',
    105: '链接错误，所访问的页面不存在',
    404: '转存失败，秒传无效',
}
EXP_MAP = {"1 天": "1", "7 天": "7", "30 天": "30", "永久": "0"}

# 预编译正则表达式
SHARE_ID_REGEX = re.compile(r'"shareid":(\d+?),"')
USER_ID_REGEX = re.compile(r'"share_uk":"(\d+?)","')
FS_ID_REGEX = re.compile(r'"fs_id":(\d+?),"')
SERVER_FILENAME_REGEX = re.compile(r'"server_filename":"(.+?)","')
ISDIR_REGEX = re.compile(r'"isdir":(\d+?),"')

# 实用函数
def normalize_link(url_code: str) -> str:
    """标准化百度网盘链接格式
    Args:
        url_code: 原始链接
    Returns:
        str: 标准化后的链接
    """
    normalized = url_code.replace("share/init?surl=", "s/1")
    if "?pwd=" not in normalized and " " in normalized:
        parts = normalized.split()
        if len(parts) == 2:
            normalized = f"{parts[0]}?pwd={parts[1]}"
    return normalized


def parse_url_and_code(url_code: str) -> Tuple[str, str]:
    """解析百度网盘链接和提取码
    Args:
        url_code: 百度网盘链接，可能包含提取码
    Returns:
        tuple: (链接, 提取码)
    """
    url_parts = url_code.split("?pwd=")
    return url_parts[0], url_parts[1] if len(url_parts) > 1 else ""


def parse_response(response: str) -> Union[List[str], int]:
    """从响应中解析出转存所需的参数
    Args:
        response: 网页响应内容
    Returns:
        list/int: 成功返回参数列表，失败返回错误码
    """
    share_id = SHARE_ID_REGEX.search(response)
    user_id = USER_ID_REGEX.search(response)
    fs_ids = FS_ID_REGEX.findall(response)
    
    if not (share_id and user_id and fs_ids):
        return -1
    
    return [share_id.group(1), user_id.group(1), fs_ids]


def update_cookie(bdclnd: str, cookie: str) -> str:
    """更新Cookie中的BDCLND参数
    Args:
        bdclnd: 新的BDCLND值
        cookie: 原始Cookie
    Returns:
        str: 更新后的Cookie
    """
    if "BDCLND=" in cookie:
        cookie = re.sub(r"BDCLND=[^;]+", f"BDCLND={bdclnd}", cookie)
    else:
        cookie += f"; BDCLND={bdclnd}"
    return cookie


def generate_code(length=4) -> str:
    """生成随机提取码
    Args:
        length: 提取码长度
    Returns:
        str: 随机提取码
    """
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))


class Baidu:
    """百度网盘操作类，用于自动化处理网盘文件"""

    def __init__(self, conf):
        """初始化百度网盘操作类
        Args:
            conf: 配置信息
        """
        # 获取百度账号配置
        baidu_account = next((acc for acc in conf.get("accounts", []) if acc.get("type") == "baidu" and acc.get("enable", True)), None)
        
        # 获取账号信息
        cookie = baidu_account.get("cookie", "") if baidu_account else ""
        save_dir = baidu_account.get("save_dir", "") if baidu_account else ""
        
        self.s = requests.Session()
        self.headers = HEADERS.copy()
        self.headers["Cookie"] = cookie
        self.bdstoken = ''
        self.folder_name = save_dir

    def get_bdstoken(self) -> Union[str, int]:
        """获取bdstoken
        Returns:
            str/int: 成功返回bdstoken，失败返回错误码
        """
        url = f'{BASE_URL}/api/gettemplatevariable'
        params = {
            'clienttype': '0',
            'app_id': '38824127',
            'web': '1',
            'fields': '["bdstoken","token","uk","isdocuser","servertime"]'
        }
        try:
            r = self.s.get(url=url, params=params, headers=self.headers, timeout=10, verify=False)
            if r.json()['errno'] != 0:
                return r.json()['errno']
            return r.json()['result']['bdstoken']
        except Exception as e:
            logger.error(f"获取bdstoken失败: {e}")
            return -1

    def get_dir_list(self, folder_name: str) -> Union[List[Any], int]:
        """获取目录列表
        Args:
            folder_name: 文件夹路径
        Returns:
            list/int: 成功返回文件列表，失败返回错误码
        """
        url = f'{BASE_URL}/api/list'
        params = {
            'order': 'time',
            'desc': '1',
            'showempty': '0',
            'web': '1',
            'page': '1',
            'num': '1000',
            'dir': folder_name,
            'bdstoken': self.bdstoken
        }
        try:
            r = self.s.get(url=url, params=params, headers=self.headers, timeout=15, verify=False)
            if r.json()['errno'] != 0:
                return r.json()['errno']
            return r.json()['list']
        except Exception as e:
            logger.error(f"获取目录列表失败: {e}")
            return -1

    def create_dir(self, folder_name: str) -> int:
        """创建目录
        Args:
            folder_name: 文件夹名
        Returns:
            int: 错误码，0表示成功
        """
        url = f'{BASE_URL}/api/create'
        params = {
            'a': 'commit',
            'bdstoken': self.bdstoken
        }
        data = {
            'path': folder_name,
            'isdir': '1',
            'block_list': '[]',
        }
        try:
            r = self.s.post(url=url, params=params, headers=self.headers, data=data, timeout=15, verify=False)
            return r.json()['errno']
        except Exception as e:
            logger.error(f"创建目录失败: {e}")
            return -1

    def verify_pass_code(self, link_url: str, pass_code: str) -> Union[str, int]:
        """验证提取码
        Args:
            link_url: 分享链接
            pass_code: 提取码
        Returns:
            str/int: 成功返回randsk，失败返回错误码
        """
        url = f'{BASE_URL}/share/verify'
        params = {
            'surl': link_url[25:48],
            'bdstoken': self.bdstoken,
            't': str(int(round(time.time() * 1000))),
            'channel': 'chunlei',
            'web': '1',
            'clienttype': '0'
        }
        data = {
            'pwd': pass_code,
            'vcode': '',
            'vcode_str': ''
        }
        try:
            r = self.s.post(url=url, params=params, headers=self.headers, data=data, timeout=10, verify=False)
            if r.json()['errno'] != 0:
                return r.json()['errno']
            return r.json()['randsk']
        except Exception as e:
            logger.error(f"验证提取码失败: {e}")
            return -1

    def get_transfer_params(self, url: str) -> str:
        """获取转存参数
        Args:
            url: 分享链接
        Returns:
            str: 网页响应内容
        """
        try:
            r = self.s.get(url=url, headers=self.headers, timeout=15, verify=False)
            return r.content.decode("utf-8")
        except Exception as e:
            logger.error(f"获取转存参数失败: {e}")
            return ""

    def transfer_file(self, params_list: List[str], folder_name: str) -> Tuple[int, str]:
        """转存文件
        Args:
            params_list: 转存参数列表
            folder_name: 目标文件夹名
        Returns:
            tuple: (错误码, 文件ID)
        """
        url = f'{BASE_URL}/share/transfer'
        params = {
            'shareid': params_list[0],
            'from': params_list[1],
            'bdstoken': self.bdstoken,
            'channel': 'chunlei',
            'web': '1',
            'clienttype': '0'
        }
        data = {
            'fsidlist': f"[{','.join(params_list[2])}]",
            'path': f'/{folder_name}'
        }
        try:
            r = self.s.post(url=url, params=params, headers=self.headers, data=data, timeout=30, verify=False)
            errno = r.json()['errno']
            new_fid = ""
            if errno == 0:
                new_fid = r.json()["info"][0]["fsid"]
            elif errno == 4:
                new_fid = r.json()["duplicated"]["list"][0]["fs_id"]
            return errno, new_fid
        except Exception as e:
            logger.error(f"转存文件失败: {e}")
            return -1, ""

    def create_share(self, fs_id: int, expiry: str, password: str) -> Union[str, int]:
        """创建分享
        Args:
            fs_id: 文件ID
            expiry: 过期时间
            password: 提取码
        Returns:
            str/int: 成功返回分享链接，失败返回错误码
        """
        url = f'{BASE_URL}/share/set'
        params = {
            'channel': 'chunlei',
            'bdstoken': self.bdstoken,
            'clienttype': '0',
            'app_id': '250528',
            'web': '1'
        }
        data = {
            'period': expiry,
            'pwd': password,
            'eflag_disable': 'true',
            'channel_list': '[]',
            'schannel': '4',
            'fid_list': f'[{fs_id}]'
        }
        try:
            r = self.s.post(url=url, params=params, headers=self.headers, data=data, timeout=15, verify=False)
            if r.json()['errno'] != 0:
                return r.json()['errno']
            return r.json()['link']
        except Exception as e:
            logger.error(f"创建分享失败: {e}")
            return -1

    def store(self, link_code: str) -> Tuple[bool, str, str]:
        """保存分享链接中的文件到自己的网盘并分享
        Args:
            link_code: 分享链接
        Returns:
            tuple: (是否是新文件, 文件名, 分享链接)
        """
        try:
            # 获取bdstoken
            self.bdstoken = self.get_bdstoken()
            if isinstance(self.bdstoken, int):
                logger.error(f"获取bdstoken失败，错误代码：{ERROR_CODES.get(self.bdstoken)}")
                return False, "", ""
                
            # 预处理链接至标准格式
            normalized_link = normalize_link(link_code)
            
            # 提取 URL和提取码
            url, password = parse_url_and_code(normalized_link)
            
            # 验证提取码
            bdclnd = self.verify_pass_code(url, password)
            if isinstance(bdclnd, int):
                logger.error(f"验证提取码失败，错误代码：{ERROR_CODES.get(bdclnd)}")
                return False, "", ""
                
            # 更新Cookie
            self.headers["Cookie"] = update_cookie(bdclnd, self.headers["Cookie"])
            
            # 获取转存参数
            response = self.get_transfer_params(url)
            params = parse_response(response)
            if isinstance(params, int):
                logger.error(f"获取转存参数失败，错误代码：{ERROR_CODES.get(params)}")
                return False, "", ""
                
            # 提取文件名
            filename_match = SERVER_FILENAME_REGEX.search(response)
            file_name = filename_match.group(1) if filename_match else "未知文件"
            
            # 创建目标目录
            if self.folder_name:
                result = self.get_dir_list(f"/{self.folder_name}")
                if isinstance(result, int):
                    result = self.create_dir(self.folder_name)
                    if result != 0:
                        logger.error(f"创建目录失败，错误代码：{ERROR_CODES.get(result)}")
                        return False, file_name, ""
            
            # 执行转存
            result, new_fid = self.transfer_file(params, self.folder_name)
            if result not in [0, 4]:
                logger.error(f"转存失败，错误代码：{ERROR_CODES.get(result)}")
                return False, file_name, ""
                
            # 分享文件
            expiry = "1 天"  # 默认1天过期
            share_password = generate_code()
            share_result = self.create_share(new_fid, EXP_MAP[expiry], share_password)
            if isinstance(share_result, int):
                logger.error(f"分享失败，错误代码：{share_result}")
                return False, file_name, ""
                
            share_link = f"{share_result}?pwd={share_password}"
            return True, file_name, share_link
            
        except Exception as e:
            logger.error(f"百度网盘转存失败: {e}")
            return False, "", "" 