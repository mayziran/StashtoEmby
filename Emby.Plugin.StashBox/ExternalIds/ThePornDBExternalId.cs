using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;

namespace Emby.Plugin.StashBox.ExternalIds
{
    /// <summary>
    /// ThePornDB 外部 ID 支持
    /// </summary>
    public class ThePornDBExternalId : IExternalId
    {
        public string Name => "ThePornDB";

        public string Key => "theporndb";

        public string UrlFormatString => "https://theporndb.net/scenes/{0}";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableThePornDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
