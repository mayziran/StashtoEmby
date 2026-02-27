using System;
using System.Collections.Generic;
using System.Linq;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    /// <summary>
    /// StashBox 外部 ID 提供者
    /// 支持多个 Stash-Box 实例：StashDB、ThePornDB、FansDB、JAVStash、PMV Stash 以及自定义实例
    /// </summary>
    public class StashBoxExternalId : IExternalId, IHasWebsite
    {
        /// <summary>
        /// 插件名称
        /// </summary>
        public string Name => Plugin.Instance.Name;

        /// <summary>
        /// 外部 ID 的 Key（与 NFO 中的 type 对应）
        /// </summary>
        public string Key => "stashdb";

        /// <summary>
        /// URL 格式字符串
        /// {0} = 网站基础 URL, {1} = stash_id
        /// </summary>
        public string UrlFormatString => "{0}/scenes/{1}";

        /// <summary>
        /// 网站地址
        /// </summary>
        public string Website => Plugin.Instance.Configuration.DefaultEndpoint?.Replace("/graphql", "") ?? "https://stashdb.org";

        /// <summary>
        /// 检查是否支持该媒体类型
        /// </summary>
        public bool Supports(IHasProviderIds item)
        {
            // 只支持电影
            if (!(item is Movie))
            {
                return false;
            }

            // 检查是否有 stashdb 类型的 ID
            return item.ProviderIds.ContainsKey(Key);
        }

        /// <summary>
        /// 获取外部 URL
        /// </summary>
        /// <param name="item">媒体项目</param>
        /// <returns>外部链接 URL</returns>
        public string GetExternalUrl(IHasProviderIds item)
        {
            if (item.ProviderIds.TryGetValue(Key, out var id))
            {
                // 解析 ID 格式：endpoint|stash_id
                var parts = id.Split('|');
                if (parts.Length == 2)
                {
                    var endpoint = parts[0];
                    var stashId = parts[1];

                    // 从 endpoint 提取网站基础 URL
                    var baseUrl = GetBaseUrlFromEndpoint(endpoint);
                    if (!string.IsNullOrEmpty(baseUrl))
                    {
                        return string.Format(UrlFormatString, baseUrl, stashId);
                    }
                }
            }
            return null;
        }

        /// <summary>
        /// 从 endpoint 提取网站基础 URL
        /// </summary>
        /// <param name="endpoint">GraphQL endpoint URL</param>
        /// <returns>网站基础 URL</returns>
        private string GetBaseUrlFromEndpoint(string endpoint)
        {
            if (string.IsNullOrEmpty(endpoint))
            {
                return Plugin.Instance.Configuration.DefaultEndpoint?.Replace("/graphql", "");
            }

            // 移除 /graphql 后缀
            var baseUrl = endpoint.Replace("/graphql", "");

            // 从配置中读取已知的 endpoint 列表
            var knownEndpoints = Plugin.Instance.Configuration.KnownEndpoints
                ?.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(e => e.Trim())
                .ToList() ?? new List<string>();

            // 验证是否是已知的 Stash-Box 实例
            foreach (var knownEndpoint in knownEndpoints)
            {
                if (knownEndpoint.StartsWith(baseUrl, StringComparison.OrdinalIgnoreCase))
                {
                    // 返回对应的网站 URL
                    return knownEndpoint.Replace("/graphql", "");
                }
            }

            // 如果不是已知实例，返回提取的 baseUrl（支持未预置的新实例）
            return baseUrl;
        }
    }
}
