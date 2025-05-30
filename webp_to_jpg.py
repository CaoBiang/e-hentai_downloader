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


if __name__=="__main__":
    input_path=input().replace('"','')
    webp_to_jpg(input_path)