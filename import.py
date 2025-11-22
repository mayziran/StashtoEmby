import base64
import json
import os
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests


class App:
    def __init__(self):
        print('版本：2022-02-09\n'
              '用于扫描当前目录及子目录下所有 actors 文件夹中的演员图片和信息并上传到 Emby\n')
        self.emby_server = input('请输入emby服务器地址：(http://ip:8096)\n')
        self.api_key = input('请输入api密钥：\n')
        self.fail_list = []
        self.actor_name = None
        self.actor_id = None
        self.file_path = None
        self.actor_info = None

    def get_actor_name(self):
        # 获取程序当前文件夹路径
        work_dir = os.getcwd()

        # 遍历当前文件夹
        print('遍历当前文件夹')
        for parent, dirnames, filenames in os.walk(work_dir):
            for dirname in dirnames:
                if dirname == 'actors':
                    actors_root = os.path.join(parent, dirname)
                    print('搜索到文件夹:', actors_root)
                    self.process_actors_dir(actors_root)

        # 上传失败列表
        if len(self.fail_list) != 0:
            print('\n\n上传失败：\n')
            for name in self.fail_list:
                print(name)

        input('\n请按任意键退出。')

    def process_actors_dir(self, actors_root: str):
        """
        处理一个 actors 目录。
        支持两种结构：
        1) actors/演员名.jpg (+ 可选同名 nfo)
        2) actors/演员名/actor.nfo + jpg（推荐）
        """
        # 先处理子目录（推荐结构）
        for entry in os.scandir(actors_root):
            if entry.is_dir():
                self.process_actor_folder(entry.path)

        # 再兼容旧结构：actors 根目录下直接放 jpg
        for entry in os.scandir(actors_root):
            if entry.is_file() and entry.name.lower().endswith('.jpg'):
                self.process_actor_file(entry.path, actors_root)

    def process_actor_folder(self, actor_dir: str):
        """处理 actors/某个演员 目录。"""
        image_path = None
        nfo_path = None

        for entry in os.scandir(actor_dir):
            if not entry.is_file():
                continue
            name_lower = entry.name.lower()
            if name_lower.endswith('.nfo'):
                # 优先使用 actor.nfo，其次使用目录中的第一个 nfo
                if name_lower == 'actor.nfo' or nfo_path is None:
                    nfo_path = entry.path
            elif name_lower.endswith('.jpg') or name_lower.endswith('.jpeg') or name_lower.endswith('.png'):
                # 优先使用 folder.jpg / poster.jpg
                if image_path is None or name_lower in ('folder.jpg', 'poster.jpg'):
                    image_path = entry.path

        if not image_path:
            print('未找到图片，跳过目录：', actor_dir)
            return

        info = self.parse_actor_nfo(nfo_path) if nfo_path else None

        # 从 NFO 取演员名，取不到则用目录名（把下划线当作空格）
        if info and info.get('name'):
            actor_name = info['name']
        else:
            actor_name = os.path.basename(actor_dir).replace('_', ' ')

        self.process_actor(actor_name, image_path, info)

    def process_actor_file(self, image_path: str, actors_root: str):
        """兼容旧结构：actors 根目录下直接放 jpg。"""
        filename = os.path.basename(image_path)
        name_no_ext, _ = os.path.splitext(filename)

        # 尝试同名 nfo
        nfo_candidate = os.path.join(actors_root, f'{name_no_ext}.nfo')
        info = self.parse_actor_nfo(nfo_candidate) if os.path.exists(nfo_candidate) else None

        if info and info.get('name'):
            actor_name = info['name']
        else:
            # 旧逻辑里首个下划线代表空格
            actor_name = name_no_ext.replace('_', ' ')

        self.process_actor(actor_name, image_path, info)

    def parse_actor_nfo(self, nfo_path: str):
        """解析演员 NFO，返回一个包含关键信息的字典。"""
        if not nfo_path or not os.path.exists(nfo_path):
            return None

        try:
            tree = ET.parse(nfo_path)
            root = tree.getroot()
        except Exception as e:
            print('解析 NFO 失败：', nfo_path, e)
            self.fail_list.append('解析 NFO 失败 ' + nfo_path)
            return None

        def _get(tag: str):
            el = root.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            return None

        info = {
            'name': _get('name'),
            'gender': _get('gender'),
            'country': _get('country'),
            'birthdate': _get('birthdate'),
            'height_cm': _get('height_cm'),
            'measurements': _get('measurements'),
            'fake_tits': _get('fake_tits'),
            'disambiguation': _get('disambiguation'),
        }
        return info

    def process_actor(self, actor_name: str, image_path: str, info=None):
        """单个演员的整体处理：获取 ID、上传头像、更新信息。"""
        self.actor_name = actor_name
        self.file_path = image_path
        self.actor_info = info or {}

        print('处理演员：', self.actor_name)
        print('图片文件：', self.file_path)
        if self.actor_info:
            print('检测到演员 NFO，将尝试导入信息')

        try:
            self.get_actor_id()
        except Exception:
            self.fail_list.append('未找到演员 ' + self.actor_name)
            return

        try:
            self.post_actor_image()
        except Exception:
            self.fail_list.append('上传头像失败 ' + self.actor_name)

        try:
            self.update_actor_metadata()
        except Exception:
            self.fail_list.append('更新元数据失败 ' + self.actor_name)

    def get_actor_id(self):
        """根据演员名称获取 Emby 中的演员 ID。"""
        # Emby 的 Persons 接口使用 URL 中的名称，需要进行 URL 编码
        encoded_name = quote(self.actor_name)
        url = f'{self.emby_server}/emby/Persons/{encoded_name}?api_key={self.api_key}'
        r = requests.get(url)
        r.raise_for_status()
        data = json.loads(r.text)
        self.actor_id = data['Id']

    def post_actor_image(self):
        # 上传图片
        with open(self.file_path, 'rb') as f:
            # 转换图片为base64编码
            b6_pic = base64.b64encode(f.read())
        url = f'{self.emby_server}/emby/Items/{self.actor_id}/Images/Primary?api_key={self.api_key}'
        headers = {'Content-Type': 'image/jpg'}
        r = requests.post(url=url, data=b6_pic, headers=headers)
        if r.status_code == 204:
            print('上传成功')
        else:
            self.fail_list.append('上传失败 ' + self.file_path)

    def update_actor_metadata(self):
        """根据 NFO 中的信息更新 Emby 中的演员元数据。"""
        if not self.actor_info:
            return

        # 模拟 Emby Web：POST /emby/Items/{Id}
        url = f'{self.emby_server}/emby/Items/{self.actor_id}?api_key={self.api_key}'
        data = {
            'Id': self.actor_id,
            'Name': self.actor_name,
            'Type': 'Person',
        }

        # 把各字段整理成一段 Overview 文本，方便在 Emby 中查看
        lines = []
        if self.actor_info.get('disambiguation'):
            lines.append(self.actor_info['disambiguation'])
        if self.actor_info.get('gender'):
            lines.append('Gender: ' + self.actor_info['gender'])
        if self.actor_info.get('country'):
            lines.append('Country: ' + self.actor_info['country'])
        if self.actor_info.get('birthdate'):
            lines.append('Birthdate: ' + self.actor_info['birthdate'])
        if self.actor_info.get('height_cm'):
            lines.append('Height: ' + self.actor_info['height_cm'] + ' cm')
        if self.actor_info.get('measurements'):
            lines.append('Measurements: ' + self.actor_info['measurements'])
        if self.actor_info.get('fake_tits'):
            lines.append('Fake tits: ' + self.actor_info['fake_tits'])

        if lines:
            overview = '\n'.join(lines)
            data['Overview'] = overview

        # 可选：把生日的年份写入 ProductionYear，便于按年份筛选
        if self.actor_info.get('birthdate'):
            try:
                year = int(self.actor_info['birthdate'][:4])
            except Exception:
                year = None
            if year:
                data['ProductionYear'] = year

        try:
            r2 = requests.post(url, json=data)
            r2.raise_for_status()
            print('元数据更新成功')
        except Exception as e:
            print('元数据更新失败：', self.actor_name, e)
            self.fail_list.append('更新元数据失败 ' + self.actor_name)


if __name__ == '__main__':
    app = App()
    app.get_actor_name()
