using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class ThePornDBExternalId : IExternalId, IHasWebsite
    {
        public string Name => "ThePornDB";
        public string Key => "theporndb";
        public string UrlFormatString => "https://theporndb.net/{0}";
        public string Website => "https://theporndb.net";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableThePornDB ?? false)
                return false;
            // 支持影片、合集、演员
            return item is Movie || item is BoxSet || item is Person;
        }
    }
}
