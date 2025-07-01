# 群发言白名单插件 (ToolGroupForbidden)

## 功能介绍

此插件实现了群聊白名单功能，只允许白名单中的成员在群中发言。当非白名单成员在配置的群聊中发送任何消息（文本、图片、视频、文件、语音、表情等）时，插件会自动将该成员移出群聊。

## 配置说明

插件配置文件为 `config.toml`，包含以下配置项：

### 基本配置

```toml
[basic]
# 是否启用插件
enable = true 

# 通知接收人配置，如果为空则不发送通知
# 格式: 接收通知的wxid，例如 "wxid_abc123"
notify_receiver = "wxid_abc123"
```

### 白名单规则配置

使用数组形式配置每个群的白名单规则：

```toml
# 白名单规则配置，使用数组形式
[[whitelist_rules]]
enabled = true                              # 是否启用此规则
name = "测试群1"                            # 群名称，用于日志和通知中显示
group_id = "12345678@chatroom"              # 群聊ID
whitelist = ["wxid_abc123", "wxid_def456"]  # 白名单成员列表

# 可以添加更多群配置
[[whitelist_rules]]
enabled = true
name = "测试群2"
group_id = "87654321@chatroom"
whitelist = ["wxid_xyz789", "wxid_uvw321"]
```

### 群别名配置

```toml
[group_aliases]
# 群聊ID和对应的别名
# 格式: "群聊ID" = "群别名"
"12345678@chatroom" = "测试群1"
"87654321@chatroom" = "测试群2"
# 可以添加多个群聊别名
```

## 使用方法

1. 确保插件已启用（`enable = true`）
2. 为每个需要监控的群聊添加一个 `[[whitelist_rules]]` 配置块：
   - `enabled`: 设置为 `true` 启用此规则
   - `name`: 设置群的易读名称
   - `group_id`: 设置群聊的wxid
   - `whitelist`: 设置允许在群中发言的成员wxid列表
3. 如需接收详细的通知消息，配置 `notify_receiver` 为接收通知的wxid
4. 重启机器人或重载插件

## 通知功能

如果配置了 `notify_receiver`，会向指定接收人发送通知，包含以下信息：
- 群名称
- 成员ID
- 消息类型
- 处理结果（成功移除或移除失败）

## 注意事项

1. 机器人需要是群主或管理员才能移除群成员
2. 群聊ID可以通过机器人日志或其他方式获取
3. 成员wxid可以通过机器人日志或其他方式获取
4. 白名单成员不会被移除，只有非白名单成员在发言后会被移除
5. 机器人自身的wxid应该添加到白名单中，否则可能无法正常工作
6. 建议配置群别名，方便在日志和通知中识别群聊 