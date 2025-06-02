import requests
import json
import urllib.parse
import urllib3
import sqlite3
import os
import datetime

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 初始化数据库
def init_database():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xianbao.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 创建表（如果不存在）- 修改表结构，只使用pic作为主键
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
        chunwenzi TEXT
    )
    ''')
    
    conn.commit()
    return conn


# 线报商品API接口
def convert_taobao_link(text):
    url = "https://api.zhetaoke.com:20001/api/api_xianbao.ashx"

    # 必填参数
    params = {
        "appkey": "2a77607fa088417a8fcb257d1fbb3088",
        "id": None,
        "type": None,
        "page": 1,
        "page_size": 1000000,
        "msg": 1,
        "interval": 1440,
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


# 保存数据到数据库，返回新数据列表
def save_to_database(data_list):
    if not data_list:
        return []
    
    conn = init_database()
    cursor = conn.cursor()
    new_data_items = []
    
    for item in data_list:
        pic = item.get('pic', '')
        
        # 如果pic为空，则跳过该记录
        if not pic:
            continue
            
        # 检查记录是否已存在（仅使用pic进行去重）
        cursor.execute("SELECT 1 FROM xianbao WHERE pic = ?", (pic,))
        if not cursor.fetchone():
            try:
                # 插入新记录
                cursor.execute('''
                INSERT INTO xianbao (
                    code, add_time, type, id, content, plat, pic, num_id, 
                    plat2, type2, cid1, cid1_name, cid2, cid2_name, cid3, cid3_name, chunwenzi
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    item.get('chunwenzi', '')
                ))
                new_data_items.append(item)
            except sqlite3.IntegrityError:
                # 如果出现主键冲突，跳过此条记录
                pass
    
    conn.commit()
    conn.close()
    return new_data_items


def main():
    # 获取当前时间
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{current_time}] 开始获取线报数据...")
    
    # 调用API获取线报数据
    xianbao_data = convert_taobao_link("得物")
    
    # 保存到数据库并获取新数据列表
    new_data_items = save_to_database(xianbao_data)
    
    # 打印结果
    if new_data_items:
        print(f"[{current_time}] 发现 {len(new_data_items)} 条新线报数据:")
        for idx, item in enumerate(new_data_items, 1):
            print(f"[{idx}] {item.get('content', '')}")
    else:
        print(f"[{current_time}] 没有新数据")


if __name__ == "__main__":
    main()
