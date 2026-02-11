#!/bin/bash

# builds a repository of plugins for StashtoEmby
# outputs to the specified directory with the following structure:
# index.yml
# <plugin_id>.zip
# Each zip file contains the <plugin_id>.yml file and any other files in the same directory

outdir="$1"
if [ -z "$outdir" ]; then
    outdir="stable"
fi

rm -rf "$outdir"
mkdir -p "$outdir"

buildPlugin()
{
    f=$1

    # 检查文件是否包含 #pkgignore 注释
    if grep -q "^#pkgignore" "$f"; then
        plugin_id=$(basename "$f")
        plugin_id=${plugin_id%.yml}
        plugin_id=${plugin_id%.yaml}
        echo "Skipping $plugin_id due to #pkgignore"
        return
    fi

    # 获取插件 ID (文件名去除扩展名)
    dir=$(dirname "$f")
    plugin_id=$(basename "$f")
    plugin_id=${plugin_id%.yml}
    plugin_id=${plugin_id%.yaml}

    echo "Processing $plugin_id"

    # 获取 Git 信息
    # 在 GitHub Actions 中，需要 fetch-depth: 0 才能获取正确的 log
    version=$(git log -n 1 --pretty=format:%h -- "$dir"/* 2>/dev/null || echo "unknown")
    updated=$(TZ=UTC0 git log -n 1 --date="format-local:%F %T" --pretty=format:%ad -- "$dir"/* 2>/dev/null || date +"%Y-%m-%d %T")

    # 创建 zip 文件
    zipfile=$(realpath "$outdir/$plugin_id.zip")

    # 进入插件目录并打包
    pushd "$dir" > /dev/null
    zip -r "$zipfile" . > /dev/null
    popd > /dev/null

    # 提取元数据
    # 简单的 grep 提取，假定字段为单行且格式规范
    name=$(grep "^name:" "$f" | head -n 1 | cut -d' ' -f2- | sed -e 's/\r//' -e 's/^"\(.*\)"$/\1/' -e 's/^'\''\(.*\)'\''$/\1/')
    description=$(grep "^description:" "$f" | head -n 1 | cut -d' ' -f2- | sed -e 's/\r//' -e 's/^"\(.*\)"$/\1/' -e 's/^'\''\(.*\)'\''$/\1/')
    ymlVersion=$(grep "^version:" "$f" | head -n 1 | cut -d' ' -f2- | sed -e 's/\r//' -e 's/^"\(.*\)"$/\1/' -e 's/^'\''\(.*\)'\''$/\1/')
    combined_version="$ymlVersion-$version"
    dep=$(grep "^# requires:" "$f" | cut -c 12- | sed -e 's/\r//')

    # 写入索引
    echo "- id: $plugin_id
  name: $name
  metadata:
    description: $description
  version: $combined_version
  date: $updated
  path: $plugin_id.zip
  sha256: $(sha256sum "$zipfile" | cut -d' ' -f1)" >> "$outdir"/index.yml

    # 处理依赖
    if [ ! -z "$dep" ]; then
        echo "  requires:" >> "$outdir"/index.yml
        for d in ${dep//,/ }; do
            echo "    - $d" >> "$outdir"/index.yml
        done
    fi

    echo "" >> "$outdir"/index.yml
}

# 查找所有插件定义的 yml/yaml 文件
find ./plugins -mindepth 2 -maxdepth 2 \( -name "*.yml" -o -name "*.yaml" \) | while read file; do
    buildPlugin "$file"
done
