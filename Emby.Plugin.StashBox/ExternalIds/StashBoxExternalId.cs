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

        public string UrlFormatString => null;

        public string Website => Plugin.Instance?.Configuration?.DefaultEndpoint?.Replace("/graphql", "") ?? "https://stashdb.org";

        public bool Supports(IHasProviderIds item)
        {
            return item is Movie && item.ProviderIds.ContainsKey(Key);
        }

        public string GetExternalUrl(IHasProviderIds item)
        {
            if (item.ProviderIds.TryGetValue(Key, out var id))
            {
                var parts = id.Split(new[] { ';' }, 2, StringSplitOptions.None);
                if (parts.Length == 2)
                {
                    var endpoint = parts[0];
                    var stashId = parts[1];

                    var baseUrl = GetBaseUrlFromEndpoint(endpoint);
                    if (!string.IsNullOrEmpty(baseUrl) && !string.IsNullOrEmpty(stashId))
                    {
                        return baseUrl + "/scenes/" + stashId;
                    }
                }
                else if (parts.Length == 1)
                {
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
