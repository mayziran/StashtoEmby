using System;
using MediaBrowser.Common.Plugins;
using Emby.Plugin.StashBox.Configuration;

[assembly: CLSCompliant(false)]

namespace Emby.Plugin.StashBox
{
    public class Plugin : BasePlugin
    {
        public Plugin(IApplicationHost applicationHost)
            : base(applicationHost)
        {
            Instance = this;
        }

        public static Plugin Instance { get; private set; }

        public override string Name => "StashBox";

        public override Guid Id => Guid.Parse("a1b2c3d4-e5f6-7890-abcd-ef1234567890");

        private PluginConfiguration _configuration;
        public PluginConfiguration Configuration
        {
            get
            {
                if (_configuration == null)
                {
                    _configuration = new PluginConfiguration();
                }
                return _configuration;
            }
        }
    }
}
