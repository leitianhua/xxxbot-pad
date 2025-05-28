# ToolPollinationsChat 插件

一个基于 Pollinations.ai API 的聊天插件，支持文本和语音回复，以及多种角色切换。

## 功能特点

- 🤖 支持多种角色切换（助手、暴躁老马、诗人等）
- 🔊 支持语音回复（多种语音类型可选）
- 💬 支持上下文记忆功能
- 🧠 使用 Pollinations.ai 的 OpenAI 兼容接口

## 安装方法

1. 将插件文件夹放入 `plugins` 目录
2. 重命名 `config.toml.template` 为 `config.toml`（如果不存在）
3. 根据需要修改配置文件
4. 重启机器人或使用插件管理命令加载插件

## 使用方法

### 基本聊天

```
p问 [问题内容]
p聊 [问题内容]
```

### 角色管理

```
p角色列表                # 查看可用角色
p切换角色 [角色名]       # 切换角色
```

### 语音设置

```
p语音开关 开/关          # 开启/关闭语音回复
p设置语音 [语音类型]     # 设置语音类型
```

### 记忆管理

```
p清除记忆                # 清除当前会话记忆
p清除记忆 all            # 清除所有会话记忆
```

## 可用的语音类型

- `alloy` - 全能型中性语音
- `echo` - 低沉深邃的语音
- `fable` - 平静温暖的语音
- `onyx` - 坚定有力的语音
- `nova` - 友好精力充沛的语音
- `shimmer` - 轻快愉悦的语音

## 配置文件说明

配置文件使用 TOML 格式，主要包含以下几个部分：

```toml
[basic]
# 是否启用插件
enable = true

[command_prefixes]
# 命令前缀配置
chat = ["p问", "p聊"]
voice_toggle = ["p语音开关"]
voice_set = ["p设置语音"]
clear_memory = ["p清除记忆"]
role_list = ["p角色列表"]
role_switch = ["p切换角色"]

[voice]
# 语音设置
enable = false
default_type = "alloy"

[memory]
# 记忆设置
enable = true
max_history = 10

[roles]
# 角色设置
default = "助手"

# 角色定义
[roles.助手]
name = "助手"
description = """
你是一个专业、友好且乐于助人的AI助手...
"""

[roles.暴躁老马]
name = "暴躁老马"
description = """
你现在要扮演一个脾气暴躁、说话粗鲁但内心善良的老马...
"""

[api]
# API设置
model = "openai"
```

## 自定义角色

可以在配置文件中添加自定义角色，格式如下：

```toml
[roles.自定义角色名]
name = "显示名称"
description = """
角色的详细描述和行为指南...
"""
```

## 注意事项

- 语音功能需要网络连接到 Pollinations.ai 服务器
- 角色切换会清除当前会话的历史记录
- 插件默认使用 OpenAI 兼容模型

## 版本历史

- v0.2: 重构插件结构，角色设定改为配置文件方式
- v0.1: 初始版本，基本聊天和语音功能

## 作者

AI Assistant