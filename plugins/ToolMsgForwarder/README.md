# ToolMsgForwarder 微信消息转发插件

ToolMsgForwarder 是一个功能强大的微信消息转发插件，可以根据配置规则将特定来源的消息（文本、图片、文件、视频）转发到指定的目标。

## 重要说明

**注意：本插件不会自动创建默认配置。必须手动创建正确的配置文件，否则插件将被禁用。**

## 主要功能

- 支持转发文本、图片、文件和视频消息
- 可以监听特定群聊或私聊消息
- 可以只监听群内特定成员的消息
- 可以转发到多个目标
- 支持为群聊、发送者和接收者配置友好的别名
- 可以在转发的消息前添加来源信息
- **新增: 支持消息处理钩子系统，实现消息转发前后的二次处理**

## 配置方法

1. 在 `plugins/ToolMsgForwarder/` 目录下创建 `config.toml` 文件
2. 按照以下格式配置规则

### 配置文件格式（推荐使用表格数组格式）

```toml
[ToolMsgForwarder]
# 全局设置
enable = true     # 总开关，设为false将完全禁用插件所有转发功能
priority = 99     # 插件优先级，值越小优先级越高

# ==================== 文本消息规则 ====================
# 规则1: 指定群聊中的特定成员消息转发
[[ToolMsgForwarder.text_rules]]
enabled = true                              # 此规则的开关
name = "测试群"                             # 群聊的易读名称，会在转发消息前缀中显示
from_wxid = "50144964587@chatroom"          # 来源群聊ID
listen_specific_senders_in_group = ["wxid_l4u1u9bgq5u022"]  # 监听的群成员
sender_names = { "wxid_l4u1u9bgq5u022" = "张三" }  # 发送者别名映射，会在转发消息前缀中显示
to_wxids = ["wxid_l4u1u9bgq5u022"]          # 转发目标wxid
target_names = { "wxid_l4u1u9bgq5u022" = "接收者" }  # 接收者别名（仅用于日志显示）
prepend_info = true                         # 是否在转发内容前添加来源信息

# 规则2: 私聊消息转发
[[ToolMsgForwarder.text_rules]]
enabled = true
name = "小助手"  # 来源用户的易读名称
from_wxid = "wxid_assistant123"  # 来源用户ID
to_wxids = ["wxid_admin456"]  # 转发目标
prepend_info = true  # 添加来源信息

# ==================== 图片消息规则 ====================
[[ToolMsgForwarder.image_rules]]
enabled = true
name = "照片群"
from_wxid = "12345678@chatroom"
listen_specific_senders_in_group = ["wxid_photo999"]
sender_names = { "wxid_photo999" = "摄影师" }
to_wxids = ["wxid_collector123"]
prepend_info = true

# ==================== 文件消息规则 ====================
[[ToolMsgForwarder.file_rules]]
enabled = true
name = "文档组"
from_wxid = "87654321@chatroom"
to_wxids = ["wxid_archive123", "wxid_manager456"]
prepend_info = true

# ==================== 视频消息规则 ====================
[[ToolMsgForwarder.video_rules]]
enabled = true
name = "视频群"
from_wxid = "99887766@chatroom"
listen_specific_senders_in_group = ["wxid_video888"]
sender_names = { "wxid_video888" = "视频小助手" }
to_wxids = ["wxid_admin123"]
prepend_info = true
```

### 配置说明

| 字段 | 说明 |
|------|------|
| enabled | 是否启用此规则 |
| name | 来源（群聊或用户）的易读名称，会在转发消息前缀中显示 |
| from_wxid | 来源ID（群聊以@chatroom结尾） |
| listen_specific_senders_in_group | 只监听群内特定成员的消息（仅当来源是群聊时有效） |
| sender_names | 发送者别名映射，格式为 `{ "wxid" = "别名" }` |
| to_wxids | 转发目标ID数组 |
| target_names | 接收者别名映射，仅用于日志显示 |
| prepend_info | 是否在转发内容前添加来源信息 |

## 转发消息格式

转发的消息格式如下：

- 群消息：`[转发自群聊 群名称 (由 发送者名称 发送)]:`
- 私聊消息：`[转发自 联系人名称]:`

## 消息处理钩子系统 (v0.5.0新增)

插件现在支持通过钩子系统对消息进行二次处理，可以在消息处理的关键节点注册处理函数。

### 钩子点说明

| 钩子点 | 触发时机 | 参数 | 返回值 |
|------|---------|------|-------|
| before_match | 规则匹配前 | (bot, message, None) | 处理后的message或None(拦截) |
| after_match | 规则匹配后 | (bot, message, rule) | 处理后的message或None(拦截) |
| before_forward | 消息转发前 | (bot, forward_context, rule) | 处理后的context或None(拦截) |
| after_forward | 消息转发后 | (bot, result_context, rule) | 无特定要求 |

### 使用示例

你可以创建一个新插件来注册消息处理器，而不需要修改ToolMsgForwarder的代码。以下是一个示例：

