#!/usr/bin/env python
# -*- coding: utf-8 -*-
import configparser
import os
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import argparse
from urllib.parse import urlparse
from loguru import logger
import os
from pathlib import Path
from PIL import Image
import os

_PARSER = False


def webp_to_jpg(input_path, output_path=None, quality=95):
    """
    将WebP图像转换为JPG格式

    参数:
        input_path (str): 输入的WebP文件路径
        output_path (str): 输出的JPG文件路径(可选)
        quality (int): 输出JPG的质量(1-100)
    """
    if output_path is None:
        output_path = os.path.splitext(input_path)[0] + '.jpg'

    try:
        img = Image.open(input_path)
        img.convert('RGB').save(output_path, 'JPEG', quality=quality)
        logger.info(f"转换成功: {input_path} -> {output_path}")
        return True
    except Exception as e:
        logger.warning(f"转换失败: {e}")
        return False


def sanitize_path_component(component: str) -> str:
    # 替换所有非法字符为下划线
    illegal_chars = r'<>:"/\\|?*'
    sanitized = ''.join('_' if c in illegal_chars else c for c in component)

    # 去除首尾空格和点（Windows不允许）
    sanitized = sanitized.strip().rstrip('.')

    return sanitized


def safe_path(original_path: str) -> str:
    # 使用 pathlib 解析路径
    path_obj = Path(original_path)

    # 处理驱动器（如 C:）
    drive = f"{path_obj.drive}\\"
    parts = list(path_obj.parts[1:] if drive else path_obj.parts)

    # 清理每个路径部分
    sanitized_parts = [drive] if drive else []
    for part in parts:
        sanitized_part = sanitize_path_component(part)
        sanitized_parts.append(sanitized_part)

    # 重新组合路径
    return os.path.join(*sanitized_parts)


