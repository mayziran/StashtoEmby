using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

#if __EMBY__
#else
using MediaBrowser.Model.Providers;
#endif

namespace Emby.Plugin.StashBox.ExternalIds
{
#if __EMBY__
    public class FansDBExternalId : IExternalId
#else
    public class FansDBExternalId : IExternalId
#endif
    {
#if __EMBY__
        public string Name => "FansDB";
#else
        public string ProviderName => "FansDB";
#endif

        public string Key => "fansdb";

#if __EMBY__
        public string UrlFormatString => "https://fansdb.cc/{0}";
#endif

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableFansDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
