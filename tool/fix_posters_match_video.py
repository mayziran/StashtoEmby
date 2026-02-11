#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
修复已经带有 -poster 后缀但前缀与视频文件名不一致的封面图片。

规则（按目录）：
  - 仅在该目录下至少有 1 个视频文件和 1 个图片文件时处理；
  - 仅考虑文件名形如 "<something>-poster.<ext>" 的图片；
  - 如果去掉 "-poster" 前缀后的 basename 与目录中某个视频文件的 basename 不一致，
    且该目录中只有 1 个视频文件，则将图片重命名为：
        <video_basename>-poster.<原扩展名>
  - 如果目标文件已存在，则跳过并输出提示。

使用方式：
    python fix_posters_match_video.py /path/to/media/root

注意：
  - 仅根据扩展名区分图片/视频，扩展名优先从 stash_configuration.json.general 读取；
  - 建议先对少量目录试跑确认效果，再全库运行。
"""

import json
import os
import sys
from typing import List, Set, Tuple


def load_extensions(config_path: str = "stash_configuration.json") -> Tuple[Set[str], Set[str]]:
    """
    从 stash_configuration.json 中读取 imageExtensions 和 videoExtensions。
    如果失败则使用一组常见的默认扩展名。
    """
    image_exts: Set[str] = set()
    video_exts: Set[str] = set()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        general = cfg.get("general", {})
        for ext in general.get("imageExtensions", []):
            if isinstance(ext, str):
                image_exts.add(ext.lower().lstrip("."))
        for ext in general.get("videoExtensions", []):
            if isinstance(ext, str):
                video_exts.add(ext.lower().lstrip("."))
    except Exception:
        # 读取失败时使用一组常见扩展名
        image_exts = {"jpg", "jpeg", "png", "gif", "webp"}
        video_exts = {
            "m4v",
            "mp4",
            "mov",
            "wmv",
            "avi",
            "mpg",
            "mpeg",
            "rmvb",
            "rm",
            "flv",
            "asf",
            "mkv",
            "webm",
            "f4v",
        }

    return image_exts, video_exts


def split_by_ext(filenames: List[str], image_exts: Set[str], video_exts: Set[str]) -> Tuple[List[str], List[str]]:
    """
    根据扩展名把文件名分成图片列表和视频列表。
    返回：(image_files, video_files)，都是文件名（不含路径）。
    """
    images: List[str] = []
    videos: List[str] = []

    for name in filenames:
        base, ext = os.path.splitext(name)
        if not ext:
            continue
        ext_clean = ext.lstrip(".").lower()
        if ext_clean in image_exts:
            images.append(name)
        elif ext_clean in video_exts:
            videos.append(name)

    return images, videos


def fix_posters_match_video(root: str, image_exts: Set[str], video_exts: Set[str]) -> None:
    """
    遍历 root，修复形如 "<something>-poster.<ext>" 但前缀与视频 basename 不一致的图片。
    为避免误伤，仅在目录中「视频文件数量 == 1」时进行修复。
    """
    for dirpath, dirnames, filenames in os.walk(root):
        if not filenames:
            continue

        image_files, video_files = split_by_ext(filenames, image_exts, video_exts)
        if not image_files or not video_files:
            continue

        # 为安全起见，仅处理只有 1 个视频文件的目录
        if len(video_files) != 1:
            continue

        video_name = video_files[0]
        video_base, _ = os.path.splitext(video_name)

        for img_name in image_files:
            img_base, img_ext = os.path.splitext(img_name)
            if not img_ext:
                continue
            ext_clean = img_ext.lstrip(".").lower()

            # 只处理已经带有 -poster 的图片
            if not img_base.endswith("-poster"):
                continue

            img_prefix = img_base[: -len("-poster")]

            # 已经和视频 basename 匹配的不需要处理
            if img_prefix == video_base:
                continue

            src_path = os.path.join(dirpath, img_name)
            dst_name = f"{video_base}-poster.{ext_clean}"
            dst_path = os.path.join(dirpath, dst_name)

            if os.path.exists(dst_path):
                print(f"[SKIP] {src_path} -> {dst_name} (target exists)")
                continue

            try:
                os.rename(src_path, dst_path)
                print(f"[RENAME] {src_path} -> {dst_name}")
            except Exception as e:
                print(f"[ERROR] Rename failed: {src_path} -> {dst_name}: {e}")


def main() -> None:
    if len(sys.argv) != 2:
        print("用法: python fix_posters_match_video.py /path/to/media/root")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"错误：{root} 不是有效目录")
        sys.exit(1)

    image_exts, video_exts = load_extensions()
    print(f"使用的图片扩展名: {sorted(image_exts)}")
    print(f"使用的视频扩展名: {sorted(video_exts)}")
    print(f"开始修复目录: {root}")

    fix_posters_match_video(root, image_exts, video_exts)
    print("处理完成。")


if __name__ == "__main__":
    main()

