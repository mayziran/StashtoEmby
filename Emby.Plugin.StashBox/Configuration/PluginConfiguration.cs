using System;
using Emby.Web.GenericEdit;

namespace Emby.Plugin.StashBox.Configuration
{
    public class PluginConfiguration : EditableOptionsBase
    {
        // 预设的 Stash-Box 实例列表（硬编码，始终支持）
        private static readonly string[] PresetEndpoints = new[]
        {
            "https://stashdb.org/graphql",
            "https://theporndb.net/graphql",
            "https://fansdb.cc/graphql",
            "https://javstash.org/graphql",
            "https://pmvstash.org/graphql"
        };

        public PluginConfiguration()
        {
            // 默认使用 StashDB
            this.DefaultEndpoint = "https://stashdb.org/graphql";

            // 用户自定义的额外端点（逗号分隔）
            this.CustomEndpoints = string.Empty;
        }

        public override string EditorTitle => Plugin.Instance?.Name ?? "StashBox";

        /// <summary>
        /// 默认的 Stash-Box endpoint
        /// </summary>
        public string DefaultEndpoint { get; set; }

        /// <summary>
        /// 用户自定义的额外 Stash-Box endpoint 列表（逗号分隔）
        /// 预设的 5 个端点始终支持，此处仅用于添加新的端点
        /// </summary>
        public string CustomEndpoints { get; set; }

        /// <summary>
        /// 获取所有支持的端点列表（预设 + 自定义）
        /// </summary>
        public string[] GetAllEndpoints()
        {
            if (string.IsNullOrEmpty(this.CustomEndpoints))
            {
                return PresetEndpoints;
            }

            var custom = this.CustomEndpoints.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
            var all = new string[PresetEndpoints.Length + custom.Length];

            PresetEndpoints.CopyTo(all, 0);
            custom.CopyTo(all, PresetEndpoints.Length);

            return all;
        }
    }
}
