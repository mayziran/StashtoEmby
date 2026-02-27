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

        // 存储格式：www.example.com\path（反斜杠替代正斜杠）
        // Emby 生成 https://www.example.com\path，浏览器会将反斜杠识别为正斜杠
        public string UrlFormatString => "https://{0}";

        public bool Supports(IHasProviderIds item)
        {
            // 检查是否启用了源链接功能
            if (!Plugin.Instance?.Configuration?.EnableSourceUrl ?? false)
                return false;

            // 检查是否有 scene_source_url 类型的 ID
            var providerIds = item.ProviderIds;
            if (providerIds == null)
                return false;

            return providerIds.ContainsKey(Key);
        }
    }
}
