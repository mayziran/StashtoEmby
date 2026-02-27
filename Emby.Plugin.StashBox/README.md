# Emby.Plugin.StashBox

Emby 插件，支持多个 Stash-Box 实例的外部 ID 跳转。

## 功能

- 读取 NFO 中的 `<uniqueid type="stashdb">` 字段
- 支持 5 个 Stash-Box 实例：
  - **StashDB** - https://stashdb.org
  - **ThePornDB** - https://theporndb.net
  - **FansDB** - https://fansdb.cc
  - **JAVStash** - https://javstash.org
  - **PMV Stash** - https://pmvstash.org
- 点击 Emby 详情页的外部链接，直接跳转到对应网站

## NFO 格式

```xml
<uniqueid type="stashdb" default="true">https://stashdb.org/graphql|7322d484-bd20-4856-816a-27646cd414f0</uniqueid>
```

**格式说明：**
- `type="stashdb"` - 固定使用这个类型
- 值格式：`endpoint|stash_id`
  - `endpoint` - GraphQL 端点 URL（如 `https://stashdb.org/graphql`）
  - `stash_id` - Scene 的 UUID

## 编译

### 前提条件

1. 安装 [.NET SDK](https://dotnet.microsoft.com/download) (netstandard2.1 或更高版本)
2. 安装 Visual Studio 2022 或 VS Code

### 编译步骤

```bash
cd D:\git\stash\StashtoEmby\Emby.Plugin.StashBox
dotnet build --configuration Release
```

编译成功后，DLL 文件位于：
```
bin\Release\netstandard2.1\Emby.Plugin.StashBox.dll
```

## 安装到 Emby

### 方法 1：手动安装

1. 将编译好的 `Emby.Plugin.StashBox.dll` 复制到 Emby 插件目录：
   ```
   C:\ProgramData\Emby-Server\programdata\plugins\
   ```

2. 重启 Emby 服务器

### 方法 2：使用 manifest.json

1. 将 `manifest.json` 上传到可访问的 URL
2. 在 Emby 管理界面添加插件仓库：
   ```
   管理 → 插件 → 仓库 → 添加
   URL: https://your-server/manifest.json
   ```
3. 安装 StashBox 插件

## 配置

在 Emby 管理界面：
```
管理 → 插件 → StashBox → 设置
```

可以配置默认的 Stash-Box endpoint。

## 与 AutoMoveOrganized 配合使用

确保 AutoMoveOrganized 插件写入的 NFO 格式为：
```xml
<uniqueid type="stashdb" default="true">https://stashdb.org/graphql|abc123</uniqueid>
```

AutoMoveOrganized 已自动支持此格式（修改第 351-362 行）。

## 支持的 Emby 版本

- Emby Server 4.9.x
- Emby Server 4.8.x
- Emby Server 4.7.x

## 插件原理

1. **NFO 读取**：Emby 读取 NFO 中的 `<uniqueid type="stashdb">` 字段
2. **ProviderIds 存储**：Emby 将 ID 存储到 `item.ProviderIds["stashdb"]`
3. **插件扫描**：Emby 自动扫描所有实现 `IExternalId` 接口的类
4. **Supports 检查**：插件检查是否有 `stashdb` 类型的 ID
5. **显示链接**：如果支持，Emby 在详情页显示外部链接按钮
6. **跳转**：点击后调用 `GetExternalUrl()` 获取完整 URL 并跳转

## 故障排除

### 插件不显示

1. 检查 DLL 是否在正确的插件目录
2. 检查 Emby 日志是否有加载错误
3. 确认 Emby 版本兼容

### 链接不跳转

1. 检查 NFO 格式是否正确（`endpoint|stash_id`）
2. 检查 endpoint 是否是已知的 Stash-Box 实例
3. 查看 Emby 日志

## 许可证

MIT License

## 参考

- [Jellyfin.Plugin.Stash](https://github.com/DirtyRacer1337/Jellyfin.Plugin.Stash)
- [Emby Plugin API](https://dev.emby.media/reference/pluginapi/)
- [Stash-Box Instances](https://docs.stashapp.cc/metadata-sources/stash-box-instances/)

