# Emby.Plugin.StashBox

Emby 插件，支持多个 Stash-Box 实例的外部 ID 跳转。

## 功能

- 支持 5 个 Stash-Box 实例的外部链接跳转：
  - **StashDB** - https://stashdb.org
  - **ThePornDB** - https://theporndb.net
  - **FansDB** - https://fansdb.cc
  - **JAVStash** - https://javstash.org
  - **PMVStash** - https://pmvstash.org
- 每个实例可独立启用/禁用，避免与其他插件冲突

## 安装

1. 下载 `Emby.Plugin.StashBox.dll`
2. 复制到 Emby 插件目录：
   ```
   C:\ProgramData\Emby-Server\programdata\plugins\
   ```
3. 重启 Emby 服务器

## 配置

在 Emby 管理界面：
```
管理 → 插件 → StashBox → 设置
```

可以独立启用/禁用每个 Stash-Box 实例。

### 默认配置

- ✅ StashDB - 启用
- ❌ ThePornDB - **禁用**（避免与其他 ThePornDB 插件冲突）
- ✅ FansDB - 启用
- ✅ JAVStash - 启用
- ✅ PMVStash - 启用

## 使用

配合 `auto_move_organized.py` 脚本使用，脚本会自动写入 NFO 文件。

### NFO 格式示例

```xml
<!-- StashDB 视频 -->
<uniqueid type="stashdb" default="true">scenes/019bb7c5-xxxx-xxxx</uniqueid>

<!-- ThePornDB 视频 -->
<uniqueid type="theporndb">scenes/7322d484-xxxx-xxxx</uniqueid>

<!-- FansDB 视频 -->
<uniqueid type="fansdb">scenes/xxxx-xxxx-xxxx</uniqueid>
```

安装后，Emby 详情页会显示外部链接按钮，点击即可跳转到对应 Stash-Box 实例。

## 注意事项

### ThePornDB 冲突

- 如果已安装其他 ThePornDB 插件，可在本插件配置中禁用 ThePornDB 支持
- 或者在 NFO 中不使用 `type="theporndb"`

### NFO type

- NFO 的 `type` 必须与插件支持的名称一致（小写）
- 例如：`type="stashdb"`、`type="theporndb"` 等

## 支持的 Emby 版本

- Emby Server 4.7.x - 4.9.x
