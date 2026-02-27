using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class StashDBExternalId : IExternalId, IHasWebsite
    {
        public string Name => "StashDB";
        public string Key => "stashdb";
        public string UrlFormatString => "https://stashdb.org/{0}";
        public string Website => "https://stashdb.org";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableStashDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
