using System;
using System.Collections.Generic;
using System.Linq;
using MediaBrowser.Controller.Entities;
using MediaBrowser.Controller.Entities.Movies;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;

namespace Emby.Plugin.StashBox.ExternalIds
{
    /// <summary>
    /// StashBox 外部 ID 提供者（电影）
    /// </summary>
    public class StashBoxExternalId : IExternalId, IHasWebsite
    {
        /// <summary>
        /// 插件名称
        /// </summary>
        public string Name => "StashBox";

        /// <summary>
        /// 外部 ID 的 Key（与 NFO 中的 type 对应）
        /// </summary>
        public string Key => "stashdb";

        /// <summary>
        /// URL 格式字符串
        /// 由于 ID 格式为 endpoint|stash_id，无法使用简单格式字符串，此属性仅用于兼容
        /// </summary>
        public string UrlFormatString => null;

        /// <summary>
        /// 网站地址
        /// </summary>
        public string Website => Plugin.Instance?.Configuration?.DefaultEndpoint?.Replace("/graphql", "") ?? "https://stashdb.org";

        /// <summary>
        /// 检查是否支持该媒体类型
        /// </summary>
        public bool Supports(IHasProviderIds item)
        {
            // 只支持电影
            return item is Movie;
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
                Plugin.Log?.Debug($"GetExternalUrl called with id: {id}");
                
                // 解析 ID 格式：endpoint|stash_id
                var parts = id.Split(new[] { '|' }, 2);
                if (parts.Length == 2)
                {
                    var endpoint = parts[0];
                    var stashId = parts[1];

                    Plugin.Log?.Debug($"Parsed endpoint: {endpoint}, stashId: {stashId}");

                    // 从 endpoint 提取网站基础 URL
                    var baseUrl = GetBaseUrlFromEndpoint(endpoint);
                    Plugin.Log?.Debug($"Base URL: {baseUrl}");
                    
                    if (!string.IsNullOrEmpty(baseUrl) && !string.IsNullOrEmpty(stashId))
                    {
                        var url = baseUrl + "/scenes/" + stashId;
                        Plugin.Log?.Debug($"Final URL: {url}");
                        return url;
                    }
                }
                else if (parts.Length == 1)
                {
                    // 只有 stash_id，没有 endpoint（兼容旧格式）
                    var stashId = parts[0];
                    Plugin.Log?.Debug($"Legacy format, stashId: {stashId}");
                    
                    if (!string.IsNullOrEmpty(stashId))
                    {
                        var baseUrl = GetBaseUrlFromEndpoint(null);
                        return baseUrl + "/scenes/" + stashId;
                    }
                }
                else
                {
                    Plugin.Log?.Warning($"Invalid ID format: {id}");
                }
            }
            else
            {
                Plugin.Log?.Debug($"No provider id found for key: {Key}");
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
            // 获取配置（如果为空则使用默认值）
            var config = Plugin.Instance?.Configuration;
            var defaultEndpoint = config?.DefaultEndpoint ?? "https://stashdb.org/graphql";

            if (string.IsNullOrEmpty(endpoint))
            {
                return defaultEndpoint.Replace("/graphql", "");
            }

            // 移除 /graphql 后缀
            var baseUrl = endpoint.Replace("/graphql", "");

            // 从配置中读取已知的 endpoint 列表（预设 + 自定义）
            var knownEndpoints = config?.GetAllEndpoints() ?? new string[0];

            // 验证是否是已知的 Stash-Box 实例
            foreach (var knownEndpoint in knownEndpoints)
            {
                var knownBaseUrl = knownEndpoint.Replace("/graphql", "");
                if (knownBaseUrl.Equals(baseUrl, StringComparison.OrdinalIgnoreCase))
                {
                    // 返回对应的网站 URL
                    Plugin.Log?.Debug($"Known endpoint matched: {knownBaseUrl}");
                    return knownBaseUrl;
                }
            }

            // 如果不是已知实例，返回提取的 baseUrl（支持未预置的新实例）
            Plugin.Log?.Debug($"Unknown endpoint, returning extracted baseUrl: {baseUrl}");
            return baseUrl;
        }
    }
}
