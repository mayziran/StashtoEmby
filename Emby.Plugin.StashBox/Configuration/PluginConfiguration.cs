namespace Emby.Plugin.StashBox.Configuration
{
    public class PluginConfiguration
    {
        public PluginConfiguration()
        {
            this.EnableStashDB = true;
            this.EnableThePornDB = false;
            this.EnableFansDB = true;
            this.EnableJAVStash = true;
            this.EnablePMVStash = true;
        }

        public bool EnableStashDB { get; set; }
        public bool EnableThePornDB { get; set; }
        public bool EnableFansDB { get; set; }
        public bool EnableJAVStash { get; set; }
        public bool EnablePMVStash { get; set; }
    }
}
