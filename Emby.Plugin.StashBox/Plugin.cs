using System;
using MediaBrowser.Common;
using MediaBrowser.Common.Plugins;
using MediaBrowser.Controller.Plugins;
using Emby.Plugin.StashBox.Configuration;

namespace Emby.Plugin.StashBox
{
    public class Plugin : BasePluginSimpleUI<PluginConfiguration>
    {
        public Plugin(IApplicationHost applicationHost)
            : base(applicationHost)
        {
            Instance = this;
        }

        public PluginConfiguration Configuration => this.GetOptions();

        public static Plugin Instance { get; private set; }

        public override string Name => "StashBox";

        public override Guid Id => Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");
    }
}
