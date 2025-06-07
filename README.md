# E-Hentai 下载器 v2.0

一个功能强大的E-Hentai画廊下载工具，支持GUI界面、自动压缩、并行下载等高级功能。

## 功能特性

### 核心功能
- 🖼️ **智能下载**：自动处理内容警告页面，支持多页画廊
- 🔄 **并行下载**：可配置的多线程并行下载，提高下载效率
- 📦 **自动压缩**：集成7-Zip支持，下载完成后自动压缩为zip/7z/rar格式
- 💾 **断点续传**：通过INI文件记录下载状态，支持失败重试和断点续传
- 🔧 **配置管理**：JSON格式配置文件，所有设置可持久化保存

### 图片处理
- 🖼️ **格式转换**：自动将WebP格式转换为JPG，可配置质量
- 📁 **路径安全**：自动处理文件名中的非法字符，确保跨平台兼容

### 界面选择
- 💻 **命令行模式**：支持参数调用和交互式操作
- 🖥️ **图形界面**：基于PyQt5的现代化GUI界面，实时进度显示

## 安装要求

### Python 依赖
```bash
pip install -r requirements.txt
```

### 系统要求
- Python 3.7+
- Windows/Linux/macOS

### 可选依赖
- **7-Zip**：用于高质量压缩（推荐安装）
  - Windows: 下载并安装 [7-Zip官方版本](https://www.7-zip.org/)
  - Linux: `sudo apt install p7zip-full`
  - macOS: `brew install p7zip`

## 使用方法

### 1. GUI模式（推荐）

```bash
python ehentai_downloader_gui.py
```

#### GUI功能说明
- **下载选项卡**：输入URL，选择下载模式
- **设置选项卡**：配置下载参数、压缩选项等
- **任务管理**：查看和管理下载任务
- **日志查看**：实时查看下载日志

### 2. 命令行模式

#### 单个画廊下载
```bash
python ehentai_downloader.py -u "画廊URL" -o "输出目录"
```

#### 批量下载
```bash
python ehentai_downloader.py -f urls.txt -d 2
```

urls.txt格式示例：
```
https://e-hentai.org/g/xxxxxx/xxxxxxxxxx/
https://e-hentai.org/g/yyyyyy/yyyyyyyyyy/
# 这是注释行，会被忽略
```

#### 断点续传
```bash
python ehentai_downloader.py -i "path/to/task_info.ini"
```

### 3. 交互模式

```bash
python ehentai_downloader.py
```

然后按提示选择操作模式。

## 配置说明

程序会自动生成`config.json`配置文件，主要配置项：

### 下载设置
```json
{
  "download": {
    "output_dir": "./download",    // 输出目录
    "delay": 1.0,                  // 请求延迟（秒）
    "max_workers": 3,              // 最大并行下载数
    "timeout": 30,                 // 请求超时时间
    "retry_count": 3               // 重试次数
  }
}
```

### 压缩设置
```json
{
  "compression": {
    "enabled": false,              // 是否启用自动压缩
    "tool_path": "",               // 7-Zip可执行文件路径
    "format": "zip",               // 压缩格式: zip/7z/rar
    "compression_level": 5,        // 压缩级别 0-9
    "password": "",                // 压缩密码
    "delete_original": false,      // 压缩后是否删除原文件夹
    "max_parallel": 2              // 最大并行压缩数
  }
}
```

### 转换设置
```json
{
  "conversion": {
    "webp_to_jpg": true,           // 是否将WebP转换为JPG
    "jpg_quality": 95              // JPG质量 1-100
  }
}
```

## 高级功能

### 自动压缩
1. 在设置中启用"自动压缩"
2. 设置7-Zip可执行文件路径
3. 选择压缩格式和级别
4. 可选设置压缩密码

### 并行下载优化
- 调整`max_workers`参数控制并行度
- 根据网络状况调整`delay`和`timeout`
- 合理设置重试次数`retry_count`

### 断点续传机制
- 每次下载完成后会生成`task_info.ini`文件
- 记录所有图片的下载状态
- 支持从任意断点重新开始下载

## 故障排除

### 常见问题

1. **下载速度慢**
   - 降低并行数`max_workers`
   - 增加请求延迟`delay`
   - 检查网络连接

2. **下载失败**
   - 检查URL是否正确
   - 确认画廊是否可访问
   - 增加重试次数和超时时间

3. **压缩失败**
   - 检查7-Zip路径是否正确
   - 确认有足够的磁盘空间
   - 检查文件权限

4. **GUI界面问题**
   - 确认已安装PyQt5
   - 尝试命令行模式作为备选

### 日志文件
程序会自动生成`ehentai_downloader.log`日志文件，记录详细的运行信息，有助于问题诊断。

## 更新日志

### v2.0 新功能
- ✨ 全新PyQt5图形界面
- 🗂️ JSON配置文件系统
- 📦 集成7-Zip自动压缩
- ⚡ 多线程并行下载
- 🔄 增强的断点续传
- 🖼️ WebP自动转换
- 📊 实时进度显示
- 📝 完整的任务管理

## 许可证

本项目仅供学习交流使用，请遵守相关网站的使用条款。

## 贡献

欢迎提交Issue和Pull Request来改进这个项目。

## 免责声明

本工具仅用于学习和研究目的。用户应当遵守相关法律法规和网站服务条款，作者不承担因使用本工具而产生的任何法律责任。