using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

#if __EMBY__
#else
using MediaBrowser.Model.Providers;
#endif

namespace Emby.Plugin.StashBox.ExternalIds
{
    /// <summary>
    /// JAVStash 外部 ID 支持
    /// </summary>
#if __EMBY__
    public class JAVStashExternalId : IExternalId
#else
    public class JAVStashExternalId : IExternalId
#endif
    {
#if __EMBY__
        public string Name => "JAVStash";
#else
        public string ProviderName => "JAVStash";
#endif

        public string Key => "javstash";

#if __EMBY__
        public string UrlFormatString => "https://javstash.org/{0}";
#endif

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableJAVStash ?? false)
                return false;
            return item is Movie;
        }
    }
}
