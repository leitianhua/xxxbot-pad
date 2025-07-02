import requests
import json
import urllib.parse
import urllib3
import sqlite3
import os
import datetime

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 线报商品API接口
def get_xianbao_data(text):
    url = "https://api.zhetaoke.com:20001/api/api_xianbao.ashx"

    # 必填参数
    params = {
        "appkey": "2a77607fa088417a8fcb257d1fbb3088",
        "id": None,
        "type": None,
        "page": 1,
        "page_size": 2000,
        "msg": 1,
        "interval": 360,
        "q": text,
    }
    # 发送请求，禁用SSL验证
    response = requests.get(url, params=params, verify=False)

    # 处理响应
    if response.status_code == 200:
        try:
            result = response.json()
            if result.get("status") == 200:
                return result.get("msg", [])
            else:
                print(f"获取线报失败: {result.get('status')}, 消息: {result.get('content', '')}")
                return []
        except json.JSONDecodeError:
            print("响应解析失败")
        return []
    else:
        print(f"请求失败: {response.status_code}")
        return []


def main():
    # 获取当前时间
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{current_time}] 开始获取线报数据...")
    xianbao_keywords = ["锝物", "得物", "鍀物"]
    count = 0
    # 调用API获取线报数据
    for keyword in xianbao_keywords:
        # 调用API获取线报数据
        xianbao_data = get_xianbao_data(keyword)
        print(f"{keyword}-数量：{len(xianbao_data)}")
        count += len(xianbao_data)

    print(f"总数量：{count}")


if __name__ == "__main__":
    main()
