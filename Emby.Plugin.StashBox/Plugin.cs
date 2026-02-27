using System;
using MediaBrowser.Common;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Model.Logging;

[assembly: CLSCompliant(false)]

namespace Emby.Plugin.StashBox
{
    public class Plugin : BasePlugin
    {
        public Plugin(IApplicationHost applicationHost, ILogManager logger)
            : base(applicationHost)
        {
            Instance = this;

            if (logger != null)
            {
                Log = logger.GetLogger(this.Name);
            }
        }

        public static ILogger Log { get; private set; }

        public static Plugin Instance { get; private set; }

        public override string Name => "StashBox";

        public override Guid Id => Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");
    }
}
