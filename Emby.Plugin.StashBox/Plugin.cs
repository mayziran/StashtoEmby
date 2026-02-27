using System;
using System.Collections.Generic;
using MediaBrowser.Common;
using MediaBrowser.Common.Net;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Controller.Plugins;
using MediaBrowser.Model.Logging;
using MediaBrowser.Model.Plugins;
using Emby.Plugin.StashBox.Configuration;

[assembly: CLSCompliant(false)]

namespace Emby.Plugin.StashBox
{
    public class Plugin : BasePluginSimpleUI<PluginConfiguration>
    {
        public Plugin(IApplicationHost applicationHost, IHttpClient http, ILogManager logger)
            : base(applicationHost)
        {
            Instance = this;
            Http = http;

            if (logger != null)
            {
                Log = logger.GetLogger(this.Name);
            }
        }

        public static IHttpClient Http { get; set; }

        public static ILogger Log { get; set; }

        public static Plugin Instance { get; private set; }

        public override string Name => "StashBox";

        public override Guid Id => Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");

        public PluginConfiguration Configuration => this.GetOptions();

        public IEnumerable<PluginPageInfo> GetPages()
            => new[]
            {
                new PluginPageInfo
                {
                    Name = this.Name,
                    EmbeddedResourcePath = $"{this.GetType().Namespace}.Configuration.configPage.html",
                },
            };
    }
}
