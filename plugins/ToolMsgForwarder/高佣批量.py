import requests
import json
import urllib.parse

def convert_taobao_link(text):
    """
    API文档: https://api.zhetaoke.com:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx
    """
    url = "https://api.zhetaoke.com:10001/api/open_gaoyongzhuanlian_tkl_piliang.ashx"

    # 必填参数
    params = {
        "appkey": "2a77607fa088417a8fcb257d1fbb3088",  # 折淘客的对接秘钥appkey
        "sid": "185073",  # 添加sid参数，根据API错误信息需要提供
        "unionId" : "2036757202", # 京东联盟ID，为一串数字。
        "pid": "mm_375930105_2518750017_111777500003",  # 淘宝联盟pid，格式为mm_xxx_xxx_xxx
        "tkl": urllib.parse.quote(text),  # 需要转换的文本，进行URL编码
    }

    # 发送请求
    response = requests.get(url, params=params)

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
    # 测试样例
    # sample_text = """
    # ——薅羊毛啦——
    # 0.1下单 备注：纸巾
    # 一号一单换号可以无限拍
    # https://s.click.taobao.com/wBFYRUr
    # 6覆ZHI3(5yFzVOvgWYx) CZ6478 ,打開/
    # http://gchat.qpic.cn/download?appid=1407&fileid=EhR1Bcf4Yb8UaVbZpVCPJ__i-xCRvRielQQg_woo6sHnv4rDjQMyBHByb2RQgL2jAVoQ_zF0pFzautHmArnR59hwj3oCiWY&rkey=CAISMJ990Sco_OuL5zDnUnxf2cLUHzfAUEAyNCbNREKqUSJnxAvifgL1IPzgPo0uCADL1A&spec=0
    # """
    sample_text = """
现在好像都是-1，小梨3个号都没有0.1
🍑￥0vGBVQdgw2R￥/ HU7405

👆复制打开淘*宝就好啦
    """

    # 调用API转换链接
    converted_text = convert_taobao_link(sample_text)

    print("原始文本:")
    print(sample_text)
    print("\n转换后文本:")
    print(converted_text)

if __name__ == "__main__":
    main()