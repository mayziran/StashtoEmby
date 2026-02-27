using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;

namespace Emby.Plugin.StashBox.ExternalIds
{
    /// <summary>
    /// PMVStash 外部 ID 支持
    /// </summary>
    public class PMVStashExternalId : IExternalId
    {
        public string Name => "PMVStash";

        public string Key => "pmvstash";

        public string UrlFormatString => "https://pmvstash.org/scenes/{0}";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnablePMVStash ?? false)
                return false;
            return item is Movie;
        }
    }
}
