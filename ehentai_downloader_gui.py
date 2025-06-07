#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
import threading
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QGridLayout, QPushButton, QLineEdit, 
                            QTextEdit, QLabel, QProgressBar, QTabWidget, 
                            QCheckBox, QSpinBox, QComboBox, QFileDialog, 
                            QGroupBox, QTableWidget, QTableWidgetItem, 
                            QHeaderView, QMessageBox, QScrollArea,
                            QSplitter, QFrame, QStatusBar, QAbstractItemView)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt, QObject
from PyQt5.QtGui import QFont
from loguru import logger
import json

from ehentai_downloader import DownloadManager, Config, EHentaiDownloader


class TaskSignals(QObject):
    """任务信号类，用于异步GUI更新"""
    task_added = pyqtSignal(str, str)  # task_id, url
    task_updated = pyqtSignal(str, object, object, str)  # task_id, current, total, message
    task_removed = pyqtSignal(str)  # task_id


class EHentaiDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        
        # 创建信号对象
        self.signals = TaskSignals()
        self.signals.task_added.connect(self.on_task_added_async)
        self.signals.task_updated.connect(self.on_task_updated_async)
        self.signals.task_removed.connect(self.on_task_removed_async)
        
        self.download_manager = DownloadManager(self.config)
        self.download_manager.set_callbacks(
            task_added=self.on_task_added,
            task_updated=self.on_task_updated,
            task_removed=self.on_task_removed
        )
        
        # 定时器用于更新任务列表
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_task_table)
        self.update_timer.start(3000)  # 每3秒更新一次，减少频率
        
        # 添加更新标记，避免无意义的更新
        self.need_update = False
        
        # 限制更新频率
        self.last_update_time = 0
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        self.setWindowTitle('E-Hentai 下载器 v2.0')
        self.setGeometry(100, 100, 1000, 750)
        self.setMinimumSize(900, 700)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 创建选项卡内容
        self.download_tab = self.create_download_tab()
        self.tab_widget.addTab(self.download_tab, "下载")
        
        self.settings_tab = self.create_settings_tab()
        self.tab_widget.addTab(self.settings_tab, "设置")
        
        self.log_tab = self.create_log_tab()
        self.tab_widget.addTab(self.log_tab, "日志")
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
    
    def create_download_tab(self):
        """创建下载选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # URL输入区域
        url_group = QGroupBox("添加下载任务")
        url_layout = QVBoxLayout(url_group)
        
        # 单个URL输入
        single_layout = QHBoxLayout()
        single_layout.addWidget(QLabel("画廊URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("输入E-Hentai画廊URL...")
        self.url_input.returnPressed.connect(self.add_download_task)  # 支持回车键
        single_layout.addWidget(self.url_input, 1)
        
        self.add_task_btn = QPushButton("添加任务")
        self.add_task_btn.clicked.connect(self.add_download_task)
        single_layout.addWidget(self.add_task_btn)
        
        url_layout.addLayout(single_layout)
        
        # 批量下载区域
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("批量文件:"))
        self.batch_file_input = QLineEdit()
        self.batch_file_input.setPlaceholderText("选择包含URL列表的文件...")
        batch_layout.addWidget(self.batch_file_input, 1)
        
        self.browse_batch_btn = QPushButton("浏览")
        self.browse_batch_btn.clicked.connect(self.browse_batch_file)
        batch_layout.addWidget(self.browse_batch_btn)
        
        self.batch_download_btn = QPushButton("批量添加")
        self.batch_download_btn.clicked.connect(self.add_batch_tasks)
        batch_layout.addWidget(self.batch_download_btn)
        
        url_layout.addLayout(batch_layout)
        
        # INI文件续传
        ini_layout = QHBoxLayout()
        ini_layout.addWidget(QLabel("任务文件:"))
        self.ini_file_input = QLineEdit()
        self.ini_file_input.setPlaceholderText("选择task_info.ini文件...")
        ini_layout.addWidget(self.ini_file_input, 1)
        
        self.browse_ini_btn = QPushButton("浏览")
        self.browse_ini_btn.clicked.connect(self.browse_ini_file)
        ini_layout.addWidget(self.browse_ini_btn)
        
        self.resume_btn = QPushButton("继续下载")
        self.resume_btn.clicked.connect(self.resume_download)
        ini_layout.addWidget(self.resume_btn)
        
        url_layout.addLayout(ini_layout)
        
        # 并发设置
        concurrent_layout = QHBoxLayout()
        concurrent_layout.addWidget(QLabel("最大并行数:"))
        self.max_concurrent_spin = QSpinBox()
        self.max_concurrent_spin.setRange(1, 10)
        self.max_concurrent_spin.setValue(3)
        self.max_concurrent_spin.valueChanged.connect(self.on_max_concurrent_changed)
        concurrent_layout.addWidget(self.max_concurrent_spin)
        concurrent_layout.addStretch()
        url_layout.addLayout(concurrent_layout)
        
        layout.addWidget(url_group)
        
        # 任务列表区域
        tasks_group = QGroupBox("下载任务")
        tasks_layout = QVBoxLayout(tasks_group)
        
        # 任务表格
        self.tasks_table = QTableWidget()
        self.tasks_table.setColumnCount(6)
        self.tasks_table.setHorizontalHeaderLabels(['URL/标题', '状态', '进度', '消息', '操作', 'ID'])
        self.tasks_table.horizontalHeader().setStretchLastSection(False)
        
        # 设置列宽
        header = self.tasks_table.horizontalHeader()
        header.resizeSection(0, 300)  # URL/标题列
        header.resizeSection(1, 80)   # 状态列
        header.resizeSection(2, 100)  # 进度列
        header.resizeSection(3, 200)  # 消息列
        header.resizeSection(4, 180)  # 操作列
        header.resizeSection(5, 80)   # ID列
        
        # 隐藏ID列（仅用于内部标识）
        self.tasks_table.setColumnHidden(5, True)
        
        # 设置表格属性
        self.tasks_table.setAlternatingRowColors(True)
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tasks_table.verticalHeader().setVisible(False)
        
        tasks_layout.addWidget(self.tasks_table)
        
        # 任务控制按钮
        task_buttons_layout = QHBoxLayout()
        
        self.start_all_btn = QPushButton("开始全部")
        self.start_all_btn.clicked.connect(self.start_all_tasks)
        task_buttons_layout.addWidget(self.start_all_btn)
        
        self.pause_all_btn = QPushButton("暂停全部")
        self.pause_all_btn.clicked.connect(self.pause_all_tasks)
        task_buttons_layout.addWidget(self.pause_all_btn)
        
        self.clear_completed_btn = QPushButton("清除已完成")
        self.clear_completed_btn.clicked.connect(self.clear_completed_tasks)
        task_buttons_layout.addWidget(self.clear_completed_btn)
        
        self.clear_all_btn = QPushButton("清除全部")
        self.clear_all_btn.clicked.connect(self.clear_all_tasks)
        task_buttons_layout.addWidget(self.clear_all_btn)
        
        task_buttons_layout.addStretch()
        tasks_layout.addLayout(task_buttons_layout)
        
        layout.addWidget(tasks_group)
        
        return widget
    
    def create_settings_tab(self):
        """创建设置选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 使用滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(15)
        
        # 下载设置
        download_group = QGroupBox("下载设置")
        download_layout = QGridLayout(download_group)
        download_layout.setSpacing(10)
        
        # 输出目录
        download_layout.addWidget(QLabel("输出目录:"), 0, 0)
        self.output_dir_input = QLineEdit()
        download_layout.addWidget(self.output_dir_input, 0, 1)
        self.browse_output_btn = QPushButton("浏览")
        self.browse_output_btn.clicked.connect(self.browse_output_dir)
        download_layout.addWidget(self.browse_output_btn, 0, 2)
        
        # 其他设置
        download_layout.addWidget(QLabel("请求延迟(秒):"), 1, 0)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(1, 10)
        self.delay_spin.setValue(1)
        download_layout.addWidget(self.delay_spin, 1, 1)
        
        download_layout.addWidget(QLabel("并行下载数:"), 2, 0)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 10)
        self.workers_spin.setValue(3)
        download_layout.addWidget(self.workers_spin, 2, 1)
        
        download_layout.addWidget(QLabel("超时时间(秒):"), 3, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 120)
        self.timeout_spin.setValue(30)
        download_layout.addWidget(self.timeout_spin, 3, 1)
        
        download_layout.addWidget(QLabel("重试次数:"), 4, 0)
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(1, 10)
        self.retry_spin.setValue(3)
        download_layout.addWidget(self.retry_spin, 4, 1)
        
        scroll_layout.addWidget(download_group)
        
        # 压缩设置
        compression_group = QGroupBox("压缩设置")
        compression_layout = QGridLayout(compression_group)
        compression_layout.setSpacing(10)
        
        self.compression_enabled = QCheckBox("启用自动压缩")
        compression_layout.addWidget(self.compression_enabled, 0, 0, 1, 3)
        
        compression_layout.addWidget(QLabel("7-Zip路径:"), 1, 0)
        self.zip_path_input = QLineEdit()
        compression_layout.addWidget(self.zip_path_input, 1, 1)
        self.browse_zip_btn = QPushButton("浏览")
        self.browse_zip_btn.clicked.connect(self.browse_zip_path)
        compression_layout.addWidget(self.browse_zip_btn, 1, 2)
        
        compression_layout.addWidget(QLabel("压缩格式:"), 2, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(['zip', '7z', 'rar'])
        compression_layout.addWidget(self.format_combo, 2, 1)
        
        compression_layout.addWidget(QLabel("压缩级别:"), 3, 0)
        self.compression_level_spin = QSpinBox()
        self.compression_level_spin.setRange(0, 9)
        self.compression_level_spin.setValue(5)
        compression_layout.addWidget(self.compression_level_spin, 3, 1)
        
        compression_layout.addWidget(QLabel("压缩密码:"), 4, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        compression_layout.addWidget(self.password_input, 4, 1)
        
        self.delete_original = QCheckBox("压缩后删除原文件夹")
        compression_layout.addWidget(self.delete_original, 5, 0, 1, 3)
        
        scroll_layout.addWidget(compression_group)
        
        # 转换设置
        conversion_group = QGroupBox("图片转换")
        conversion_layout = QGridLayout(conversion_group)
        conversion_layout.setSpacing(10)
        
        self.webp_to_jpg = QCheckBox("自动将WebP转换为JPG")
        conversion_layout.addWidget(self.webp_to_jpg, 0, 0, 1, 3)
        
        conversion_layout.addWidget(QLabel("JPG质量:"), 1, 0)
        self.jpg_quality_spin = QSpinBox()
        self.jpg_quality_spin.setRange(1, 100)
        self.jpg_quality_spin.setValue(95)
        conversion_layout.addWidget(self.jpg_quality_spin, 1, 1)
        
        scroll_layout.addWidget(conversion_group)
        
        # 按钮区域
        buttons_layout = QHBoxLayout()
        self.save_settings_btn = QPushButton("保存设置")
        self.save_settings_btn.clicked.connect(self.save_settings)
        buttons_layout.addWidget(self.save_settings_btn)
        
        self.reset_settings_btn = QPushButton("重置设置")
        self.reset_settings_btn.clicked.connect(self.reset_settings)
        buttons_layout.addWidget(self.reset_settings_btn)
        
        buttons_layout.addStretch()
        scroll_layout.addLayout(buttons_layout)
        
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)
        
        return widget
    
    def create_log_tab(self):
        """创建日志选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 日志区域
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        
        # 日志控制按钮
        log_buttons_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("清除日志")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_buttons_layout.addWidget(self.clear_log_btn)
        
        self.save_log_btn = QPushButton("保存日志")
        self.save_log_btn.clicked.connect(self.save_log)
        log_buttons_layout.addWidget(self.save_log_btn)
        
        log_buttons_layout.addStretch()
        log_layout.addLayout(log_buttons_layout)
        
        layout.addWidget(log_group)
        return widget

    # 任务管理方法
    def add_download_task(self):
        """添加下载任务"""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "警告", "请输入画廊URL!")
            return
        
        self.update_config_from_ui()
        task_id = self.download_manager.add_task(url)
        self.url_input.clear()
        # 日志记录将在异步回调中处理
    
    def add_batch_tasks(self):
        """批量添加下载任务"""
        file_path = self.batch_file_input.text().strip()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "警告", "请选择有效的URL列表文件!")
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
            
            if not urls:
                QMessageBox.warning(self, "警告", "文件中没有找到有效的URL!")
                return
            
            self.update_config_from_ui()
            added_count = 0
            for url in urls:
                try:
                    self.download_manager.add_task(url)
                    added_count += 1
                except Exception as e:
                    logger.error(f"添加任务失败: {url} - {e}")
            
            self.log_message(f"批量添加完成，成功添加 {added_count} 个任务")
            QMessageBox.information(self, "完成", f"已添加 {added_count} 个下载任务!")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"批量添加失败: {e}")
    
    def on_max_concurrent_changed(self):
        """最大并行数改变"""
        max_concurrent = self.max_concurrent_spin.value()
        self.download_manager.set_max_concurrent(max_concurrent)
        self.log_message(f"最大并行数已设置为: {max_concurrent}")
    
    def on_task_added(self, task_id, url):
        """任务添加回调（异步触发信号）"""
        self.signals.task_added.emit(task_id, url)
    
    def on_task_updated(self, task_id, current, total, message):
        """任务更新回调（异步触发信号）"""
        self.signals.task_updated.emit(task_id, current, total, message)
    
    def on_task_removed(self, task_id):
        """任务移除回调（异步触发信号）"""
        self.signals.task_removed.emit(task_id)
    
    def on_task_added_async(self, task_id, url):
        """任务添加回调（在主线程中执行）"""
        self.log_message(f"已添加下载任务: {url} (ID: {task_id})")
        self.need_update = True
        # 立即更新一次，因为这是重要的状态变化
        self.update_task_table()
    
    def on_task_updated_async(self, task_id, current, total, message):
        """任务更新回调（在主线程中执行）"""
        # 限制更新频率，避免过于频繁的更新
        current_time = time.time()
        if current_time - self.last_update_time > 1.0:  # 最多每秒更新一次
            self.need_update = True
            self.last_update_time = current_time
    
    def on_task_removed_async(self, task_id):
        """任务移除回调（在主线程中执行）"""
        self.log_message(f"任务已移除: {task_id}")
        self.need_update = True
        # 立即更新一次，因为这是重要的状态变化
        self.update_task_table()
    
    def update_task_table(self):
        """更新任务表格（优化版本，增量更新）"""
        # 如果不需要更新，直接返回
        if not self.need_update:
            return
            
        try:
            self.need_update = False
            tasks = self.download_manager.get_all_tasks()
            
            # 获取当前表格中的任务ID
            current_task_ids = set()
            for row in range(self.tasks_table.rowCount()):
                task_id_item = self.tasks_table.item(row, 5)
                if task_id_item:
                    current_task_ids.add(task_id_item.text())
            
            # 获取新的任务ID
            new_task_ids = {task.get('task_id') for task in tasks if task}
            
            # 删除不存在的任务行
            rows_to_remove = []
            for row in range(self.tasks_table.rowCount()):
                task_id_item = self.tasks_table.item(row, 5)
                if task_id_item and task_id_item.text() not in new_task_ids:
                    rows_to_remove.append(row)
            
            # 从后往前删除行，避免索引变化
            for row in reversed(rows_to_remove):
                self.tasks_table.removeRow(row)
            
            # 更新或添加任务
            for task in tasks:
                if task is None:
                    continue
                
                task_id = task.get('task_id')
                
                # 查找现有行
                existing_row = -1
                for row in range(self.tasks_table.rowCount()):
                    task_id_item = self.tasks_table.item(row, 5)
                    if task_id_item and task_id_item.text() == task_id:
                        existing_row = row
                        break
                
                if existing_row == -1:
                    # 添加新行
                    row = self.tasks_table.rowCount()
                    self.tasks_table.insertRow(row)
                    self._create_task_row(row, task)
                else:
                    # 更新现有行
                    self._update_task_row(existing_row, task)
                    
        except Exception as e:
            logger.error(f"更新任务表格失败: {e}")
    
    def _create_task_row(self, row, task):
        """创建新的任务行"""
        task_id = task.get('task_id')
        
        # URL/标题列
        title_text = task.get('title', '') or task.get('url', '')[:50] + "..."
        self.tasks_table.setItem(row, 0, QTableWidgetItem(title_text))
        
        # 状态列
        self.tasks_table.setItem(row, 1, QTableWidgetItem(task.get('status', '')))
        
        # 进度列
        progress = task.get('progress', 0)
        total = task.get('total', 0)
        if total > 0:
            progress_text = f"{progress}/{total} ({progress*100//total}%)"
        else:
            progress_text = "0/0 (0%)"
        self.tasks_table.setItem(row, 2, QTableWidgetItem(progress_text))
        
        # 消息列
        message = task.get('message', '')[:50]
        self.tasks_table.setItem(row, 3, QTableWidgetItem(message))
        
        # 操作列 - 创建按钮组
        self._create_task_buttons(row, task)
        
        # ID列（隐藏）
        self.tasks_table.setItem(row, 5, QTableWidgetItem(task_id))
    
    def _update_task_row(self, row, task):
        """更新现有任务行"""
        # URL/标题列
        title_text = task.get('title', '') or task.get('url', '')[:50] + "..."
        title_item = self.tasks_table.item(row, 0)
        if title_item and title_item.text() != title_text:
            title_item.setText(title_text)
        elif not title_item:
            self.tasks_table.setItem(row, 0, QTableWidgetItem(title_text))
        
        # 状态列
        status = task.get('status', '')
        status_item = self.tasks_table.item(row, 1)
        if status_item and status_item.text() != status:
            status_item.setText(status)
            # 状态改变时需要更新按钮
            self._create_task_buttons(row, task)
        elif not status_item:
            self.tasks_table.setItem(row, 1, QTableWidgetItem(status))
            self._create_task_buttons(row, task)
        
        # 进度列
        progress = task.get('progress', 0)
        total = task.get('total', 0)
        if total > 0:
            progress_text = f"{progress}/{total} ({progress*100//total}%)"
        else:
            progress_text = "0/0 (0%)"
        progress_item = self.tasks_table.item(row, 2)
        if progress_item and progress_item.text() != progress_text:
            progress_item.setText(progress_text)
        elif not progress_item:
            self.tasks_table.setItem(row, 2, QTableWidgetItem(progress_text))
        
        # 消息列
        message = task.get('message', '')[:50]
        message_item = self.tasks_table.item(row, 3)
        if message_item and message_item.text() != message:
            message_item.setText(message)
        elif not message_item:
            self.tasks_table.setItem(row, 3, QTableWidgetItem(message))
    
    def _create_task_buttons(self, row, task):
        """创建任务操作按钮"""
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(2, 2, 2, 2)
        button_layout.setSpacing(2)
        
        task_id = task.get('task_id')
        status = task.get('status', '')
        
        if status == "等待中":
            start_btn = QPushButton("开始")
            start_btn.clicked.connect(lambda checked, tid=task_id: self.start_task(tid))
            button_layout.addWidget(start_btn)
        elif status == "下载中":
            pause_btn = QPushButton("暂停")
            pause_btn.clicked.connect(lambda checked, tid=task_id: self.pause_task(tid))
            button_layout.addWidget(pause_btn)
        elif status == "已暂停":
            resume_btn = QPushButton("继续")
            resume_btn.clicked.connect(lambda checked, tid=task_id: self.start_task(tid))
            button_layout.addWidget(resume_btn)
        
        if status not in ["已完成"]:
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(lambda checked, tid=task_id: self.cancel_task(tid))
            button_layout.addWidget(cancel_btn)
        
        remove_btn = QPushButton("删除")
        remove_btn.clicked.connect(lambda checked, tid=task_id: self.remove_task(tid))
        button_layout.addWidget(remove_btn)
        
        self.tasks_table.setCellWidget(row, 4, button_widget)
    
    def start_task(self, task_id):
        """开始任务"""
        if self.download_manager.start_task(task_id):
            self.log_message(f"任务 {task_id} 已开始")
        else:
            self.log_message(f"任务 {task_id} 开始失败")
    
    def pause_task(self, task_id):
        """暂停任务"""
        if self.download_manager.pause_task(task_id):
            self.log_message(f"任务 {task_id} 已暂停")
        else:
            self.log_message(f"任务 {task_id} 暂停失败")
    
    def cancel_task(self, task_id):
        """取消任务"""
        reply = QMessageBox.question(self, "确认", "确定要取消这个任务吗？")
        if reply == QMessageBox.Yes:
            if self.download_manager.cancel_task(task_id):
                self.log_message(f"任务 {task_id} 已取消")
            else:
                self.log_message(f"任务 {task_id} 取消失败")
    
    def remove_task(self, task_id):
        """删除任务"""
        reply = QMessageBox.question(self, "确认", "确定要删除这个任务吗？")
        if reply == QMessageBox.Yes:
            if self.download_manager.remove_task(task_id):
                self.log_message(f"任务 {task_id} 已删除")
            else:
                self.log_message(f"任务 {task_id} 删除失败（可能正在运行中）")
    
    def start_all_tasks(self):
        """开始所有等待中的任务"""
        tasks = self.download_manager.get_all_tasks()
        started_count = 0
        for task in tasks:
            if task and task.get('status') in ['等待中', '已暂停']:
                if self.download_manager.start_task(task.get('task_id')):
                    started_count += 1
        
        self.log_message(f"已开始 {started_count} 个任务")
    
    def pause_all_tasks(self):
        """暂停所有运行中的任务"""
        tasks = self.download_manager.get_all_tasks()
        paused_count = 0
        for task in tasks:
            if task and task.get('status') == '下载中':
                if self.download_manager.pause_task(task.get('task_id')):
                    paused_count += 1
        
        self.log_message(f"已暂停 {paused_count} 个任务")
    
    def clear_completed_tasks(self):
        """清除已完成的任务"""
        self.download_manager.clear_finished_tasks()
        self.log_message("已清除完成的任务")
    
    def clear_all_tasks(self):
        """清除所有任务"""
        reply = QMessageBox.question(self, "确认", "确定要清除所有任务吗？这将取消所有进行中的下载！")
        if reply == QMessageBox.Yes:
            tasks = self.download_manager.get_all_tasks()
            for task in tasks:
                if task:
                    task_id = task.get('task_id')
                    self.download_manager.cancel_task(task_id)
                    self.download_manager.remove_task(task_id)
            
            self.log_message("已清除所有任务")

    # 文件浏览方法
    def browse_batch_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择URL列表文件", "", "文本文件 (*.txt);;所有文件 (*)")
        if file_path:
            self.batch_file_input.setText(file_path)
    
    def browse_ini_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择任务信息文件", "", "INI文件 (*.ini);;所有文件 (*)")
        if file_path:
            self.ini_file_input.setText(file_path)
    
    def browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dir_input.setText(dir_path)
    
    def browse_zip_path(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择7-Zip可执行文件", "", "可执行文件 (*.exe);;所有文件 (*)")
        if file_path:
            self.zip_path_input.setText(file_path)
    
    def resume_download(self):
        ini_path = self.ini_file_input.text().strip()
        if not ini_path or not os.path.exists(ini_path):
            QMessageBox.warning(self, "警告", "请选择有效的任务信息文件!")
            return
        
        try:
            delay = self.config.get('download', 'delay', 1)
            threading.Thread(target=lambda: self.download_manager.resume_download(ini_path, delay), daemon=True).start()
            self.log_message("开始从INI文件继续下载...")
            QMessageBox.information(self, "开始", "继续下载已开始!")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"继续下载失败: {e}")

    # 设置管理方法
    def load_settings(self):
        """从配置文件加载设置到界面"""
        self.output_dir_input.setText(self.config.get('download', 'output_dir', './download'))
        self.delay_spin.setValue(int(self.config.get('download', 'delay', 1)))
        self.workers_spin.setValue(self.config.get('download', 'max_workers', 3))
        self.timeout_spin.setValue(self.config.get('download', 'timeout', 30))
        self.retry_spin.setValue(self.config.get('download', 'retry_count', 3))
        
        self.compression_enabled.setChecked(self.config.get('compression', 'enabled', False))
        self.zip_path_input.setText(self.config.get('compression', 'tool_path', ''))
        format_index = self.format_combo.findText(self.config.get('compression', 'format', 'zip'))
        if format_index >= 0:
            self.format_combo.setCurrentIndex(format_index)
        self.compression_level_spin.setValue(self.config.get('compression', 'compression_level', 5))
        self.password_input.setText(self.config.get('compression', 'password', ''))
        self.delete_original.setChecked(self.config.get('compression', 'delete_original', False))
        
        self.webp_to_jpg.setChecked(self.config.get('conversion', 'webp_to_jpg', True))
        self.jpg_quality_spin.setValue(self.config.get('conversion', 'jpg_quality', 95))
        
        # 设置最大并行数
        max_concurrent = self.config.get('download', 'max_concurrent', 3)
        self.max_concurrent_spin.setValue(max_concurrent)
        self.download_manager.set_max_concurrent(max_concurrent)
    
    def update_config_from_ui(self):
        """从界面更新配置"""
        self.config.set('download', 'output_dir', self.output_dir_input.text())
        self.config.set('download', 'delay', self.delay_spin.value())
        self.config.set('download', 'max_workers', self.workers_spin.value())
        self.config.set('download', 'timeout', self.timeout_spin.value())
        self.config.set('download', 'retry_count', self.retry_spin.value())
        self.config.set('download', 'max_concurrent', self.max_concurrent_spin.value())
        
        self.config.set('compression', 'enabled', self.compression_enabled.isChecked())
        self.config.set('compression', 'tool_path', self.zip_path_input.text())
        self.config.set('compression', 'format', self.format_combo.currentText())
        self.config.set('compression', 'compression_level', self.compression_level_spin.value())
        self.config.set('compression', 'password', self.password_input.text())
        self.config.set('compression', 'delete_original', self.delete_original.isChecked())
        
        self.config.set('conversion', 'webp_to_jpg', self.webp_to_jpg.isChecked())
        self.config.set('conversion', 'jpg_quality', self.jpg_quality_spin.value())
    
    def save_settings(self):
        """保存设置"""
        self.update_config_from_ui()
        self.config.save_config()
        QMessageBox.information(self, "完成", "设置已保存!")
    
    def reset_settings(self):
        """重置设置"""
        reply = QMessageBox.question(self, "确认", "确定要重置所有设置吗？")
        if reply == QMessageBox.Yes:
            self.config = Config()
            self.load_settings()
            QMessageBox.information(self, "完成", "设置已重置!")
    
    # 日志管理方法
    def log_message(self, message):
        """添加日志消息"""
        timestamp = time.strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        self.log_text.append(formatted_message)
        
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        self.log_text.clear()
    
    def save_log(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", f"ehentai_downloader_log_{time.strftime('%Y%m%d_%H%M%S')}.txt", 
            "文本文件 (*.txt);;所有文件 (*)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                QMessageBox.information(self, "完成", "日志已保存!")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存日志失败: {e}")
    
    def closeEvent(self, event):
        """关闭事件处理"""
        active_count = self.download_manager.get_active_count()
        if active_count > 0:
            reply = QMessageBox.question(self, "确认", f"有 {active_count} 个下载任务正在进行，确定要退出吗？")
            if reply == QMessageBox.Yes:
                # 取消所有任务
                tasks = self.download_manager.get_all_tasks()
                for task in tasks:
                    if task and task.get('status') in ['下载中', '等待中', '已暂停']:
                        self.download_manager.cancel_task(task.get('task_id'))
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序信息
    app.setApplicationName("E-Hentai Downloader")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("EHentai Tools")
    
    # 创建主窗口
    window = EHentaiDownloaderGUI()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
