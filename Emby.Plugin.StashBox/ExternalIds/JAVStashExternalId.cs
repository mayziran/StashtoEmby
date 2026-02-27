using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class JAVStashExternalId : IExternalId
    {
        public string Name => "JAVStash";
        public string Key => "javstash";
        public string UrlFormatString => "https://javstash.org/{0}";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableJAVStash ?? false)
                return false;
            return item is Movie;
        }
    }
}
