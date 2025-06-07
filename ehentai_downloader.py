#!/usr/bin/env python
# -*- coding: utf-8 -*-
import configparser
import os
import re
import time
from datetime import datetime
import threading
import subprocess
import zipfile
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
import uuid

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


class TaskStatus(Enum):
    """任务状态枚举"""
    WAITING = "等待中"
    RUNNING = "下载中"
    PAUSED = "已暂停"
    COMPLETED = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"


class DownloadTask:
    """下载任务类"""
    def __init__(self, task_id, url, config, progress_callback=None, status_callback=None, completion_callback=None):
        self.task_id = task_id
        self.url = url
        self.config = config
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.completion_callback = completion_callback
        
        self.status = TaskStatus.WAITING
        self.current_progress = 0
        self.total_progress = 0
        self.message = ""
        self.title = ""
        self.output_dir = ""
        self.downloader = None
        self.worker_thread = None
        self.is_paused = False
        self.is_cancelled = False
        
        # 创建线程锁
        self.lock = threading.Lock()
        
        # 回调限制
        self.last_progress_callback_time = 0
        self.last_status_callback_time = 0
    
    def start(self):
        """开始任务"""
        should_start = False
        with self.lock:
            if self.status in [TaskStatus.WAITING, TaskStatus.PAUSED]:
                self.status = TaskStatus.RUNNING
                self.is_paused = False
                self.is_cancelled = False
                should_start = True

        if should_start:
            self.worker_thread = threading.Thread(target=self._run_download, daemon=True)
            self.worker_thread.start()
            
            if self.status_callback:
                self.status_callback(self.task_id, TaskStatus.RUNNING.value, "开始下载...")
            return True
            
        return False
    
    def pause(self):
        """暂停任务"""
        should_pause = False
        with self.lock:
            if self.status == TaskStatus.RUNNING:
                self.is_paused = True
                self.status = TaskStatus.PAUSED
                if self.downloader:
                    self.downloader.pause()
                should_pause = True

        if should_pause:
            if self.status_callback:
                self.status_callback(self.task_id, TaskStatus.PAUSED.value, "任务已暂停")
            return True
        
        return False
    
    def cancel(self):
        """取消任务"""
        should_cancel = False
        with self.lock:
            if self.status in [TaskStatus.WAITING, TaskStatus.RUNNING, TaskStatus.PAUSED]:
                self.is_cancelled = True
                self.status = TaskStatus.CANCELLED
                if self.downloader:
                    self.downloader.cancel()
                should_cancel = True

        if should_cancel:
            if self.status_callback:
                self.status_callback(self.task_id, TaskStatus.CANCELLED.value, "任务已取消")
            return True
            
        return False
    
    def _run_download(self):
        """运行下载任务"""
        try:
            self.downloader = EHentaiDownloader(
                self.url, 
                self.config,
                progress_callback=self._on_progress,
                status_callback=self._on_status
            )
            
            success = self.downloader.download_gallery()
            
            with self.lock:
                if self.is_cancelled:
                    self.status = TaskStatus.CANCELLED
                elif success:
                    self.status = TaskStatus.COMPLETED
                    self.current_progress = self.total_progress
                else:
                    self.status = TaskStatus.FAILED
                
                if self.completion_callback:
                    self.completion_callback(self.task_id, self.status, success)
                    
        except Exception as e:
            logger.error(f"任务 {self.task_id} 执行失败: {e}")
            with self.lock:
                self.status = TaskStatus.FAILED
                self.message = f"下载失败: {e}"
                
                if self.completion_callback:
                    self.completion_callback(self.task_id, self.status, False)
    
    def _on_progress(self, current, total, message):
        """进度回调"""
        if self.is_cancelled or self.is_paused:
            return
            
        with self.lock:
            self.current_progress = current
            self.total_progress = total
            self.message = message
            
        # 限制回调频率，避免过于频繁的UI更新
        current_time = time.time()
        if self.progress_callback and (current_time - self.last_progress_callback_time > 0.5):
            self.progress_callback(self.task_id, current, total, message)
            self.last_progress_callback_time = current_time
    
    def _on_status(self, status):
        """状态回调"""
        if self.is_cancelled or self.is_paused:
            return
            
        with self.lock:
            self.message = status
            if "画廊标题:" in status:
                self.title = status.replace("画廊标题: ", "").strip()
            if self.downloader and self.downloader.output_dir:
                self.output_dir = self.downloader.output_dir
        
        # 限制状态回调频率
        current_time = time.time()
        if self.status_callback and (current_time - self.last_status_callback_time > 1.0):
            self.status_callback(self.task_id, self.status.value, status)
            self.last_status_callback_time = current_time


