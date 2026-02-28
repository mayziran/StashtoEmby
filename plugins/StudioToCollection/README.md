# StudioToCollection 插件

将 Stash 工作室元数据同步到 Emby 合集（BoxSet）。

## 功能

- ✅ 同步简介（Overview）
- ✅ 同步图片（海报 + 徽标）
- ✅ 同步评分（CommunityRating）
- ✅ 同步外部 ID（ProviderIds.Stash + ProviderIds.StashDB）
- ✅ 同步别名和网址到简介
- ✅ 支持 Hook 自动响应（Studio.Update.Post / Studio.Create.Post）
- ✅ 支持 Task 批量同步

## 配合说明

⚠️ **本插件与 Jellyfin.Plugin.Stash 的合集整理功能配合使用**

- **Jellyfin.Plugin.Stash**（Emby 插件）：负责创建合集、整理影片到合集
- **StudioToCollection**（Stash 插件）：负责同步工作室元数据到已有合集
- 两者互补，不冲突

## 字段映射

| Stash | Emby | 说明 |
|-------|------|------|
| `id` | `ProviderIds.Stash` | 外部 ID |
| `details` | `Overview` | 简介 |
| `image_path` | `Images.Primary` | 海报（主图） |
| `image_path` | `Images.Logo` | 徽标（Logo） |
| `rating100` | `CommunityRating` | 评分 (÷10) |
| `stash_ids` | `ProviderIds.StashDB` | 外部数据库 ID |
| `aliases` | `Overview` | 别名（写入简介） |
| `urls` | `Overview` + `ExternalId.scene_source_url` | 所有链接写入简介，第一个链接额外写入原链接 |

### Overview 写入格式

```
别名：Studio A / Studio Alpha
这是工作室的简介内容...

相关链接:
https://example.com
https://twitter.com/studio
```

### 原链接写入

- 第一个 URL 写入 `ExternalId.scene_source_url`
- 反斜杠格式（`https:\moodyz.com`）
- Emby.Plugin.StashBox 显示按钮：🔗 源链接

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 启用 Hook 响应 | 启用后自动响应工作室创建/更新事件（建议先手动测试后再启用） | false |
| Emby 服务器地址 | Emby 服务器的完整地址 | `http://localhost:8096` |
| Emby API 密钥 | 在 Emby 控制台生成的 API 密钥 | - |
| 仅模拟 | 不真正写入 Emby，只输出日志 | false |
| 异步 Worker 延迟时间 | 格式：等待 Stash 创建影片时间，等待 Emby 扫描时间（秒），例如：35,70 | `35,70` |
| Emby 计划任务 ID（可选） | Create Hook 时触发的 Emby 计划任务 ID（如 Jellyfin.Plugin.Stash 的刷新任务），不填则不触发 | - |
| 启用异步 Worker 日志 | 是否将 Create Hook 触发的异步同步脚本日志写入到 studio_sync_worker.log 文件 | true |

## 使用方法

### 1. 安装插件

将 `StudioToCollection` 文件夹放到 Stash 插件目录，或在 Stash 中从插件源安装。

### 2. 配置插件

1. 在 Stash 中进入 **设置 → 插件 → StudioToCollection**
2. 填写配置：
   - Emby 服务器地址
   - Emby API 密钥
   - 启用 Hook 响应
   - 仅模拟（测试用）

### 3. 测试

1. 启用"仅模拟"模式
2. 更新一个工作室
3. 查看日志确认配置正确
4. 关闭"仅模拟"模式

### 4. 自动运行

配置完成后，当你在 Stash 中更新或创建工作室时，会自动同步元数据到 Emby 合集。

**Create Hook 工作流程**:
1. 等待 35 秒（等待 Stash 创建影片）
2. 触发 Emby 媒体库刷新
3. 等待 70 秒（等待 Emby 扫描完成）
4. 触发 Emby 计划任务（如果配置了）
5. 等待 30 秒
6. 搜索合集，找到就上传
7. 未找到则重试（最多 3 次）

### 5. 手动批量同步

在 Stash 中进入 **任务 → 同步所有工作室**，手动执行批量同步。

## 文件结构

