using Emby.Web.GenericEdit;

namespace Emby.Plugin.StashBox.Configuration
{
    public class PluginConfiguration : EditableOptionsBase
    {
        public PluginConfiguration()
        {
            // 默认启用所有实例
            this.EnableStashDB = true;
            this.EnableThePornDB = false;  // 默认禁用，避免与官方插件冲突
            this.EnableFansDB = true;
            this.EnableJAVStash = true;
            this.EnablePMVStash = true;
        }

        public override string EditorTitle => Plugin.Instance?.Name ?? "StashBox";

        /// <summary>
        /// 是否启用 StashDB 支持
        /// </summary>
        public bool EnableStashDB { get; set; }

        /// <summary>
        /// 是否启用 ThePornDB 支持（如果已安装官方 ThePornDB 插件，请保持禁用）
        /// </summary>
        public bool EnableThePornDB { get; set; }

        /// <summary>
        /// 是否启用 FansDB 支持
        /// </summary>
        public bool EnableFansDB { get; set; }

        /// <summary>
        /// 是否启用 JAVStash 支持
        /// </summary>
        public bool EnableJAVStash { get; set; }

        /// <summary>
        /// 是否启用 PMVStash 支持
        /// </summary>
        public bool EnablePMVStash { get; set; }
    }
}
