import tomllib
from datetime import datetime
from random import randint

import pytz
from loguru import logger
from WechatAPI import WechatAPIClient
from database.XYBotDB import XYBotDB
from utils.decorators import *
from utils.plugin_base import PluginBase


class ToolPoint(PluginBase):
    description = "积分管理工具"
    author = "HenryXiaoYang"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        logger.info("ToolPoint插件初始化开始")

        try:
            with open("plugins/ToolPoint/config.toml", "rb") as f:
                plugin_config = tomllib.load(f)
            logger.debug("成功加载插件配置文件")

            with open("main_config.toml", "rb") as f:
                main_config = tomllib.load(f)
            logger.debug("成功加载主配置文件")

            config = plugin_config["ToolPoint"]
            main_config = main_config["XYBot"]

            # 基础配置
            self.enable = config["enable"]
            self.admins = main_config["admins"]
            self.timezone = main_config["timezone"]
            self.message_prefix = config["message-prefix"]
            self.message_suffix = config["message-suffix"]
            logger.info(f"插件总开关状态: {self.enable}")
            logger.debug(f"管理员列表: {self.admins}")

            # 管理员功能配置
            self.admin_point_enable = config["admin-point-enable"]
            self.admin_point_command_format = config["admin-point-command-format"]
            logger.info(f"管理员功能开关状态: {self.admin_point_enable}")

            # 重置签到功能配置
            self.reset_signin_enable = config["reset-signin-enable"]
            self.reset_signin_command = config["reset-signin-command"]
            logger.info(f"重置签到功能开关状态: {self.reset_signin_enable}")

            # 查询积分功能配置
            self.query_point_enable = config["query-point-enable"]
            self.query_point_command = config["query-point-command"]
            logger.info(f"查询积分功能开关状态: {self.query_point_enable}")

            # 积分交易功能配置
            self.point_trade_enable = config["point-trade-enable"]
            self.point_trade_command = config["point-trade-command"]
            self.point_trade_command_format = config["point-trade-command-format"]
            logger.info(f"积分交易功能开关状态: {self.point_trade_enable}")

            # 签到功能配置
            self.signin_enable = config["signin-enable"]
            self.signin_command = config["signin-command"]
            self.signin_min_point = config["signin-min-point"]
            self.signin_max_point = config["signin-max-point"]
            self.signin_streak_cycle = config["signin-streak-cycle"]
            self.signin_max_streak_point = config["signin-max-streak-point"]

            self.db = XYBotDB()
            logger.info("数据库连接初始化成功")

            # 每日签到排名数据
            self.today_signin_count = 0
            self.last_reset_date = datetime.now(tz=pytz.timezone(self.timezone)).date()

            logger.info("ToolPoint插件初始化完成")

        except Exception as e:
            logger.error(f"插件初始化失败: {str(e)}", exc_info=True)
            raise

    def _check_and_reset_count(self):
        """检查并重置每日签到计数"""
        current_date = datetime.now(tz=pytz.timezone(self.timezone)).date()
        if current_date != self.last_reset_date:
            self.today_signin_count = 0
            self.last_reset_date = current_date
            logger.debug("重置每日签到计数")

    def _format_message(self, content: str) -> str:
        """格式化消息内容"""
        return f"\n{self.message_prefix}\n{content}{self.message_suffix}"

    @on_text_message(priority=100)
    async def handle_text(self, bot: WechatAPIClient, message: dict):
        try:
            if not self.enable:
                logger.debug("插件已禁用，忽略消息")
                return True

            content = str(message["Content"]).strip()
            command = content.split(" ")
            sender_wxid = message["SenderWxid"]
            logger.debug(f"收到消息: {content} 来自: {sender_wxid}")

            # 签到功能
            if self.signin_enable and command[0] in self.signin_command:
                logger.info("触发签到功能")
                # 检查是否需要重置计数
                self._check_and_reset_count()

                sign_wxid = message["SenderWxid"]
                last_sign = self.db.get_signin_stat(sign_wxid)
                now = datetime.now(tz=pytz.timezone(self.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)

                # 确保 last_sign 用了时区
                if last_sign and last_sign.tzinfo is None:
                    last_sign = pytz.timezone(self.timezone).localize(last_sign)
                last_sign = last_sign.replace(hour=0, minute=0, second=0, microsecond=0)

                if last_sign and (now - last_sign).days < 1:
                    logger.info(f"用户 {sign_wxid} 今日已签到")
                    output = self._format_message("你今天已经签到过了！😠")
                    await bot.send_at_message(message["FromWxid"], output, [sign_wxid])
                    return False

                # 检查是否断开连续签到（超过1天没签到）
                if last_sign and (now - last_sign).days > 1:
                    old_streak = self.db.get_signin_streak(sign_wxid)
                    streak = 1  # 重置连续签到天数
                    streak_broken = True
                else:
                    old_streak = self.db.get_signin_streak(sign_wxid)
                    streak = old_streak + 1 if old_streak else 1  # 如果是第一次签到，从1开始
                    streak_broken = False

                self.db.set_signin_stat(sign_wxid, now)
                self.db.set_signin_streak(sign_wxid, streak)  # 设置连续签到天数
                streak_points = min(streak // self.signin_streak_cycle, self.signin_max_streak_point)  # 计算连续签到奖励

                signin_points = randint(self.signin_min_point, self.signin_max_point)  # 随机积分
                self.db.add_points(sign_wxid, signin_points + streak_points)  # 增加积分

                # 增加签到计数并获取排名
                self.today_signin_count += 1
                today_rank = self.today_signin_count

                output = (
                    f"签到成功！你领到了 {signin_points} 个积分！✅\n"
                    f"你是今天第 {today_rank} 个签到的！🎉\n"
                )

                if streak_broken and old_streak > 0:  # 只有在真的断签且之前有签到记录时才显示
                    output += f"你断开了 {old_streak} 天的连续签到！[心碎]"
                elif streak > 1:
                    output += f"你连续签到了 {streak} 天！"

                if streak_points > 0:
                    output += f" 再奖励 {streak_points} 积分！"

                if streak > 1 and not streak_broken:
                    output += "[爱心]"

                logger.info(f"用户 {sign_wxid} 签到成功，获得 {signin_points} 积分，连续签到 {streak} 天")
                await bot.send_at_message(message["FromWxid"], self._format_message(output), [sign_wxid])
                return False

            # 管理员功能
            elif self.admin_point_enable and command[0] in ["加积分", "减积分", "设置积分"]:
                logger.info(f"触发管理员功能: {command[0]}")
                if sender_wxid not in self.admins:
                    logger.warning(f"非管理员尝试使用管理员功能: {sender_wxid}")
                    await bot.send_text_message(message["FromWxid"], self._format_message("❌你配用这个指令吗？😡"))
                    return False
                elif len(command) < 3 or not command[1].isdigit():
                    logger.warning(f"管理员功能参数错误: {content}")
                    await bot.send_text_message(message["FromWxid"], self._format_message(self.admin_point_command_format))
                    return False

                if command[2].startswith("@") and len(message["Ats"]) == 1:
                    change_wxid = message["Ats"][0]
                elif "@" not in " ".join(command[2:]):
                    change_wxid = command[2]
                else:
                    logger.warning("手动@错误")
                    await bot.send_text_message(message["FromWxid"], self._format_message("❌请不要手动@！"))
                    return False

                change_point = int(command[1])
                nickname = await bot.get_nickname(change_wxid)
                logger.info(f"操作目标: {change_wxid}({nickname}), 积分变动: {change_point}")

                if command[0] == "加积分":
                    self.db.add_points(change_wxid, change_point)
                    new_point = self.db.get_points(change_wxid)
                    output = (
                        f"成功给 {change_wxid} {nickname if nickname else ''} 加了 {change_point} 点积分\n"
                        f"他现在有 {new_point} 点积分"
                    )
                elif command[0] == "减积分":
                    self.db.add_points(change_wxid, -change_point)
                    new_point = self.db.get_points(change_wxid)
                    output = (
                        f"成功给 {nickname if nickname else ''} {change_wxid} 减了 {change_point} 点积分\n"
                        f"他现在有 {new_point} 点积分"
                    )
                else:  # 设置积分
                    self.db.set_points(change_wxid, change_point)
                    output = (
                        f"成功将 {nickname if nickname else ''} {change_wxid} 的积分设置为 {change_point}"
                    )

                logger.info(f"管理员功能执行成功: {output}")
                await bot.send_text_message(message["FromWxid"], self._format_message(output))
                return False

            # 重置签到功能
            elif self.reset_signin_enable and command[0] in self.reset_signin_command:
                logger.info("触发重置签到功能")
                if sender_wxid not in self.admins:
                    logger.warning(f"非管理员尝试重置签到: {sender_wxid}")
                    await bot.send_text_message(message["FromWxid"], self._format_message("❌你配用这个指令吗？😡"))
                    return False
                self.db.reset_all_signin_stat()
                logger.info("签到状态重置成功")
                await bot.send_text_message(message["FromWxid"], self._format_message("成功重置签到状态！"))
                return False

            # 查询积分功能
            elif self.query_point_enable and command[0] in self.query_point_command:
                logger.info(f"触发查询积分功能: {sender_wxid}")
                query_wxid = message["SenderWxid"]
                points = self.db.get_points(query_wxid)
                output = f"你有 {points} 点积分！😄"
                logger.info(f"查询积分结果: {points}")
                await bot.send_at_message(message["FromWxid"], self._format_message(output), [query_wxid])
                return False

            # 积分交易功能
            elif self.point_trade_enable and command[0] in self.point_trade_command:
                logger.info("触发积分交易功能")
                if len(command) < 3:
                    logger.warning(f"积分交易参数不足: {content}")
                    await bot.send_at_message(message["FromWxid"], self._format_message(self.point_trade_command_format), [message["SenderWxid"]])
                    return False
                elif not command[1].isdigit():
                    logger.warning(f"积分交易金额无效: {command[1]}")
                    await bot.send_at_message(message["FromWxid"], self._format_message("🈚️转账积分无效(必须为正整数!)"),
                                            [message["SenderWxid"]])
                    return False
                elif len(message["Ats"]) != 1:
                    logger.warning("积分交易@目标无效")
                    await bot.send_at_message(message["FromWxid"], self._format_message("转账失败❌\n🈚️转账人无效！"),
                                            [message["SenderWxid"]])
                    return False

                points = int(command[1])
                target_wxid = message["Ats"][0]
                trader_wxid = message["SenderWxid"]
                logger.info(f"积分交易: {trader_wxid} -> {target_wxid}, 金额: {points}")

                # 检查积分是否足够
                trader_points = self.db.get_points(trader_wxid)
                if trader_points < points:
                    logger.warning(f"积分不足: {trader_wxid} 当前积分 {trader_points}, 需要 {points}")
                    await bot.send_at_message(message["FromWxid"], self._format_message("转账失败❌\n积分不足！😭"),
                                            [message["SenderWxid"]])
                    return False

                self.db.safe_trade_points(trader_wxid, target_wxid, points)
                logger.info("积分交易执行成功")

                trader_nick, target_nick = await bot.get_nickname([trader_wxid, target_wxid])
                trader_points = self.db.get_points(trader_wxid)
                target_points = self.db.get_points(target_wxid)

                output = (
                    f"✅积分转账成功！✨\n"
                    f"🤝{trader_nick} 现在有 {trader_points} 点积分➖\n"
                    f"🤝{target_nick} 现在有 {target_points} 点积分➕\n"
                    f"⌚️时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                logger.info(f"积分交易完成: {output}")
                await bot.send_at_message(message["FromWxid"], self._format_message(output), [trader_wxid, target_wxid])
                return False

            return True

        except Exception as e:
            logger.error(f"处理消息时发生错误: {str(e)}", exc_info=True)
            await bot.send_text_message(message["FromWxid"], self._format_message("❌处理消息时发生错误，请查看日志"))
            return False 