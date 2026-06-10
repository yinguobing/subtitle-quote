#!/usr/bin/env python3
"""
聊天字幕视频生成器 subtitle_quote
每条独立渲染，透明背景，带头像+名字+打字机气泡效果

用法：
  # 单条渲染
  python3 subtitle_quote.py "国冰: AI时代，你准备好了吗？" -o quote.mp4
  
  # 批量渲染（从文件）
  python3 subtitle_quote.py input.txt -o output_dir/
  
  # 指定头像
  python3 subtitle_quote.py "国冰: 你好" -o quote.mp4 --avatar avatar.jpg

输入格式（每行一条）：
  名字: 说话内容
  名字: 下一句话

样式：默认左侧（头像名在左，气泡在右），加 --right 切换右侧
"""

import argparse
import os
import re
import tempfile
import subprocess
import math
from PIL import Image, ImageDraw, ImageFont

# ── 默认配置 ──────────────────────────────────────────────

FONT = "/home/robin/.local/share/fonts/NotoSansSC-Medium.ttf"
FONT_BOLD = "/home/robin/.local/share/fonts/NotoSansSC-SemiBold.ttf"
TEXT_SIZE = 48           # 气泡文字大小
NAME_SIZE = 32           # 名字大小
AVATAR_SIZE = 100        # 头像尺寸
BUBBLE_PAD = (40, 30, 40, 30)  # 气泡内边距 (l, t, r, b)
BUBBLE_RADIUS = 24       # 气泡圆角
AVATAR_GAP = 16          # 头像到气泡间距
LINE_GAP = 8             # 文本行间距
MAX_WIDTH = 700          # 气泡最大宽度
FPS = 20
CHAR_INTERVAL = 3        # 每字符帧数（控制打字速度）

# 颜色
BUBBLE_COLOR = (255, 255, 255, 230)       # 气泡白色半透明
TEXT_COLOR = (30, 30, 30, 255)
NAME_COLOR = (255, 255, 255, 220)
AVATAR_COLORS = [
    (66, 133, 244), (234, 67, 53), (251, 188, 4),
    (52, 168, 83), (142, 68, 173), (230, 126, 34),
]

# ── 默认头像生成 ──────────────────────────────────────────

def make_avatar(text, size, color=None):
    """生成默认圆形头像（首字母 + 纯色背景）"""
    if color is None:
        idx = abs(hash(text)) % len(AVATAR_COLORS)
        color = AVATAR_COLORS[idx]
    img = Image.new("RGBA", (size, size), color + (255,))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT, size // 2)
    except:
        font = ImageFont.load_default()
    ch = text.strip()[0] if text.strip() else "?"
    bbox = draw.textbbox((0, 0), ch, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), ch, fill="white", font=font)
    # 圆形遮罩
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return img

def load_avatar(path, size):
    """加载图片并裁剪为圆形"""
    if not path or not os.path.exists(path):
        return None
    img = Image.open(path).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return img

# ── 文字排版 ──────────────────────────────────────────────

def word_wrap(text, font, max_width, draw):
    """逐字换行，返回行列表"""
    lines = []
    cur = ""
    for ch in text:
        test = cur + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines

def measure_block(lines, font, draw):
    """测量文本块尺寸"""
    max_w = max_h = 0
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        max_w = max(max_w, w)
        max_h += h + (LINE_GAP if i < len(lines) - 1 else 0)
    return max_w, max_h

# ── 单帧渲染 ──────────────────────────────────────────────

