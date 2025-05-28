# ToolPoint 积分管理工具

一个集成了积分管理、查询、交易和签到重置功能的综合插件。

## 功能特点

### 1. 管理员功能
- 加积分：给指定用户增加积分
- 减积分：给指定用户减少积分
- 设置积分：设置指定用户的积分数值

### 2. 重置签到功能
- 重置所有用户的签到状态

### 3. 查询积分功能
- 查询当前用户的积分数量

### 4. 积分交易功能
- 用户之间进行积分转账

## 配置说明

配置文件位于 `plugins/ToolPoint/config.toml`，包含以下配置项：

```toml
[ToolPoint]
# 插件总开关
enable = true

# 管理员功能配置
admin-point-enable = true
admin-point-command-format = "加积分/减积分/设置积分 数量 @用户/wxid"

# 重置签到功能配置
reset-signin-enable = true
reset-signin-command = ["重置签到"]

# 查询积分功能配置
query-point-enable = true
query-point-command = ["查询积分", "积分"]

# 积分交易功能配置
point-trade-enable = true
point-trade-command = ["转账"]
point-trade-command-format = "转账 数量 @用户"
```

## 使用方法

### 管理员功能
1. 加积分
   ```
   加积分 100 @用户
   加积分 100 wxid
   ```

2. 减积分
   ```
   减积分 50 @用户
   减积分 50 wxid
   ```

3. 设置积分
   ```
   设置积分 200 @用户
   设置积分 200 wxid
   ```

### 重置签到功能
```
重置签到
```

### 查询积分功能
```
查询积分
积分
```

### 积分交易功能
```
转账 100 @用户
```

## 注意事项

1. 管理员功能仅限管理员使用
2. 积分转账时，转账金额必须为正整数
3. 转账时积分不足会提示失败
4. 所有功能都可以在配置文件中单独开启或关闭
5. 使用@功能时，请使用机器人的@功能，不要手动输入@

## 作者信息

- 作者：HenryXiaoYang
- 版本：1.0.0
- 描述：积分管理工具 