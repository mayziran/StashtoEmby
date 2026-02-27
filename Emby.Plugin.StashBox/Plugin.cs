using System;
using MediaBrowser.Common.Plugins;
using Emby.Plugin.StashBox.Configuration;

#if __EMBY__
using MediaBrowser.Common;
using MediaBrowser.Model.Logging;
#else
using MediaBrowser.Common.Configuration;
using MediaBrowser.Model.Serialization;
using Microsoft.Extensions.Logging;
#endif

[assembly: CLSCompliant(false)]

namespace Emby.Plugin.StashBox
{
#if __EMBY__
    public class Plugin : BasePluginSimpleUI<PluginConfiguration>
    {
        public Plugin(IApplicationHost applicationHost)
            : base(applicationHost)
        {
            Instance = this;
        }

        public PluginConfiguration Configuration => this.GetOptions();
#else
    public class Plugin : BasePlugin<PluginConfiguration>
    {
        public Plugin(IApplicationPaths applicationPaths, IXmlSerializer xmlSerializer)
            : base(applicationPaths, xmlSerializer)
        {
            Instance = this;
        }

        public PluginConfiguration Configuration => this.GetOptions();
#endif

        public static Plugin Instance { get; private set; }

        public override string Name => "StashBox";

        public override Guid Id => Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");
    }
}
