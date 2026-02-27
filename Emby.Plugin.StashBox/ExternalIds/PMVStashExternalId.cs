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
    public class PMVStashExternalId : IExternalId
#else
    public class PMVStashExternalId : IExternalId
#endif
    {
#if __EMBY__
        public string Name => "PMVStash";
#else
        public string ProviderName => "PMVStash";
#endif

        public string Key => "pmvstash";

#if __EMBY__
        public string UrlFormatString => "https://pmvstash.org/{0}";
#endif

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnablePMVStash ?? false)
                return false;
            return item is Movie;
        }
    }
}
