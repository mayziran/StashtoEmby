using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class PMVStashExternalId : IExternalId, IHasWebsite
    {
        public string Name => "PMVStash";
        public string Key => "pmvstash";
        public string UrlFormatString => "https://pmvstash.org/{0}";
        public string Website => "https://pmvstash.org";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnablePMVStash ?? false)
                return false;
            // 支持影片、合集、演员
            return item is Movie || item is BoxSet || item is Person;
        }
    }
}
