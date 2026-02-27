# Emby.Plugin.StashBox

Emby 插件，支持多个 Stash-Box 实例的外部 ID 跳转。

## 功能

- 支持 5 个 Stash-Box 实例的外部链接跳转：
  - **StashDB** - https://stashdb.org
  - **ThePornDB** - https://theporndb.net
  - **FansDB** - https://fansdb.cc
  - **JAVStash** - https://javstash.org
  - **PMVStash** - https://pmvstash.org
- 每个实例可独立启用/禁用

## 安装

1. 从 [Releases](https://github.com/mayziran/StashtoEmby/releases) 下载 `Emby.Plugin.StashBox.dll`
2. 复制到 Emby 插件目录
3. 重启 Emby 服务器

## 配置

**管理 → 插件 → StashBox → 设置**

| 实例 | 默认状态 |
|------|---------|
| StashDB | ✅ 启用 |
| ThePornDB | ❌ 禁用 |
| FansDB | ✅ 启用 |
| JAVStash | ✅ 启用 |
| PMVStash | ✅ 启用 |

> **ThePornDB 说明**：默认禁用以避免与 [ThePornDB Jellyfin 插件](https://github.com/ThePornDatabase/Jellyfin.Plugin.ThePornDB) 冲突。如未安装该插件，可在此启用。

## NFO 格式

```xml
<uniqueid type="stashdb">scenes\019bb7c5-xxxx-xxxx</uniqueid>
<uniqueid type="theporndb">scenes\7322d484-xxxx-xxxx</uniqueid>
```

**注意：** 使用反斜杠 `\`（Emby 会将 `/` 视为路径分隔符）

## 使用

1. 配合 `auto_move_organized.py` 脚本自动生成 NFO
2. 在 Emby 中刷新媒体库
3. 安装后，Emby 详情页会显示外部链接按钮，点击即可跳转到对应 Stash-Box 实例

## 支持的 Emby 版本

- Emby Server 4.7.x - 4.9.x