class EHentaiDownloader:
    def __init__(self, gallery_url, output_dir=None, delay=1):
        """
        初始化下载器
        :param gallery_url: 画廊URL
        :param output_dir: 输出目录，默认为当前目录下的画廊标题
        :param delay: 请求间隔时间（秒）
        """
        self.gallery_url = gallery_url
        self.output_dir = output_dir
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://e-hentai.org/'
        })
        # 添加图片状态跟踪
        self.image_status = {}

    def download_gallery(self):
        """
        下载整个画廊
        """
        try:
            # 获取画廊页面
            logger.info(f"正在获取画廊信息: {self.gallery_url}")
            gallery_html = self.session.get(self.gallery_url).text
            soup = BeautifulSoup(gallery_html, 'html.parser')

            # 获取画廊标题
            title = soup.title.text.split(' - E-Hentai Galleries')[0].strip()
            logger.info(f"画廊标题: {title}")

            # 设置输出目录
            if not self.output_dir or self.output_dir.endswith(title):
                self.output_dir = os.path.join(os.getcwd(), 'download', title)
            self.output_dir = safe_path(self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)
            logger.info(f"输出目录: {self.output_dir}")

            # 获取所有图片页面链接
            image_page_links = self.get_all_image_pages_links(gallery_html)
            total_images = len(image_page_links)
            logger.info(f"找到 {total_images} 张图片")

            # 下载所有图片
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            failed_links = []

            for index, image_url in enumerate(image_page_links, 1):
                try:
                    # 检查是否已下载
                    padded_index = image_url.split("-")[-1]
                    skip_ext = ['.jpg', '.png', '.webp']

                    if any([os.path.exists(os.path.join(self.output_dir, padded_index) + ext) for ext in skip_ext]):
                        logger.info(f"图片 {index}/{total_images} 已存在，跳过下载")
                        skipped_count += 1
                        self.image_status[image_url] = "skipped"
                        continue

                    self.download_image(image_url, index, total_images)
                    downloaded_count += 1
                    self.image_status[image_url] = "success"
                    time.sleep(self.delay)  # 添加延迟，避免请求过快
                except Exception as e:
                    logger.error(f"下载图片 {index} 失败: {e}")
                    failed_count += 1
                    self.image_status[image_url] = f"failed: {str(e)}"
                    failed_links.append(image_url)

            logger.info(
                f"下载完成! 总计: {total_images}张, 新下载: {downloaded_count}张, 跳过: {skipped_count}张, 失败: {failed_count}张")
            logger.info(f"输出目录: {self.output_dir}")

            # 生成任务信息文件
            self.generate_task_info(title, total_images, downloaded_count, skipped_count, failed_count, failed_links)

            return True
        except Exception as e:
            logger.error(f"下载画廊失败: {e}")
            return False

    def generate_task_info(self, title, total, downloaded, skipped, failed, failed_links):
        """
        生成任务信息INI文件
        """
        config = configparser.ConfigParser()

        # 基本信息部分
        config['Gallery'] = {
            'Title': title,
            'URL': self.gallery_url,
            'DownloadTime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'TotalImages': str(total),
            'Downloaded': str(downloaded),
            'Skipped': str(skipped),
            'Failed': str(failed)
        }

        # 失败的链接
        if failed_links:
            config['FailedLinks'] = {}
            for i, link in enumerate(failed_links, 1):
                config['FailedLinks'][f'Link{i}'] = link

        # 所有图片的状态
        config['ImageStatus'] = {}
        for url, status in self.image_status.items():
            # 使用图片索引作为键
            img_index = url.split("-")[-1]
            config['ImageStatus'][img_index] = f"{url} | {status}"

        # 写入INI文件
        ini_path = os.path.join(self.output_dir, 'task_info.ini')
        with open(ini_path, 'w', encoding='utf-8') as f:
            config.write(f)

        logger.info(f"任务信息已保存到: {ini_path}")

    def get_all_image_page_links(self, gallery_html):
        """
        从画廊HTML中提取所有图片页面链接
        """
        # 查找所有图片链接
        # 在E-Hentai中，图片链接通常在gdtm或gdtl类的div中
        """
        <a href="https://e-hentai.org/s/338bdf29b4/1435885-27"><div style="width:100px;height:145px;background:transparent url(https://zoycbewnml.hath.network/cm/3v2bqb49lyisl6z08/1435885-1.jpg) -600px 0 no-repeat" title="Page 27: 26.jpg"></div></a>
        """
        # 尝试查找所有指向图片页面的链接
        pattern = r'https://e-hentai\.org/s/[a-z0-9]+/\d+-\d+'
        image_page_links = re.findall(pattern, gallery_html)

        return image_page_links

    def get_all_image_pages_links(self, gallery_html):
        """
        从画廊HTML中提取所有图片页面链接
        """
        soup = BeautifulSoup(gallery_html, 'html.parser')
        image_page_links = []

        # 首先从第一页获取图片链接
        pattern = r'https://e-hentai\.org/s/[a-z0-9]+/\d+-\d+'
        first_page_links = re.findall(pattern, gallery_html)
        image_page_links.extend(first_page_links)

        # 检查是否有分页
        pagination = soup.find('table', class_='ptt')
        if pagination:
            # 获取所有页码链接
            page_links = pagination.find_all('a')

            # 检查是否有多页
            if len(page_links) > 1:
                # 如果有">"按钮，最后一页是倒数第二个元素
                if ">" in page_links[-1].text:
                    last_page_tag = page_links[-2]
                else:
                    last_page_tag = page_links[-1]

                if last_page_tag and 'href' in last_page_tag.attrs:
                    last_page_url = last_page_tag['href']
                    last_page_match = re.search(r'\?p=(\d+)', last_page_url)
                    if last_page_match:
                        last_page_num = int(last_page_match.group(1))
                        logger.info(f"检测到画廊共有 {last_page_num + 1} 页")

                        # 获取剩余页面的图片链接（从第2页开始，因为第1页已经处理过）
                        for page_num in range(1, last_page_num + 1):
                            page_url = f"{self.gallery_url}{'&' if '?' in self.gallery_url else '?'}p={page_num}"
                            logger.info(f"获取第 {page_num + 1} 页的图片链接: {page_url}")

                            try:
                                page_html = self.session.get(page_url).text
                                page_links = re.findall(pattern, page_html)
                                image_page_links.extend(page_links)
                                logger.info(f"第 {page_num + 1} 页找到 {len(page_links)} 张图片")
                                time.sleep(self.delay)  # 添加延迟，避免请求过快
                            except Exception as e:
                                logger.error(f"获取第 {page_num + 1} 页图片链接失败: {e}")
            else:
                logger.info("画廊只有一页")

        # 去除重复链接
        image_page_links = list(dict.fromkeys(image_page_links))
        logger.info(f"总共找到 {len(image_page_links)} 张图片链接")

        return image_page_links

    def get_image_links_from_page(self, page_html):
        """
        从单个页面HTML中提取图片链接
        """
        soup = BeautifulSoup(page_html, 'html.parser')
        links = []

        for div in soup.find_all('div', class_=lambda c: c and (c.startswith('gdtm') or c.startswith('gdtl'))):
            a_tag = div.find('a')
            if a_tag and 'href' in a_tag.attrs:
                links.append(a_tag['href'])

        if not links:
            pattern = r'https://e-hentai\.org/s/[a-z0-9]+/\d+-\d+'
            links = re.findall(pattern, page_html)

        return links

    def download_image(self, image_page_url, index, total):
        """
        从图片页面下载图片
        :param image_page_url: 图片页面URL
        :param index: 图片索引（用于命名）
        :param total: 总图片数（用于日志显示）
        """
        # 获取图片文件名前缀（用于检查是否已下载）
        padded_index = image_page_url.split("-")[-1]

        # 检查是否已经下载（检查.jpg和.webp两种格式）
        jpg_path = os.path.join(self.output_dir, f"{padded_index}.jpg")
        webp_path = os.path.join(self.output_dir, f"{padded_index}.webp")

        if os.path.exists(jpg_path) or os.path.exists(webp_path):
            logger.info(f"图片 {index}/{total} 已存在，跳过下载: {image_page_url}")
            return

        logger.info(f"下载图片 {index}/{total}: {image_page_url}")

        # 获取图片页面
        response = self.session.get(image_page_url)
        response.raise_for_status()
        image_page_html = response.text
        soup = BeautifulSoup(image_page_html, 'html.parser')

        original_image_link = None

        # 获取显示中的图片链接
        img_tag = soup.find('img', id='img')
        if img_tag and 'src' in img_tag.attrs:
            original_image_link = img_tag['src']
            logger.info(f"图片链接: {original_image_link}")

        if not original_image_link:
            raise Exception("无法找到图片链接")

        # 获取图片文件名
        filename = os.path.basename(urlparse(original_image_link).path)
        # 确保文件名有序
        extension = os.path.splitext(filename)[1] or '.jpg'  # 使用原始扩展名，如果没有则默认为.jpg
        new_filename = f"{padded_index}{extension}"
        output_path = os.path.join(self.output_dir, new_filename)

        # 下载图片，添加重试机制
        max_retries = 3
        retry_count = 0
        while retry_count <= max_retries:
            try:
                response = self.session.get(original_image_link, stream=True, timeout=30)
                response.raise_for_status()

                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(f"图片 {index}/{total} 下载完成: {output_path}")

                # 如果是webp格式，转换为jpg
                if extension == '.webp':
                    webp_to_jpg(output_path, None, 100)
                    os.remove(output_path)

                return  # 下载成功，退出函数
            except (requests.RequestException, IOError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = self.delay * (2 ** retry_count)  # 指数退避策略
                    logger.warning(
                        f"下载图片文件失败，正在重试 ({retry_count}/{max_retries})，等待 {wait_time:.1f} 秒: {e}")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"下载图片文件失败，已达到最大重试次数: {e}")