def render_quote(name, visible_text, side, avatar_img, canvas_w=1080, canvas_h=720):
    """渲染一帧：透明背景 + 头像 + 名字 + 气泡 + 打字机文字
    
    side: 'left' 或 'right'
        left  → 头像名左, 气泡右
        right → 头像名右, 气泡左
    """
    frame = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)
    
    font = ImageFont.truetype(FONT, TEXT_SIZE)
    name_font = ImageFont.truetype(FONT, NAME_SIZE)
    
    # 换行计算
    lines = word_wrap(visible_text, font, MAX_WIDTH, draw)
    tw, th = measure_block(lines, font, draw)
    
    # 气泡尺寸
    bw = tw + BUBBLE_PAD[0] + BUBBLE_PAD[2]
    bh = th + BUBBLE_PAD[1] + BUBBLE_PAD[3]
    bw = max(bw, 100)  # 最小宽度
    
    # 整体内容的宽高
    content_w = AVATAR_SIZE + AVATAR_GAP + bw
    content_h = max(AVATAR_SIZE + NAME_SIZE + 12, bh)
    
    # 居中定位
    base_x = (canvas_w - content_w) // 2
    base_y = (canvas_h - content_h) // 2
    
    if side == 'left':
        # 头像在左
        avatar_x = base_x
        bubble_x = base_x + AVATAR_SIZE + AVATAR_GAP
        name_x = avatar_x + AVATAR_SIZE // 2
    else:
        # 头像在右
        bubble_x = base_x
        avatar_x = base_x + bw + AVATAR_GAP
        name_x = avatar_x + AVATAR_SIZE // 2
    
    # 名字（头像上方居中）
    bbox_n = draw.textbbox((0, 0), name, font=name_font)
    nw = bbox_n[2] - bbox_n[0]
    draw.text((name_x - nw // 2, base_y), name, fill=NAME_COLOR, font=name_font)
    
    # 头像
    avatar_y = base_y + NAME_SIZE + 12
    if avatar_img:
        frame.paste(avatar_img, (int(avatar_x), int(avatar_y)), avatar_img)
    
    # 气泡
    bubble_y = avatar_y + AVATAR_SIZE // 2 - bh // 2
    if bubble_y < base_y + NAME_SIZE + 12:
        bubble_y = base_y + NAME_SIZE + 12
    
    draw.rounded_rectangle(
        [bubble_x, bubble_y, bubble_x + bw, bubble_y + bh],
        radius=BUBBLE_RADIUS, fill=BUBBLE_COLOR
    )
    
    # 气泡小尾巴（指向头像方向）
    tail_size = 12
    cy = bubble_y + bh // 2
    if side == 'left':
        tx = bubble_x
        draw.polygon([
            (tx, cy - tail_size), 
            (tx - tail_size, cy), 
            (tx, cy + tail_size)
        ], fill=BUBBLE_COLOR)
    else:
        tx = bubble_x + bw
        draw.polygon([
            (tx, cy - tail_size),
            (tx + tail_size, cy),
            (tx, cy + tail_size)
        ], fill=BUBBLE_COLOR)
    
    # 文字
    pad_l, pad_t = BUBBLE_PAD[0], BUBBLE_PAD[1]
    tx_pos = bubble_x + pad_l
    ty_pos = bubble_y + pad_t
    for line in lines:
        draw.text((tx_pos, ty_pos), line, fill=TEXT_COLOR, font=font)
        bbox = draw.textbbox((0, 0), line, font=font)
        ty_pos += bbox[3] - bbox[1] + LINE_GAP
    
    return frame


def render_quote_clip(name, text, side, avatar_img, 
                       canvas_w=1080, canvas_h=720, fps=FPS, chars_per_frame=CHAR_INTERVAL):
    """渲染整段话的所有帧，返回帧列表"""
    frames = []
    total_chars = len(text)
    
    for ci in range(1, total_chars + 1, chars_per_frame):
        visible = text[:ci]
        f = render_quote(name, visible, side, avatar_img, canvas_w, canvas_h)
        frames.append(f)
    
    # 完整显示后停留一会儿
    full_frame = render_quote(name, text, side, avatar_img, canvas_w, canvas_h)
    for _ in range(int(fps * 2)):  # 停留 2 秒
        frames.append(full_frame.copy())
    
    return frames


def save_frames_to_video(frames, output_path, fps=FPS):
    """将帧列表保存为视频（带透明通道）"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, frame in enumerate(frames):
            path = os.path.join(tmpdir, f"f_{i:06d}.png")
            frame.save(path, "PNG")
        
        # 用 ffmpeg 合成（qtrle 支持 alpha）
        cmd = [
            'ffmpeg', '-y',
            '-framerate', str(fps),
            '-i', os.path.join(tmpdir, 'f_%06d.png'),
            '-c:v', 'qtrle',
            '-pix_fmt', 'rgba',
            output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    
    return output_path


def parse_input(source):
    """解析输入：文件或文本"""
    if os.path.isfile(source):
        with open(source, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return source.strip()


def main():
    parser = argparse.ArgumentParser(description='字幕引用视频生成器')
    parser.add_argument('input', help='输入文本或文件路径（每行: 名字: 内容）')
    parser.add_argument('-o', '--output', default='output', help='输出路径（目录或文件）')
    parser.add_argument('--avatar', help='头像图片路径（所有引用共用）')
    parser.add_argument('--right', action='store_true', help='头像在右侧（默认左侧）')
    parser.add_argument('--width', type=int, default=1080, help='画布宽度')
    parser.add_argument('--height', type=int, default=720, help='画布高度')
    parser.add_argument('--fps', type=int, default=FPS, help='帧率')
    parser.add_argument('--speed', type=int, default=CHAR_INTERVAL, 
                        help='每帧跳过字符数（越大打字越快）')
    parser.add_argument('--batch', action='store_true', 
                        help='批量模式：将 input 文件每行渲染为独立视频')
    
    args = parser.parse_args()
    args.input = parse_input(args.input)
    
    # 头像
    avatar_img = load_avatar(args.avatar, AVATAR_SIZE)
    
    # 解析所有行
    lines = [l.strip() for l in args.input.split('\n') if l.strip()]
    quotes = []
    for line in lines:
        m = re.match(r'^([^:]+):\s*(.*)', line)
        if m:
            name = m.group(1).strip()
            text = m.group(2).strip()
            if text:
                quotes.append((name, text))
    
    if not quotes:
        print("未找到有效内容，格式：名字: 内容")
        return
    
    side = 'right' if args.right else 'left'
    
    if args.batch or len(quotes) > 1:
        # 批量模式
        os.makedirs(args.output, exist_ok=True)
        for i, (name, text) in enumerate(quotes):
            loc_avatar = avatar_img or make_avatar(name, AVATAR_SIZE)
            frames = render_quote_clip(name, text, side, loc_avatar,
                                        args.width, args.height, args.fps, args.speed)
            out = os.path.join(args.output, f"{i+1:03d}.mov")
            save_frames_to_video(frames, out, args.fps)
            print(f"  [{i+1}/{len(quotes)}] {name}: {text[:30]}... → {out}")
        print(f"完成，共 {len(quotes)} 段")
    else:
        # 单条模式
        name, text = quotes[0]
        loc_avatar = avatar_img or make_avatar(name, AVATAR_SIZE)
        frames = render_quote_clip(name, text, side, loc_avatar,
                                    args.width, args.height, args.fps, args.speed)
        out = args.output if args.output.endswith('.mov') else args.output + '.mov'
        save_frames_to_video(frames, out, args.fps)
        print(f"→ {out}")


if __name__ == '__main__':
    main()