class Config:
    """配置管理类"""
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.default_config = {
            'download': {
                'output_dir': './download',
                'delay': 1.0,
                'max_workers': 3,
                'max_concurrent': 3,
                'timeout': 30,
                'retry_count': 3
            },
            'compression': {
                'enabled': False,
                'tool_path': '',  # 7zip路径
                'format': 'zip',  # zip, 7z, rar
                'compression_level': 5,  # 0-9
                'password': '',
                'delete_original': False,
                'max_parallel': 2
            },
            'conversion': {
                'webp_to_jpg': True,
                'jpg_quality': 95
            }
        }
        self.config = self.load_config()

    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                # 合并默认配置和用户配置
                return self.merge_config(self.default_config, config)
            except Exception as e:
                logger.warning(f"加载配置文件失败: {e}，使用默认配置")
        return self.default_config.copy()

    def merge_config(self, default, user):
        """合并配置"""
        result = default.copy()
        for key, value in user.items():
            if isinstance(value, dict) and key in result:
                result[key] = self.merge_config(result[key], value)
            else:
                result[key] = value
        return result

    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {self.config_file}")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")

    def get(self, section, key, default=None):
        """获取配置值"""
        return self.config.get(section, {}).get(key, default)

    def set(self, section, key, value):
        """设置配置值"""
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value


class CompressionManager:
    """压缩管理器"""
    def __init__(self, config):
        self.config = config
        self.progress_callback = None

    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self.progress_callback = callback

    def compress_directory(self, source_dir, output_path=None):
        """压缩目录"""
        if not self.config.get('compression', 'enabled'):
            return True

        tool_path = self.config.get('compression', 'tool_path')
        format_type = self.config.get('compression', 'format', 'zip')
        compression_level = self.config.get('compression', 'compression_level', 5)
        password = self.config.get('compression', 'password', '')

        if not output_path:
            output_path = f"{source_dir}.{format_type}"

        try:
            if tool_path and os.path.exists(tool_path):
                return self._compress_with_7zip(source_dir, output_path, tool_path, 
                                              format_type, compression_level, password)
            else:
                return self._compress_with_zipfile(source_dir, output_path)
        except Exception as e:
            logger.error(f"压缩失败: {e}")
            return False

    def _compress_with_7zip(self, source_dir, output_path, tool_path, 
                           format_type, compression_level, password):
        """使用7zip压缩"""
        cmd = [tool_path, 'a', f'-t{format_type}', f'-mx{compression_level}']
        
        if password:
            cmd.extend([f'-p{password}'])
        
        cmd.extend([output_path, f'{source_dir}/*'])

        logger.info(f"开始压缩: {source_dir} -> {output_path}")
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE, text=True)
        
        while True:
            output = process.poll()
            if output is not None:
                break
            if self.progress_callback:
                self.progress_callback("压缩中...")
            time.sleep(0.1)

        if process.returncode == 0:
            logger.info(f"压缩完成: {output_path}")
            
            # 如果设置了删除原文件夹
            if self.config.get('compression', 'delete_original'):
                import shutil
                shutil.rmtree(source_dir)
                logger.info(f"已删除原文件夹: {source_dir}")
            
            return True
        else:
            logger.error(f"压缩失败，返回码: {process.returncode}")
            return False

    def _compress_with_zipfile(self, source_dir, output_path):
        """使用内置zipfile压缩"""
        logger.info(f"使用内置方法压缩: {source_dir} -> {output_path}")
        
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, source_dir)
                    zipf.write(file_path, arcname)
                    
                    if self.progress_callback:
                        self.progress_callback(f"压缩中: {file}")

        logger.info(f"压缩完成: {output_path}")
        
        if self.config.get('compression', 'delete_original'):
            import shutil
            shutil.rmtree(source_dir)
            logger.info(f"已删除原文件夹: {source_dir}")
        
        return True


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


