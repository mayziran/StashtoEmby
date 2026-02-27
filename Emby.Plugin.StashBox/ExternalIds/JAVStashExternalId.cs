using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class JAVStashExternalId : IExternalId, IHasWebsite
    {
        public string Name => "JAVStash";
        public string Key => "javstash";
        public string UrlFormatString => "https://javstash.org/{0}";
        public string Website => "https://javstash.org";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableJAVStash ?? false)
                return false;
            return item is Movie;
        }
    }
}
