using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    public class FansDBExternalId : IExternalId, IHasWebsite
    {
        public string Name => "FansDB";
        public string Key => "fansdb";
        public string UrlFormatString => "https://fansdb.cc/{0}";
        public string Website => "https://fansdb.cc";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableFansDB ?? false)
                return false;
            // 支持影片、合集、演员
            return item is Movie || item is BoxSet || item is Person;
        }
    }
}
