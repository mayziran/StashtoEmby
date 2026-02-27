using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class ThePornDBExternalId : IExternalId
    {
        public string Name => "ThePornDB";
        public string Key => "theporndb";
        public string UrlFormatString => "https://theporndb.net/{0}";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableThePornDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
