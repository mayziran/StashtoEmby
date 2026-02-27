using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class StashSourceUrlExternalId : IExternalId
    {
        public string Name => "源链接";
        public string Key => "scene_source_url";

        // UrlFormatString 使用 {0} 占位符，Emby 会替换为存储的 ID 值（即完整 URL）
        public string UrlFormatString => "{0}";

        public bool Supports(IHasProviderIds item)
        {
            // 检查是否有 scene_source_url 类型的 ID
            var providerIds = item.ProviderIds;
            if (providerIds == null)
                return false;

            return providerIds.ContainsKey(Key);
        }
    }
}
