import requests
import json
import urllib.parse
import urllib3

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def convert_taobao_link(text):
    url = "https://api.zhetaoke.cn:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

    # 必填参数
    params = {
        "appkey": "2a77607fa088417a8fcb257d1fbb3088",  # 折淘客的对接秘钥appkey
        "sid": "185073",  # 添加sid参数，根据API错误信息需要提供
        "unionId": "2036757202",  # 京东联盟ID，为一串数字。
        "pid": "mm_375930105_2518750017_111777500003",  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
        "tkl": text,  # 需要转换的文本，进行URL编码
    }
    # 发送请求，禁用SSL验证
    response = requests.get(url, params=params, verify=False)

    # 处理响应
    if response.status_code == 200:
        try:
            result = response.json()
            if result.get("status") == 200:
                return result.get("content", "")
            else:
                return f"转链失败: {result.get('status')}, 消息: {result.get('content', '')}"
        except json.JSONDecodeError:
            return "响应解析失败"
    else:
        return f"请求失败: {response.status_code}"


def main():
    sample_text = """
建议先收藏姐妹们
1⃣领🧧https://u.jd.com/DOXcmof 

白边20（https://u.jd.com/DaXTlW6 
单白新拍2（https://u.jd.com/DaXJuYK  
彩虹🌈：https://u.jd.com/DrXki2f 
黑胶https://u.jd.com/DrXlxHL 
Kitty https://u.jd.com/DDXj3v6 
波点 https://u.jd.com/DrXAOmM 
花雨 https://u.jd.com/DOXEI43 
涂鸦 https://u.jd.com/D6Xj0Gx  
粉边https://u.jd.com/DOXJD2u 
蓝边https://u.jd.com/DGXJkeI 
黑边https://u.jd.com/D1X4a4k 
黑边https://u.jd.com/DOXHkl1 （新
紫边https://u.jd.com/DG9KpoB 
锦绣https://u.jd.com/DDXN55A 
人鱼https://u.jd.com/DDX45n9 
和风 https://u.jd.com/D1XE8pb （新
天青石https://u.jd.com/DG9dlMn 
懒蛋蛋https://u.jd.com/DO9d1do 
石灰岩https://u.jd.com/D6XRfQw 
马卡龙https://u.jd.com/Dg9Lmgy 
双子星https://u.jd.com/D6XjiEx 

宽白https://u.jd.com/D6X5Y2w 
宽彩🌈https://u.jd.com/D6XXVND （抢购模式
宽黑边https://u.jd.com/DaXmLlS 
宽黑白https://u.jd.com/DDXRWKm 

⚠：先收藏可以去刷新姐妹们可以，小梨也只是听说具体以通知为主哈还是

    """

    # 测试样例
    # sample_text = """
    # ——薅羊毛啦——
    # 0.1下单 备注：纸巾
    # 一号一单换号可以无限拍
    # https://s.click.taobao.com/wBFYRUr
    # 6覆ZHI3(5yFzVOvgWYx) CZ6478 ,打開/
    # http://gchat.qpic.cn/download?appid=1407&fileid=EhR1Bcf4Yb8UaVbZpVCPJ__i-xCRvRielQQg_woo6sHnv4rDjQMyBHByb2RQgL2jAVoQ_zF0pFzautHmArnR59hwj3oCiWY&rkey=CAISMJ990Sco_OuL5zDnUnxf2cLUHzfAUEAyNCbNREKqUSJnxAvifgL1IPzgPo0uCADL1A&spec=0
    # """
    # sample_text = """
    # 1⃣领🧧https://u.jd.com/DOXcmof
    # 1⃣领🧧https://u.jd.com/DOXcmof
    # 1⃣领🧧https://u.jd.com/DOXcmof
    # 1⃣领🧧https://u.jd.com/DOXcmof
    # 1⃣领🧧https://u.jd.com/DOXcmof
    # 1⃣领🧧https://u.jd.com/DOXcmof
    # """

    # 调用API转换链接
    converted_text = convert_taobao_link(sample_text)

    print("原始文本:")
    print(sample_text)
    print("\n转换后文本:")
    print(converted_text)


if __name__ == "__main__":
    main()