def batch_download(file_path, output_dir=None, delay=1):
    """
    从文件中读取多个画廊URL并依次下载

    :param file_path: 包含画廊URL的文件路径，每行一个URL
    :param output_dir: 输出目录的基础路径
    :param delay: 请求间隔时间（秒）
    """
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.error(f"文件不存在: {file_path}")
            return

        # 读取文件中的URL
        with open(file_path, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

        if not urls:
            logger.warning("文件中没有找到有效的URL")
            return

        logger.info(f"从文件 {file_path} 中读取到 {len(urls)} 个画廊URL")

        # 依次下载每个画廊
        for i, url in enumerate(urls, 1):
            logger.info(f"开始下载第 {i}/{len(urls)} 个画廊: {url}")
            try:
                downloader = EHentaiDownloader(url, output_dir, delay)
                downloader.download_gallery()
                logger.info(f"第 {i}/{len(urls)} 个画廊下载完成")
            except Exception as e:
                logger.error(f"下载第 {i}/{len(urls)} 个画廊时出错: {e}")

            # 在画廊之间添加额外延迟，避免请求过快
            if i < len(urls):
                wait_time = delay * 3
                logger.info(f"等待 {wait_time} 秒后继续下载下一个画廊...")
                time.sleep(wait_time)

        logger.info(f"所有画廊下载完成，共 {len(urls)} 个")
    except Exception as e:
        logger.error(f"批量下载过程中出错: {e}")


def main():
    if _PARSER:
        parser = argparse.ArgumentParser(description='E-Hentai画廊下载器')
        parser.add_argument('-u', '--url', help='画廊URL')
        parser.add_argument('-o', '--output', help='输出目录', default=None)
        parser.add_argument('-d', '--delay', type=float, default=1, help='请求间隔时间（秒）')
        parser.add_argument('-f', '--file', help='包含多个画廊URL的文件路径，每行一个URL')
        parser.add_argument('-i', '--ini', help='任务信息INI文件路径，用于继续下载失败项')
        args = parser.parse_args()

        if args.ini:
            # 从INI文件继续下载失败项
            resume_download_from_ini(args.ini, args.delay)
        elif args.file:
            # 从文件读取多个URL并下载
            batch_download(args.file, args.output, args.delay)
        elif args.url:
            # 下载单个URL
            downloader = EHentaiDownloader(args.url, args.output, args.delay)
            downloader.download_gallery()
        else:
            parser.print_help()
    else:
        # 交互模式
        mode = input("选择模式 (1: 单个画廊下载, 2: 批量下载, 3: 从INI文件继续下载): ")
        if mode == "1":
            url = input("请输入画廊URL: ").replace('"','')
            output = None
            delay = 1
            downloader = EHentaiDownloader(url, output, delay)
            downloader.download_gallery()
        elif mode == "2":
            file_path = input("请输入包含画廊URL的文件路径: ").replace('"','')
            output = None
            delay = 1
            batch_download(file_path, output, delay)
        elif mode == "3":
            ini_path = input("请输入任务信息INI文件路径: ").replace('"','')
            delay = 1
            resume_download_from_ini(ini_path, delay)
        else:
            print("无效的选择，退出程序")


def resume_download_from_ini(ini_path, delay=1):
    """
    从INI文件中读取失败的下载项并重新下载
    
    :param ini_path: 任务信息INI文件路径
    :param delay: 请求间隔时间（秒）
    """
    try:
        # 检查INI文件是否存在
        if not os.path.exists(ini_path):
            logger.error(f"INI文件不存在: {ini_path}")
            return

        logger.info(f"正在解析INI文件: {ini_path}")
        config = configparser.ConfigParser()
        config.read(ini_path, encoding='utf-8')

        # 获取画廊基本信息
        if 'Gallery' not in config:
            logger.error("INI文件格式错误: 缺少Gallery部分")
            return

        gallery_url = config['Gallery'].get('URL')
        if not gallery_url:
            logger.error("INI文件格式错误: 缺少画廊URL")
            return

        logger.info(f"从INI文件中获取到画廊URL: {gallery_url}")

        # 获取输出目录
        output_dir = os.path.dirname(ini_path)
        logger.info(f"使用INI文件所在目录作为输出目录: {output_dir}")

        # 获取失败的链接
        failed_links = []
        if 'FailedLinks' in config:
            for key in config['FailedLinks']:
                failed_links.append(config['FailedLinks'][key])

        # 获取所有图片状态
        image_status = {}
        if 'ImageStatus' in config:
            for key, value in config['ImageStatus'].items():
                parts = value.split(' | ')
                if len(parts) >= 2:
                    url = parts[0]
                    status = parts[1]
                    image_status[url] = status

        # 找出失败的和未下载的链接
        to_download = []
        for url, status in image_status.items():
            if status.startswith('failed') or status == 'pending':
                to_download.append(url)

        # 添加FailedLinks中的链接（可能有些链接在ImageStatus中没有记录）
        for url in failed_links:
            if url not in to_download:
                to_download.append(url)

        if not to_download:
            logger.info("没有找到需要重新下载的项目")
            return

        logger.info(f"找到 {len(to_download)} 个需要下载的项目")

        # 创建下载器并设置输出目录
        downloader = EHentaiDownloader(gallery_url, output_dir, delay)

        # 下载每个失败的项目
        downloaded_count = 0
        failed_count = 0
        new_failed_links = []

        for i, url in enumerate(to_download, 1):
            logger.info(f"正在下载第 {i}/{len(to_download)} 个项目: {url}")
            try:
                # 从URL中提取索引
                padded_index = url.split("-")[-1]

                # 检查是否已经下载
                jpg_path = os.path.join(output_dir, f"{padded_index}.jpg")
                webp_path = os.path.join(output_dir, f"{padded_index}.webp")

                if os.path.exists(jpg_path) or os.path.exists(webp_path):
                    logger.info(f"图片 {i}/{len(to_download)} 已存在，跳过下载")
                    continue

                # 下载图片
                downloader.download_image(url, i, len(to_download))
                downloaded_count += 1

                # 更新状态
                downloader.image_status[url] = "success"

                time.sleep(delay)  # 添加延迟，避免请求过快
            except Exception as e:
                logger.error(f"下载项目 {i} 失败: {e}")
                failed_count += 1
                downloader.image_status[url] = f"failed: {str(e)}"
                new_failed_links.append(url)

        logger.info(f"继续下载完成! 成功: {downloaded_count}张, 失败: {failed_count}张")

        # 更新INI文件
        if downloaded_count > 0 or failed_count > 0:
            # 更新Gallery部分的统计信息
            total = int(config['Gallery'].get('TotalImages', '0'))
            old_downloaded = int(config['Gallery'].get('Downloaded', '0'))
            old_failed = int(config['Gallery'].get('Failed', '0'))

            config['Gallery']['Downloaded'] = str(old_downloaded + downloaded_count)
            config['Gallery']['Failed'] = str(old_failed - downloaded_count + failed_count)
            config['Gallery']['DownloadTime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 更新FailedLinks部分
            if 'FailedLinks' in config:
                config.remove_section('FailedLinks')
            if new_failed_links:
                config['FailedLinks'] = {}
                for i, link in enumerate(new_failed_links, 1):
                    config['FailedLinks'][f'Link{i}'] = link

            # 更新ImageStatus部分
            for url, status in downloader.image_status.items():
                img_index = url.split("-")[-1]
                config['ImageStatus'][img_index] = f"{url} | {status}"

            # 写入更新后的INI文件
            with open(ini_path, 'w', encoding='utf-8') as f:
                config.write(f)

            logger.info(f"已更新任务信息文件: {ini_path}")

    except Exception as e:
        logger.error(f"从INI文件继续下载时出错: {e}")


if __name__ == '__main__':
    # 设置日志格式
    logger.add("ehentai_downloader.log", rotation="10 MB", level="INFO")

    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断下载，程序退出")
    except Exception as e:
        logger.error(f"程序执行出错: {e}")
