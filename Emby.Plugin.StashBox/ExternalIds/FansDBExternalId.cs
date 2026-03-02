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
            return item is Movie;
        }
    }

    public class FansDBPersonExternalId : IExternalId, IHasWebsite
    {
        public string Name => "FansDB";
        public string Key => "fansdb";
        public string UrlFormatString => "https://fansdb.cc/performers/{0}";
        public string Website => "https://fansdb.cc";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableFansDB ?? false)
                return false;
            return item is Person;
        }
    }

    public class FansDBBoxSetExternalId : IExternalId, IHasWebsite
    {
        public string Name => "FansDB";
        public string Key => "fansdb";
        public string UrlFormatString => "https://fansdb.cc/studios/{0}";
        public string Website => "https://fansdb.cc";

        public bool Supports(IHasProviderIds item)
        {
            if (!Plugin.Instance?.Configuration?.EnableFansDB ?? false)
                return false;
            return item is BoxSet;
        }
    }
}
