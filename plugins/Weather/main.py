import os
import requests
import re
import json
from datetime import datetime, timedelta
from loguru import logger
import tomllib

from WechatAPI import WechatAPIClient
from utils.decorators import *
from utils.plugin_base import PluginBase

BASE_URL_ALAPI = "https://v2.alapi.cn/api/"

class Weather(PluginBase):
    description = "天气查询插件"
    author = "chatgpt"
    version = "0.2.0"

    def __init__(self):
        super().__init__()
        
        # 获取配置文件路径
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 读取基本配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)  # 读取插件开关
            self.alapi_token = basic_config.get("alapi_token", None)
            
            if not self.alapi_token:
                logger.warn("[Weather] 已初始化，但在配置中找不到alapi_token")
            else:
                logger.info("[Weather] 已初始化，成功加载alapi_token")
                
            self.condition_2_and_3_cities = None  # 天气查询，存储重复城市信息
            
            # 禁用请求验证警告
            logger.warning("[Weather] SSL证书验证已禁用，这可能带来安全风险")
            
            # 禁用urllib3的InsecureRequestWarning
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
        except Exception as e:
            logger.error(f"[Weather] 加载配置失败: {str(e)}")
            self.enable = False  # 如果加载失败，禁用插件
            self.alapi_token = None

    async def async_init(self):
        return

    @on_text_message(priority=88)
    async def handle_weather(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return True  # 允许其他插件处理
        
        content = message.get("Content", "").strip()
        logger.debug(f"[Weather] 收到消息: {content}")
        
        # 天气查询
        weather_match = re.match(r'^(?:(.{2,7}?)(?:市|县|区|镇)?|(\d{7,9}))(:?今天|明天|后天|7天|七天)?(?:的)?天气$', content)
        if not weather_match:
            return True  # 不匹配天气查询格式，继续处理
            
        # 如果匹配成功，提取城市或ID和日期
        city_or_id = weather_match.group(1) or weather_match.group(2)
        date = weather_match.group(3)
        
        if not self.alapi_token:
            # 根据是否为群聊决定发送方式
            if message.get("IsGroup", False):
                await bot.send_at_message(
                    message["FromWxid"], 
                    "请先配置alapi的token", 
                    [message["SenderWxid"]]
                )
            else:
                await bot.send_text_message(message["FromWxid"], "请先配置alapi的token")
        else:
            weather_info = self.get_weather(city_or_id, date, content)
            
            # 根据是否为群聊决定发送方式
            if message.get("IsGroup", False):
                await bot.send_at_message(
                    message["FromWxid"], 
                    weather_info, 
                    [message["SenderWxid"]]
                )
            else:
                await bot.send_text_message(message["FromWxid"], weather_info)
                
        return False  # 阻止其他插件处理

    def get_weather(self, city_or_id: str, date: str, content):
        url = BASE_URL_ALAPI + 'tianqi'
        isFuture = date in ['明天', '后天', '七天', '7天']
        if isFuture:
            url = BASE_URL_ALAPI + 'tianqi/seven'
        # 判断使用id还是city请求api
        if city_or_id.isnumeric():  # 判断是否为纯数字，也即是否为 city_id
            params = {
                'city_id': city_or_id,
                'token': f'{self.alapi_token}'
            }
        else:
            city_info = self.check_multiple_city_ids(city_or_id)
            if city_info:
                data = city_info['data']
                formatted_city_info = "\n".join(
                    [f"{idx + 1}) {entry['province']}--{entry['leader']}, ID: {entry['city_id']}"
                     for idx, entry in enumerate(data)]
                )
                return f"查询 <{city_or_id}> 具有多条数据：\n{formatted_city_info}\n请使用id查询，发送'id'天气"

            params = {
                'city': city_or_id,
                'token': f'{self.alapi_token}'
            }
        try:
            weather_data = self.make_request(url, "GET", params=params)
            if isinstance(weather_data, dict) and weather_data.get('code') == 200:
                data = weather_data['data']
                if isFuture:
                    formatted_output = []
                    for num, d in enumerate(data):
                        if num == 0:
                            formatted_output.append(f"🏙️ 城市: {d['city']} ({d['province']})\n")
                        if date == '明天' and num != 1:
                            continue
                        if date == '后天' and num != 2:
                            continue
                        basic_info = [
                            f"🕒 日期: {d['date']}",
                            f"🌦️ 天气: 🌞{d['wea_day']}| 🌛{d['wea_night']}",
                            f"🌡️ 温度: 🌞{d['temp_day']}℃| 🌛{d['temp_night']}℃",
                            f"🌅 日出/日落: {d['sunrise']} / {d['sunset']}",
                        ]
                        for i in d['index']:
                            basic_info.append(f"{i['name']}: {i['level']}")
                        formatted_output.append("\n".join(basic_info) + '\n')
                    return "\n".join(formatted_output)
                update_time = data['update_time']
                dt_object = datetime.strptime(update_time, "%Y-%m-%d %H:%M:%S")
                formatted_update_time = dt_object.strftime("%m-%d %H:%M")
                # Basic Info
                if not city_or_id.isnumeric() and data['city'] not in content:  # 如果返回城市信息不是所查询的城市，重新输入
                    return "输入不规范，请输<国内城市+(今天|明天|后天|七天|7天)+天气>，比如 '广州天气'"
                formatted_output = []
                basic_info = (
                    f"🏙️ 城市: {data['city']} ({data['province']})\n"
                    f"🕒 更新: {formatted_update_time}\n"
                    f"🌦️ 天气: {data['Weather']}\n"
                    f"🌡️ 温度: ↓{data['min_temp']}℃| 现{data['temp']}℃| ↑{data['max_temp']}℃\n"
                    f"🌬️ 风向: {data['wind']}\n"
                    f"💦 湿度: {data['humidity']}\n"
                    f"🌅 日出/日落: {data['sunrise']} / {data['sunset']}\n"
                )
                formatted_output.append(basic_info)

                # Clothing Index,处理部分县区穿衣指数返回null
                chuangyi_data = data.get('index', {})[0].get('chuangyi', {})
                if chuangyi_data:
                    chuangyi_level = chuangyi_data.get('level', '未知')
                    chuangyi_content = chuangyi_data.get('content', '未知')
                else:
                    chuangyi_level = '未知'
                    chuangyi_content = '未知'

                chuangyi_info = f"👚 穿衣指数: {chuangyi_level} - {chuangyi_content}\n"
                formatted_output.append(chuangyi_info)
                # Next 7 hours Weather
                ten_hours_later = dt_object + timedelta(hours=10)

                future_weather = []
                for hour_data in data['hour']:
                    forecast_time_str = hour_data['time']
                    forecast_time = datetime.strptime(forecast_time_str, "%Y-%m-%d %H:%M:%S")

                    if dt_object < forecast_time <= ten_hours_later:
                        future_weather.append(f"     {forecast_time.hour:02d}:00 - {hour_data['wea']} - {hour_data['temp']}°C")

                future_weather_info = "⏳ 未来10小时的天气预报:\n" + "\n".join(future_weather)
                formatted_output.append(future_weather_info)

                # Alarm Info
                if data.get('alarm'):
                    alarm_info = "⚠️ 预警信息:\n"
                    for alarm in data['alarm']:
                        alarm_info += (
                            f"🔴 标题: {alarm['title']}\n"
                            f"🟠 等级: {alarm['level']}\n"
                            f"🟡 类型: {alarm['type']}\n"
                            f"🟢 提示: \n{alarm['tips']}\n"
                            f"🔵 内容: \n{alarm['content']}\n\n"
                        )
                    formatted_output.append(alarm_info)

                return "\n".join(formatted_output)
            else:
                return self.handle_error(weather_data, "获取失败，请查看服务器log")

        except Exception as e:
            return self.handle_error(e, "获取天气信息失败")

    def make_request(self, url, method="GET", headers=None, params=None, data=None, json_data=None):
        try:
            if method.upper() == "GET":
                response = requests.request(method, url, headers=headers, params=params, verify=False)
            elif method.upper() == "POST":
                response = requests.request(method, url, headers=headers, data=data, json=json_data, verify=False)
            else:
                return {"success": False, "message": "Unsupported HTTP method"}

            return response.json()
        except Exception as e:
            return e

    def handle_error(self, error, message):
        logger.error(f"{message}，错误信息：{error}")
        return message

    def load_city_conditions(self):
        if self.condition_2_and_3_cities is None:
            try:
                json_file_path = os.path.join(os.path.dirname(__file__), 'duplicate-citys.json')
                if os.path.exists(json_file_path):
                    with open(json_file_path, 'r', encoding='utf-8') as f:
                        self.condition_2_and_3_cities = json.load(f)
                else:
                    # 如果文件不存在，返回None
                    logger.warning("[Weather] 找不到duplicate-citys.json文件")
            except Exception as e:
                logger.error(f"[Weather] 加载城市数据失败: {str(e)}")
                return None

    def check_multiple_city_ids(self, city):
        self.load_city_conditions()
        if self.condition_2_and_3_cities:
            city_info = self.condition_2_and_3_cities.get(city, None)
            if city_info:
                return city_info
        return None

    @on_at_message(priority=88)
    async def handle_at(self, bot: WechatAPIClient, message: dict):
        if not self.enable:
            return True  # 允许其他插件处理
        
        content = message.get("Content", "").strip()
        logger.debug(f"[Weather] 收到@消息: {content}")
        
        # 检查是否为@天气消息
        city_match = re.search(r'@天气\s+(\S+?)(?:市|县|区|镇)?(?:的)?(?:今天|明天|后天|7天|七天)?(?:天气)?', content)
        if not city_match:
            return True  # 不匹配天气查询格式，继续处理
            
        city = city_match.group(1)
        logger.info(f"[Weather] 解析到城市: {city}")
        
        # 提取日期信息
        date_match = re.search(r'(今天|明天|后天|7天|七天)', content)
        date = date_match.group(1) if date_match else None
        
        if not self.alapi_token:
            # 根据是否为群聊决定发送方式
            if message.get("IsGroup", False):
                await bot.send_at_message(
                    message["FromWxid"], 
                    "请先配置alapi的token", 
                    [message["SenderWxid"]]
                )
            else:
                await bot.send_text_message(message["FromWxid"], "请先配置alapi的token")
        else:
            weather_info = self.get_weather(city, date, city)
            
            # 根据是否为群聊决定发送方式
            if message.get("IsGroup", False):
                await bot.send_at_message(
                    message["FromWxid"], 
                    weather_info, 
                    [message["SenderWxid"]]
                )
            else:
                await bot.send_text_message(message["FromWxid"], weather_info)
                
        return False  # 阻止其他插件处理 