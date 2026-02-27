using Emby.Web.GenericEdit;

namespace Emby.Plugin.StashBox.Configuration
{
    public class PluginConfiguration : EditableOptionsBase
    {
        public PluginConfiguration()
        {
            // 默认使用 StashDB
            this.DefaultEndpoint = "https://stashdb.org/graphql";

            // 预置 5 个已知 Stash-Box 实例
            this.KnownEndpoints = "https://stashdb.org/graphql,https://theporndb.net/graphql,https://fansdb.cc/graphql,https://javstash.org/graphql,https://pmvstash.org/graphql";
        }

        public override string EditorTitle => Plugin.Instance?.Name ?? "StashBox";

        /// <summary>
        /// 默认的 Stash-Box endpoint
        /// </summary>
        public string DefaultEndpoint { get; set; }

        /// <summary>
        /// 已知的 Stash-Box endpoint 列表（逗号分隔）
        /// </summary>
        public string KnownEndpoints { get; set; }
    }
}
