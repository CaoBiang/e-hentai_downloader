from loguru import logger
from PIL import Image
import os


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


def process_directory(input_dir, quality=95):
    """
    处理文件夹中的所有WebP文件

    参数:
        input_dir (str): 输入文件夹路径
        quality (int): 输出JPG的质量(1-100)
    """
    if not os.path.isdir(input_dir):
        logger.error(f"输入路径不是文件夹: {input_dir}")
        return False

    success_count = 0
    fail_count = 0

    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.lower().endswith('.webp'):
                input_path = os.path.join(root, file)
                if webp_to_jpg(input_path, quality=quality):
                    success_count += 1
                else:
                    fail_count += 1

    logger.info(f"批处理完成: 成功 {success_count} 个文件, 失败 {fail_count} 个文件")
    return True


if __name__=="__main__":
    input_path = input().replace('"','')
    if os.path.isdir(input_path):
        process_directory(input_path)
    else:
        webp_to_jpg(input_path)