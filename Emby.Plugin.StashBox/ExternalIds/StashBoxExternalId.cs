using System;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class StashBoxExternalId : IExternalId, IHasWebsite, IHasSupportedExternalIdentifiers
    {
        // 已知的 Stash-Box 实例映射
        private static readonly string[][] KnownEndpoints = new[]
        {
            new[] { "stashdb", "https://stashdb.org" },
            new[] { "theporndb", "https://theporndb.net" },
            new[] { "fansdb", "https://fansdb.cc" },
            new[] { "javstash", "https://javstash.org" },
            new[] { "pmvstash", "https://pmvstash.org" }
        };

        public string Name => "StashBox";

        public string Key => "stashdb";

        public string UrlFormatString => "https://stashdb.org/scenes/{0}";

        public string Website => Plugin.Instance?.Configuration?.DefaultEndpoint?.Replace("/graphql", "") ?? "https://stashdb.org";

        public bool Supports(IHasProviderIds item) => item is Movie;

        public string[] GetSupportedExternalIdentifiers()
        {
            return new[] { Key };
        }

        public string GetExternalUrl(IHasProviderIds item)
        {
            if (item.ProviderIds.TryGetValue(Key, out var id))
            {
                // ID 格式：identifier;stash_id（例如：stashdb;019bb7c5-...）
                var parts = id.Split(new[] { ';' }, 2, StringSplitOptions.None);
                if (parts.Length == 2)
                {
                    var identifier = parts[0];
                    var stashId = parts[1];

                    // 根据标识符查找对应的网站
                    var baseUrl = GetBaseUrlFromIdentifier(identifier);
                    if (!string.IsNullOrEmpty(baseUrl) && !string.IsNullOrEmpty(stashId))
                    {
                        return baseUrl + "/scenes/" + stashId;
                    }
                }
                else if (parts.Length == 1)
                {
                    // 兼容旧格式：只有 stash_id
                    var stashId = parts[0];
                    if (!string.IsNullOrEmpty(stashId))
                    {
                        var baseUrl = GetBaseUrlFromEndpoint(null);
                        return baseUrl + "/scenes/" + stashId;
                    }
                }
            }
            return null;
        }

        private string GetBaseUrlFromIdentifier(string identifier)
        {
            // 查找已知的 Stash-Box 实例
            foreach (var mapping in KnownEndpoints)
            {
                if (mapping[0].Equals(identifier, StringComparison.OrdinalIgnoreCase))
                {
                    return mapping[1];
                }
            }

            // 如果是未知标识符，尝试从配置中查找
            var config = Plugin.Instance?.Configuration;
            var customEndpoints = config?.CustomEndpoints
                ?.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);

            if (customEndpoints != null)
            {
                foreach (var endpoint in customEndpoints)
                {
                    var trimmed = endpoint.Trim();
                    if (trimmed.StartsWith("http", StringComparison.OrdinalIgnoreCase))
                    {
                        var domain = trimmed.Replace("/graphql", "")
                            .Replace("https://", "")
                            .Replace("http://", "");
                        var id = domain.Split('.')[0];
                        if (id.Equals(identifier, StringComparison.OrdinalIgnoreCase))
                        {
                            return trimmed.Replace("/graphql", "");
                        }
                    }
                }
            }

            // 未知标识符，返回默认
            return GetBaseUrlFromEndpoint(null);
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
