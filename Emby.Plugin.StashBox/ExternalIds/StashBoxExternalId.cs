using System;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class StashBoxExternalId : IExternalId, IHasWebsite
    {
        public string Name => "StashBox";

        public string Key => "stashdb";

        public string UrlFormatString => "{0}";

        public string Website => Plugin.Instance?.Configuration?.DefaultEndpoint?.Replace("/graphql", "") ?? "https://stashdb.org";

        public bool Supports(IHasProviderIds item)
        {
            return item is Movie && item.ProviderIds.ContainsKey(Key);
        }

        public string GetExternalUrl(IHasProviderIds item)
        {
            if (item.ProviderIds.TryGetValue(Key, out var id))
            {
                // ID 已经是完整 URL：https://xxx/scenes/xxx_id
                if (id.StartsWith("http://") || id.StartsWith("https://"))
                {
                    return id;
                }

                // 兼容旧格式：只有 stash_id，使用默认 endpoint
                var baseUrl = GetBaseUrlFromEndpoint(null);
                return baseUrl + "/scenes/" + id;
            }
            return null;
        }

        private string GetBaseUrlFromEndpoint(string endpoint)
        {
            if (string.IsNullOrEmpty(endpoint))
            {
                var config = Plugin.Instance?.Configuration;
                var defaultEndpoint = config?.DefaultEndpoint ?? "https://stashdb.org/graphql";
                return defaultEndpoint.Replace("/graphql", "");
            }

            return endpoint.Replace("/graphql", "");
        }
    }
}
