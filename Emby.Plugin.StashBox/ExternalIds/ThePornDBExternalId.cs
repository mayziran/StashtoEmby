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
    public class ThePornDBExternalId : IExternalId
#else
    public class ThePornDBExternalId : IExternalId
#endif
    {
#if __EMBY__
        public string Name => "ThePornDB";
#else
        public string ProviderName => "ThePornDB";
#endif

        public string Key => "theporndb";

#if __EMBY__
        public string UrlFormatString => "https://theporndb.net/{0}";
#endif

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableThePornDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