class DownloadManager:
    """下载管理器，统一管理所有下载任务"""
    def __init__(self, config=None):
        self.config = config or Config()
        self.tasks = {}  # task_id -> DownloadTask
        self.active_tasks = set()  # 正在运行的任务ID
        self.max_concurrent = self.config.get('download', 'max_concurrent', 3)
        self.lock = threading.Lock()
        
        # 回调函数
        self.task_added_callback = None
        self.task_updated_callback = None
        self.task_removed_callback = None
        
    def set_max_concurrent(self, max_concurrent):
        """设置最大并发数"""
        with self.lock:
            self.max_concurrent = max_concurrent
            self.config.set('download', 'max_concurrent', max_concurrent)
            self._start_waiting_tasks_unlocked()
    
    def set_callbacks(self, task_added=None, task_updated=None, task_removed=None):
        """设置回调函数"""
        self.task_added_callback = task_added
        self.task_updated_callback = task_updated
        self.task_removed_callback = task_removed
    
    def add_task(self, url, progress_callback=None, status_callback=None):
        """添加下载任务"""
        task_id = str(uuid.uuid4())[:8]
        
        def _progress_callback(task_id, current, total, message):
            if progress_callback:
                progress_callback(task_id, current, total, message)
            if self.task_updated_callback:
                self.task_updated_callback(task_id, current, total, message)
        
        def _status_callback(task_id, status, message):
            if status_callback:
                status_callback(task_id, status, message)
            if self.task_updated_callback:
                self.task_updated_callback(task_id, None, None, message)
        
        def _completion_callback(task_id, status, success):
            with self.lock:
                if task_id in self.active_tasks:
                    self.active_tasks.remove(task_id)
                
                # 尝试启动等待中的任务
                self._start_waiting_tasks_unlocked()
            
            if self.task_updated_callback:
                self.task_updated_callback(task_id, None, None, status.value)
        
        task = DownloadTask(
            task_id, url, self.config,
            progress_callback=_progress_callback,
            status_callback=_status_callback,
            completion_callback=_completion_callback
        )
        
        with self.lock:
            self.tasks[task_id] = task
            
        if self.task_added_callback:
            self.task_added_callback(task_id, url)
        
        # 尝试立即开始任务
        self._try_start_task(task_id)
        
        return task_id
    
    def start_task(self, task_id):
        """开始指定任务"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.WAITING and len(self.active_tasks) < self.max_concurrent:
                    if task.start():
                        self.active_tasks.add(task_id)
                        return True
                elif task.status == TaskStatus.PAUSED:
                    if task.start():
                        self.active_tasks.add(task_id)
                        return True
        return False
    
    def pause_task(self, task_id):
        """暂停指定任务"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.pause():
                    if task_id in self.active_tasks:
                        self.active_tasks.remove(task_id)
                    # 尝试启动等待中的任务
                    self._start_waiting_tasks_unlocked()
                    return True
        return False
    
    def cancel_task(self, task_id):
        """取消指定任务"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.cancel():
                    if task_id in self.active_tasks:
                        self.active_tasks.remove(task_id)
                    # 尝试启动等待中的任务
                    self._start_waiting_tasks_unlocked()
                    return True
        return False
    
    def remove_task(self, task_id):
        """删除指定任务"""
        task_to_remove = None
        should_callback = False
        removed = False

        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                # 只能删除非运行状态的任务
                if task.status not in [TaskStatus.RUNNING]:
                    task_to_remove = task
                    if task_id in self.active_tasks:
                        self.active_tasks.remove(task_id)
                    
                    del self.tasks[task_id]
                    should_callback = True
                    self._start_waiting_tasks_unlocked()
                    removed = True

        if task_to_remove:
            # Cancel the task outside the lock
            if task_to_remove.status in [TaskStatus.WAITING, TaskStatus.PAUSED]:
                task_to_remove.cancel()
            
            # Fire the callback outside the lock
            if should_callback and self.task_removed_callback:
                self.task_removed_callback(task_id)
        
        return removed
    
    def get_task_info(self, task_id):
        """获取任务信息"""
        with self.lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                return {
                    'task_id': task_id,
                    'url': task.url,
                    'status': task.status.value,
                    'progress': task.current_progress,
                    'total': task.total_progress,
                    'message': task.message,
                    'title': task.title,
                    'output_dir': task.output_dir
                }
        return None
    
    def get_all_tasks(self):
        """获取所有任务信息"""
        with self.lock:
            tasks_info = []
            for task_id, task in self.tasks.items():
                tasks_info.append({
                    'task_id': task_id,
                    'url': task.url,
                    'status': task.status.value,
                    'progress': task.current_progress,
                    'total': task.total_progress,
                    'message': task.message,
                    'title': task.title,
                    'output_dir': task.output_dir
                })
            return tasks_info
    
    def _try_start_task(self, task_id):
        """尝试启动任务"""
        with self.lock:
            self._try_start_task_unlocked(task_id)
    
    def _try_start_task_unlocked(self, task_id):
        """尝试启动任务（不加锁版本）"""
        if len(self.active_tasks) < self.max_concurrent:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task.status == TaskStatus.WAITING:
                    if task.start():
                        self.active_tasks.add(task_id)
    
    def _start_waiting_tasks(self):
        """启动等待中的任务"""
        with self.lock:
            self._start_waiting_tasks_unlocked()
    
    def _start_waiting_tasks_unlocked(self):
        """启动等待中的任务（不加锁版本）"""
        waiting_tasks = [task_id for task_id, task in self.tasks.items() 
                       if task.status == TaskStatus.WAITING]
        
        for task_id in waiting_tasks:
            if len(self.active_tasks) >= self.max_concurrent:
                break
            self._try_start_task_unlocked(task_id)
        
    def start_single_download(self, url, progress_callback=None, status_callback=None):
        """开始单个下载任务（保持向后兼容）"""
        task_id = self.add_task(url, progress_callback, status_callback)
        return self.tasks[task_id].downloader
        
    def start_batch_download(self, file_path, progress_callback=None, status_callback=None):
        """开始批量下载任务"""
        return batch_download(file_path, self.config)
        
    def resume_download(self, ini_path, delay=1):
        """从INI文件继续下载"""
        return resume_download_from_ini(ini_path, delay)
        
    def get_active_count(self):
        """获取活跃下载数量"""
        with self.lock:
            return len(self.active_tasks)
        
    def clear_finished_tasks(self):
        """清理已完成的任务"""
        with self.lock:
            finished_task_ids = [task_id for task_id, task in self.tasks.items() 
                               if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]]
            
            for task_id in finished_task_ids:
                del self.tasks[task_id]
                if self.task_removed_callback:
                    self.task_removed_callback(task_id)


class EHentaiDownloader:
    def __init__(self, gallery_url, config=None, progress_callback=None, status_callback=None):
        """
        初始化下载器
        :param gallery_url: 画廊URL
        :param config: 配置对象
        :param progress_callback: 进度回调函数 callback(current, total, message)
        :param status_callback: 状态回调函数 callback(status)
        """
        self.gallery_url = gallery_url
        self.config = config or Config()
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        
        self.output_dir = None
        self.delay = self.config.get('download', 'delay', 1)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://e-hentai.org/'
        })
        # 添加图片状态跟踪
        self.image_status = {}
        self.compression_manager = CompressionManager(self.config)
        self.compression_manager.set_progress_callback(self._on_compression_progress)
        
        # 添加控制标志
        self.is_paused = False
        self.is_cancelled = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # 初始为未暂停状态

    def pause(self):
        """暂停下载"""
        self.is_paused = True
        self.pause_event.clear()
    
    def resume(self):
        """恢复下载"""
        self.is_paused = False
        self.pause_event.set()
    
    def cancel(self):
        """取消下载"""
        self.is_cancelled = True
        self.pause_event.set()  # 确保不会卡在暂停状态

    def _check_pause_or_cancel(self):
        """检查是否需要暂停或取消"""
        if self.is_cancelled:
            raise Exception("下载已取消")
        
        if self.is_paused:
            self.pause_event.wait()  # 等待恢复信号
            
        if self.is_cancelled:
            raise Exception("下载已取消")

    def _on_compression_progress(self, message):
        """压缩进度回调"""
        if self.status_callback:
            self.status_callback(message)

    def _update_progress(self, current, total, message=""):
        """更新进度"""
        if self.progress_callback:
            self.progress_callback(current, total, message)

    def _update_status(self, status):
        """更新状态"""
        if self.status_callback:
            self.status_callback(status)

    def is_content_warning_page(self, html):
        """
        检查是否为内容警告页面
        :param html: 页面HTML内容
        :return: 如果是内容警告页面返回True，否则返回False
        """
        # 检查页面是否包含内容警告的关键词
        warning_indicators = [
            "Content Warning",
            "This gallery has been flagged as",
            "Offensive For Everyone",
            "should not be viewed by anyone"
        ]

        for indicator in warning_indicators:
            if indicator in html:
                return True
        return False

    def get_actual_gallery_url(self, html):
        """
        从内容警告页面提取实际的画廊URL
        :param html: 内容警告页面的HTML内容
        :return: 实际的画廊URL，如果提取失败返回None
        """
        soup = BeautifulSoup(html, 'html.parser')

        # 查找包含"View Gallery"文本的链接
        view_gallery_link = soup.find('a', string='View Gallery')
        if view_gallery_link and 'href' in view_gallery_link.attrs:
            return view_gallery_link['href']

        # 备用方法：通过正则表达式查找带有?nw=session的链接
        pattern = r'href="([^"]*\?nw=session[^"]*)"'
        match = re.search(pattern, html)
        if match:
            return match.group(1)

        # 如果都没找到，返回None
        return None

    def download_gallery(self):
        """
        下载整个画廊
        """
        try:
            self._check_pause_or_cancel()
            self._update_status("正在获取画廊信息...")
            # 获取画廊页面
            logger.info(f"正在获取画廊信息: {self.gallery_url}")
            gallery_html = self.session.get(self.gallery_url).text

            # 检查是否遇到内容警告页面
            if self.is_content_warning_page(gallery_html):
                self._update_status("检测到内容警告页面，正在自动跳过...")
                logger.info("检测到内容警告页面，正在自动跳过...")
                actual_gallery_url = self.get_actual_gallery_url(gallery_html)
                if actual_gallery_url:
                    logger.info(f"获取到实际画廊URL: {actual_gallery_url}")
                    gallery_html = self.session.get(actual_gallery_url).text
                    # 更新URL为实际的画廊URL
                    self.gallery_url = actual_gallery_url
                else:
                    raise Exception("无法从内容警告页面提取实际画廊URL")

            soup = BeautifulSoup(gallery_html, 'html.parser')

            # 获取画廊标题
            title = soup.title.text.split(' - E-Hentai Galleries')[0].strip()
            logger.info(f"画廊标题: {title}")
            self._update_status(f"画廊标题: {title}")

            # 设置输出目录
            base_output_dir = self.config.get('download', 'output_dir', './download')
            if not self.output_dir or self.output_dir.endswith(title):
                self.output_dir = os.path.join(base_output_dir, title)
            self.output_dir = safe_path(self.output_dir)
            os.makedirs(self.output_dir, exist_ok=True)
            logger.info(f"输出目录: {self.output_dir}")

            # 获取所有图片页面链接
            self._check_pause_or_cancel()
            self._update_status("正在获取图片链接...")
            image_page_links = self.get_all_image_pages_links(gallery_html)
            total_images = len(image_page_links)
            logger.info(f"找到 {total_images} 张图片")
            self._update_status(f"找到 {total_images} 张图片")

            # 下载所有图片
            self._update_status("开始下载图片...")
            downloaded_count = 0
            skipped_count = 0
            failed_count = 0
            failed_links = []

            # 使用线程池并行下载
            max_workers = self.config.get('download', 'max_workers', 3)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有下载任务
                future_to_info = {}
                for index, image_url in enumerate(image_page_links, 1):
                    # 检查是否已下载
                    padded_index = image_url.split("-")[-1]
                    skip_ext = ['.jpg', '.png', '.webp']

                    if any([os.path.exists(os.path.join(self.output_dir, padded_index) + ext) for ext in skip_ext]):
                        logger.info(f"图片 {index}/{total_images} 已存在，跳过下载")
                        skipped_count += 1
                        self.image_status[image_url] = "skipped"
                        self._update_progress(index, total_images, f"跳过已存在的图片 {index}/{total_images}")
                        continue

                    future = executor.submit(self._download_single_image, image_url, index, total_images)
                    future_to_info[future] = (image_url, index)

                # 处理完成的任务
                for future in as_completed(future_to_info):
                    self._check_pause_or_cancel()
                    image_url, index = future_to_info[future]
                    try:
                        result = future.result()
                        if result:
                            downloaded_count += 1
                            self.image_status[image_url] = "success"
                        else:
                            failed_count += 1
                            self.image_status[image_url] = "failed"
                            failed_links.append(image_url)
                    except Exception as e:
                        logger.error(f"下载图片 {index} 失败: {e}")
                        failed_count += 1
                        self.image_status[image_url] = f"failed: {str(e)}"
                        failed_links.append(image_url)
                    
                    current_total = downloaded_count + skipped_count + failed_count
                    self._update_progress(current_total, total_images, 
                                        f"已处理 {current_total}/{total_images} 张图片")

            logger.info(
                f"下载完成! 总计: {total_images}张, 新下载: {downloaded_count}张, 跳过: {skipped_count}张, 失败: {failed_count}张")
            logger.info(f"输出目录: {self.output_dir}")
            self._update_status(f"下载完成! 新下载: {downloaded_count}张, 跳过: {skipped_count}张, 失败: {failed_count}张")

            # 生成任务信息文件
            self.generate_task_info(title, total_images, downloaded_count, skipped_count, failed_count, failed_links)

            # 自动压缩
            if self.config.get('compression', 'enabled'):
                self._update_status("开始压缩文件...")
                if self.compression_manager.compress_directory(self.output_dir):
                    self._update_status("压缩完成!")
                else:
                    self._update_status("压缩失败!")

            return True
        except Exception as e:
            logger.error(f"下载画廊失败: {e}")
            self._update_status(f"下载失败: {e}")
            return False

    def _download_single_image(self, image_page_url, index, total):
        """下载单张图片（用于线程池）"""
        try:
            self._check_pause_or_cancel()
            self.download_image(image_page_url, index, total)
            return True
        except Exception as e:
            if "下载已取消" in str(e):
                return False
            logger.error(f"下载图片 {index} 失败: {e}")
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
                            # 正确处理URL参数
                            if '?' in self.gallery_url:
                                if '&p=' in self.gallery_url:
                                    # 如果URL中已经有p参数，替换它
                                    page_url = re.sub(r'&p=\d+', f'&p={page_num}', self.gallery_url)
                                else:
                                    # 如果URL中有其他参数但没有p参数，添加p参数
                                    page_url = f"{self.gallery_url}&p={page_num}"
                            else:
                                # 如果URL中没有任何参数，添加p参数
                                page_url = f"{self.gallery_url}?p={page_num}"

                            logger.info(f"获取第 {page_num + 1} 页的图片链接: {page_url}")

                            try:
                                page_url = page_url.replace("nw=session&", '')
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
        logger.info(f"去重前共找到 {len(image_page_links)} 张图片链接")
        image_page_links = list(dict.fromkeys(image_page_links))
        logger.info(f"去重后共找到 {len(image_page_links)} 张图片链接")

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
        timeout = self.config.get('download', 'timeout', 30)
        response = self.session.get(image_page_url, timeout=timeout)
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
        max_retries = self.config.get('download', 'retry_count', 3)
        retry_count = 0
        while retry_count <= max_retries:
            try:
                response = self.session.get(original_image_link, stream=True, timeout=timeout)
                response.raise_for_status()

                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(f"图片 {index}/{total} 下载完成: {output_path}")

                # 如果是webp格式且配置了转换，转换为jpg
                if (extension == '.webp' and 
                    self.config.get('conversion', 'webp_to_jpg', True)):
                    quality = self.config.get('conversion', 'jpg_quality', 95)
                    if webp_to_jpg(output_path, None, quality):
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


def batch_download(file_path, config=None):
    """
    从文件中读取多个画廊URL并依次下载

    :param file_path: 包含画廊URL的文件路径，每行一个URL
    :param config: 配置对象
    """
    if not config:
        config = Config()
    
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
                downloader = EHentaiDownloader(url, config)
                downloader.download_gallery()
                logger.info(f"第 {i}/{len(urls)} 个画廊下载完成")
            except Exception as e:
                logger.error(f"下载第 {i}/{len(urls)} 个画廊时出错: {e}")

            # 在画廊之间添加额外延迟，避免请求过快
            if i < len(urls):
                wait_time = config.get('download', 'delay', 1) * 3
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

        config = Config()
        if args.output:
            config.set('download', 'output_dir', args.output)
        config.set('download', 'delay', args.delay)

        if args.ini:
            # 从INI文件继续下载失败项
            resume_download_from_ini(args.ini, args.delay)
        elif args.file:
            # 从文件读取多个URL并下载
            batch_download(args.file, config)
        elif args.url:
            # 下载单个URL
            downloader = EHentaiDownloader(args.url, config)
            downloader.download_gallery()
        else:
            parser.print_help()
    else:
        # 交互模式
        mode = input("选择模式 (1: 单个画廊下载, 2: 批量下载, 3: 从INI文件继续下载, 4: GUI模式): ")
        if mode == "1":
            url = input("请输入画廊URL: ").replace('"', '')
            config = Config()
            downloader = EHentaiDownloader(url, config)
            downloader.download_gallery()
        elif mode == "2":
            file_path = input("请输入包含画廊URL的文件路径: ").replace('"', '')
            config = Config()
            batch_download(file_path, config)
        elif mode == "3":
            ini_path = input("请输入任务信息INI文件路径: ").replace('"', '')
            delay = 1
            resume_download_from_ini(ini_path, delay)
        elif mode == "4":
            # 启动GUI
            from ehentai_downloader_gui import main as gui_main
            gui_main()
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

        # 创建配置和下载器
        config = Config()
        config.set('download', 'delay', delay)
        downloader = EHentaiDownloader(gallery_url, config)
        downloader.output_dir = output_dir

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