```
StudioToCollection/
├── StudioToCollection.yml    # 插件配置
├── StudioToCollection.py     # 主入口
├── hook_handler.py           # Hook 处理器
├── task_handler.py           # Task 处理器
├── emby_uploader.py          # Emby 上传模块
├── studio_sync_worker.py     # 异步 Worker 脚本
├── utils.py                  # 工具函数
├── README.md                 # 使用说明
└── requirements.txt          # Python 依赖
```

## 运行模式

### Hook 模式（自动）

- **Studio.Create.Post**: 工作室创建时，异步延迟同步
  - 延迟时间可配置（默认 35 秒 + 70 秒）
  - 触发 Emby 媒体库刷新
  - 触发 Emby 计划任务（如果配置了）
  - 最多重试 3 次搜索合集
- **Studio.Update.Post**: 工作室更新时，同步立即同步
  - 不延迟，直接上传

### Task 模式（手动）

- **同步所有工作室**: 批量同步所有工作室到 Emby 合集
- 适用于初次部署或批量修复

## 匹配策略

- **只使用名称精确匹配**（不区分大小写）
- 不使用 ProviderIds 匹配（Jellyfin.Plugin.Stash 创建的合集没有 ProviderIds）
- 差一丝一毫都不行（例如 "Moodyz" 不匹配 "Moodyz Studio"）

## 与相关插件配合

### Jellyfin.Plugin.Stash (Emby 插件)

- 功能：Stash 元数据刮削、合集创建
- 使用字段：`ProviderIds.Stash`
- GitHub: https://github.com/DirtyRacer1337/Jellyfin.Plugin.Stash

### Emby.Plugin.StashBox (Emby 插件)

- 功能：外部 ID 链接跳转
- 使用字段：`ExternalId.stashdb`、`ExternalId.scene_source_url`
- 支持：StashDB、ThePornDB、FansDB、JAVStash、PMVStash

## 注意事项

1. **名称匹配**: 插件通过名称精确匹配 Emby 合集（不区分大小写）
2. **评分转换**: Stash 的 `rating100` (0-100) 会转换为 Emby 的 `CommunityRating` (0-10)
3. **图片上传**: 同一张工作室图片会上传两次（海报 Primary + 徽标 Logo）
4. **Create Hook 延迟**: 工作室创建后延迟 35 秒 + 70 秒再同步（给 Stash 和 Emby 时间处理）
5. **外部 ID 格式**: StashDB IDs 以逗号分隔写入 `ProviderIds.StashDB`
6. **日志文件**: Create Hook 的异步 worker 日志写入 `studio_sync_worker.log` 文件
7. **计划任务**: 如果配置了 Emby 计划任务 ID，会在等待后触发（用于触发 Jellyfin.Plugin.Stash 刷新）

## 故障排除

### 合集未找到

1. 确保 Emby 中已有同名合集
2. 检查名称是否完全匹配（不区分大小写）
3. 检查是否已安装 Jellyfin.Plugin.Stash 并创建了合集
4. 查看 `studio_sync_worker.log` 日志文件，确认重试过程

### 图片上传失败

1. 检查 Stash 图片路径是否正确
2. 检查 Emby 服务器地址是否正确
3. 查看日志中的详细错误信息

### 外部 ID 未生效

1. 确保 Emby.Plugin.StashBox 插件已安装
2. 检查 `stash_ids` 字段是否有 StashDB 数据
3. 刷新 Emby 合集元数据

### Worker 日志文件位置

```
StashtoEmby/plugins/StudioToCollection/studio_sync_worker.log
```

如果 Create Hook 后合集未同步，查看此日志文件了解详细过程。

### 如何获取 Emby 计划任务 ID

1. 访问 Emby 管理后台
2. 进入 **仪表板 → 计划任务**
3. 打开浏览器开发者工具（F12）
4. 查看网络请求，找到 `ScheduledTasks` 的响应
5. 复制想要触发的任务 ID（如 Jellyfin.Plugin.Stash 的刷新任务）

## 版本历史

- **1.0.0** - 初始版本
  - 同步工作室元数据到 Emby 合集
  - 支持简介、图片、评分、外部 ID
  - 支持别名和网址写入简介
  - 支持 Hook 自动响应（Create 异步/Update 同步）
  - 支持 Task 批量同步
