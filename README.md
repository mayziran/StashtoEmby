# 输出到兼容Emby目录的 Stash 插件

为 [Stash](https://github.com/stashapp/stash) 提供插件扩展功能，这是一个开源的媒体整理工具。

**注意**：本项目中的 AutoMoveOrganized 插件基于 [zyd16888/AutoMoveOrganized](https://github.com/zyd16888/AutoMoveOrganized) 修改而来。

## 安装方法

在 Stash 中将此仓库添加为插件源：

1. 进入 **设置 → 插件 → 可用插件**
2. 点击 **添加源**
3. 输入 URL: `https://mayziran.github.io/StashtoEmby/stable/index.yml`
4. 点击 **重新加载**
5. 在 "mayziran" 下浏览并安装可用插件

## 可用插件

### actorSyncEmby

将Stash中的演员信息（图片和NFO文件）导出到指定目录，并可选择性地将这些信息上传到Emby服务器。

**功能：**
- 同步演员基本信息到 Emby
- 自动下载并更新演员头像
- 支持批量同步操作
- 支持多种同步模式

[详细文档](https://github.com/mayziran/StashtoEmby/blob/main/plugins/actorSyncEmby/README.md)

### AutoMoveOrganized

在场景更新后，把已整理(organized)的文件移动到指定目录，并按模板重命名。

**功能：**
- 根据元数据自动移动文件
- 使用自定义模板重命名文件
- 支持批量处理
- 支持Hook模式（自动响应场景更新）和Task模式（手动批量处理）
- 生成 NFO 文件和下载封面图
- 支持AI翻译元数据

[详细文档](https://github.com/mayziran/StashtoEmby/blob/main/plugins/AutoMoveOrganized/README.md)

## 支持

- **问题反馈**: [GitHub Issues](https://github.com/mayziran/StashtoEmby/issues)
- **社区交流**: [Stash Discord](https://discord.gg/stashapp) | [Stash Discourse](https://discourse.stashapp.cc/)

