using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class FansDBExternalId : IExternalId
    {
        public string Name => "FansDB";
        public string Key => "fansdb";
        public string UrlFormatString => "https://fansdb.cc/{0}";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableFansDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
