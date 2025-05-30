# E-Hentai 画廊下载器

这是一个用于从E-Hentai网站下载画廊图片的Python脚本。它可以自动获取画廊中的所有图片，并按照顺序保存到本地。

## 功能特点

- 输入画廊URL，自动下载所有图片
- 按照顺序对图片进行命名
- 自动创建以画廊标题命名的文件夹
- 支持多页画廊
- 可自定义下载延迟，避免请求过快

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 基本用法

```bash
python ehentai_downloader.py "https://e-hentai.org/g/画廊ID/画廊Token/"
```

### 高级选项

```bash
python ehentai_downloader.py "https://e-hentai.org/g/画廊ID/画廊Token/" -o "下载目录" -d 2
```

参数说明：
- `-o, --output`: 指定下载目录（可选，默认为当前目录下以画廊标题命名的文件夹）
- `-d, --delay`: 请求间隔时间，单位为秒（可选，默认为1秒）

## 注意事项

- 请合理设置下载延迟，避免对网站造成过大负担
- 部分画廊可能需要登录才能访问，本脚本暂不支持登录功能
- 请遵守网站的使用条款和版权规定