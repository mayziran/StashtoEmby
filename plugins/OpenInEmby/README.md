# Open in Emby

一个 Stash 插件，在场景页面工具栏添加"Open in Emby"按钮，通过 Stash ID 匹配 Emby 中的视频并跳转到详情页。

## 功能特点

- 🔘 **工具栏按钮** - 在场景页面自动显示 Emby 跳转按钮
- 🔗 **Stash ID 匹配** - 通过 `stash.{id}` 精确匹配 Emby 视频
- 🌐 **双地址支持** - 内网地址 API 查询，外网地址网页跳转

## 前置依赖

**必须配合 Emby 的 Stash 插件使用！**

- Emby 需要安装：[Jellyfin.Plugin.Stash](https://github.com/DirtyRacer1337/Jellyfin.Plugin.Stash)

## 安装

将 `OpenInEmby` 文件夹复制到 Stash 插件目录，重启 Stash。

## 配置选项

| 配置项 | 类型 | 描述 |
|--------|------|------|
| `Emby 服务器地址（跳转用）` | 字符串 | 用于网页跳转的外网地址 |
| `Emby 内网地址（API 用）` | 字符串 | 用于后端 API 请求的内网地址 |
| `Emby API Key` | 字符串 | Emby 控制台生成的 API 密钥 |

## 使用方法

1. 在 **设置 → 插件** 中配置上述三个参数
2. 打开任意场景页面，工具栏会显示绿色的 **Emby 按钮**
3. 点击按钮即可跳转到 Emby 中对应的视频详情页

## 前提条件

- ✅ Emby 中已扫描视频文件
- ✅ Emby 已安装 Stash 插件并正确配置
- ✅ Stash 插件已匹配视频并写入 `ProviderIds.Stash`

## 故障排除

### 提示"未找到匹配"
- 检查 Emby 中是否已安装 Stash 插件
- 在 Emby 中刷新该视频的元数据

### 按钮不显示
- 确认在场景页面（URL 包含 `/scenes/xxx`）

## 版本历史

### 1.0.0
- 初始版本