```python
from utils.plugin_base import PluginBase
from loguru import logger

class MyMessageProcessor(PluginBase):
    description = "ToolMsgForwarder的消息处理扩展"
    author = "你的名字"
    version = "1.0.0"
    
    def __init__(self):
        super().__init__()
        self.forwarder = None
        logger.info("[MyMessageProcessor] 初始化")
        
    async def on_plugins_loaded(self, plugins_map):
        """当所有插件加载完成后，注册处理器"""
        if "ToolMsgForwarder" in plugins_map:
            self.forwarder = plugins_map["ToolMsgForwarder"]
            # 注册各个处理器
            self.forwarder.register_processor("before_match", self.pre_process_message)
            self.forwarder.register_processor("before_forward", self.modify_forward_content)
            self.forwarder.register_processor("after_forward", self.log_forwarded_message)
            logger.info("[MyMessageProcessor] 已注册消息处理器")
        else:
            logger.error("[MyMessageProcessor] 未找到ToolMsgForwarder插件")
            
    async def pre_process_message(self, bot, message, rule):
        """消息预处理：在规则匹配前处理消息"""
        # 示例：如果是文本消息，可以进行敏感词过滤
        if "Content" in message and isinstance(message["Content"], str):
            content = message["Content"]
            # 敏感词替换示例
            filtered_content = content.replace("敏感词", "**")
            if filtered_content != content:
                logger.info("[MyMessageProcessor] 已过滤敏感词")
                message["Content"] = filtered_content
        return message
    
    async def modify_forward_content(self, bot, context, rule):
        """修改转发内容：在消息转发前修改内容"""
        # 示例：为转发的文本添加额外信息
        if context.get("msg_type") == "text" and "content_to_send" in context:
            # 添加时间戳
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            context["content_to_send"] += f"\n[转发时间: {timestamp}]"
            logger.info("[MyMessageProcessor] 已添加时间戳到转发内容")
        return context
    
    async def log_forwarded_message(self, bot, result, rule):
        """记录转发结果：在消息转发后记录信息"""
        success = result.get("success", False)
        target = result.get("target_name", "未知目标")
        if success:
            logger.info(f"[MyMessageProcessor] 成功转发到 {target}")
        else:
            error = result.get("error", "未知错误")
            logger.warning(f"[MyMessageProcessor] 转发到 {target} 失败: {error}")
        # 这个钩子点不需要返回值
        
    def on_unload(self):
        """插件卸载时，取消注册处理器"""
        if self.forwarder:
            self.forwarder.unregister_processor("before_match", self.pre_process_message)
            self.forwarder.unregister_processor("before_forward", self.modify_forward_content)
            self.forwarder.unregister_processor("after_forward", self.log_forwarded_message)
            logger.info("[MyMessageProcessor] 已取消注册消息处理器")
```

### 处理器函数接口

处理器函数必须是异步函数(async)，并按照以下接口实现：

```python
async def processor_name(bot, message_or_context, rule=None):
    # 处理逻辑
    # 返回处理后的message或context
    # 或者返回None表示拦截消息
    return processed_result
```

### forward_context 对象说明

`before_forward` 和 `after_forward` 钩子点接收的 `forward_context` 包含以下字段：

```python
{
    "target_wxid": "目标用户ID",
    "target_name": "目标用户名称",
    "content_to_send": "要发送的内容",
    "text_prefix": "媒体消息的文本前缀",
    "prepend_info": True/False,  # 是否添加前缀
    "msg_type": "消息类型(text/image/file/video)",
    "filename": "文件名(文件消息才有)",
    "success": True/False,  # 仅在after_forward中有
    "error": "错误信息"  # 转发失败时才有
}
```

## 注意事项

1. 必须手动创建配置文件，插件不会自动创建默认配置
2. wxid 必须准确，否则消息将无法正确转发
3. 至少需要配置一条有效的规则，否则插件将被禁用
4. 如果配置文件有语法错误，插件将被禁用
5. 修改配置后需要重启机器人才能生效
6. 处理器函数必须返回处理后的消息/上下文，或者返回None表示拦截消息
7. 尽量保证处理器函数的高效，避免阻塞其他消息的处理

## 故障排除

- 如果插件无法正常工作，请检查日志中的错误信息
- 确保配置文件的格式正确，符合TOML语法规范
- 确保wxid正确且有效
- 检查是否有规则被成功启用
- 如果使用了消息处理钩子系统，检查处理器函数是否正确实现并返回了适当的值

## 版本历史

- 0.5.0: 添加消息处理钩子系统，支持消息的二次处理
- 0.4.0: 移除默认配置创建功能，需要手动配置才能使用
- 0.3.6: 支持在配置中设置名称别名，优先显示别名而不是wxid
- 0.3.0: 支持表格数组配置格式
- 0.2.5: 完善配置加载，增强错误处理
- 0.2.4: 简化代码结构
- 0.2.0: 添加多目标转发和群内成员过滤功能
- 0.1.0: 初始版本 