using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;

namespace Emby.Plugin.StashBox.ExternalIds
{
    /// <summary>
    /// StashDB 外部 ID 支持
    /// </summary>
    public class StashDBExternalId : IExternalId
    {
        public string Name => "StashDB";

        public string Key => "stashdb";

        public string UrlFormatString => "https://stashdb.org/{0}";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableStashDB ?? false)
                return false;
            return item is Movie;
        }
    }
}
