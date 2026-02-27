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
    /// StashDB 外部 ID 支持
    /// </summary>
#if __EMBY__
    public class StashDBExternalId : IExternalId
#else
    public class StashDBExternalId : IExternalId
#endif
    {
#if __EMBY__
        public string Name => "StashDB";
#else
        public string ProviderName => "StashDB";
#endif

        public string Key => "stashdb";

#if __EMBY__
        public string UrlFormatString => "https://stashdb.org/{0}";
#endif

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableStashDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
