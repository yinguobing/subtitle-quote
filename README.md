# subtitle-quote

聊天字幕视频生成器 — 将对话文本渲染为带打字机效果的短视频，微信风格暗色配色与布局。

## 效果

- 暗色模式背景 + 圆形头像 + 对话气泡（模拟微信聊天界面）
- 打字机逐字淡入效果
- 输出 1920×1080 h264/mp4，兼容所有播放器
- 可选透明背景（qtrle/mov），适合 DaVinci Resolve 等后期合成

## 依赖

- Python 3
- [Pillow](https://python-pillow.org/) — 逐帧渲染
- [ffmpeg](https://ffmpeg.org/) — 帧合成视频

```bash
pip install Pillow
```

确保系统已安装 ffmpeg。

## 字体

默认使用 Noto Sans SC，路径在脚本中配置：

```python
FONT = "/home/robin/.local/share/fonts/NotoSansSC-Medium.ttf"
```

可改为任意支持中文的字体路径。

## 快速开始

```bash
# 单条消息
python3 subtitle_quote.py "国冰: AI 时代，你准备好了吗？" -o quote.mp4

# 指定头像
python3 subtitle_quote.py "国冰: 你好" -o quote.mp4 --avatar avatar.jpg

# 头像在右侧（模拟自己发送的消息，气泡变为微信绿）
python3 subtitle_quote.py "国冰: 我准备好了" -o quote.mp4 --right

# 透明背景（适合后期合成，输出 .mov）
python3 subtitle_quote.py "国冰: 你好" -o quote.mov --transparent

# 调整打字速度（值越大越慢，默认 2）
python3 subtitle_quote.py "国冰: 慢慢打字..." -o quote.mp4 --speed 5
```

## 批量渲染

创建文本文件 `quotes.txt`，每行一条：

```
国冰: AI 时代，你准备好了吗？
小明: 我一直在准备。
国冰: 那就开始吧。
```

```bash
python3 subtitle_quote.py quotes.txt -o output_dir/ --batch
```

输出 `output_dir/001.mp4`、`002.mp4`、`003.mp4`。

## 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `input` | — | 文本或文件路径（格式：`名字: 内容`） |
| `-o, --output` | `output` | 输出路径（单条模式自动补 `.mp4`） |
| `--avatar` | — | 头像图片路径（不指定则生成首字母头像） |
| `--right` | — | 头像在右侧（默认左侧） |
| `--width` | `1920` | 画布宽度 |
| `--height` | `1080` | 画布高度 |
| `--fps` | `24` | 帧率 |
| `--speed` | `2` | 每字符帧数，越大打字越慢 |
| `--batch` | — | 批量模式：每行生成独立视频 |
| `--transparent` | — | 透明背景（输出 qtrle/mov） |

## 可配置项

以下常量可在脚本顶部直接修改：

| 常量 | 默认值 | 说明 |
|---|---|---|
| `TEXT_SIZE` | `48` | 气泡文字大小 |
| `NAME_SIZE` | `32` | 名字文字大小 |
| `AVATAR_SIZE` | `100` | 头像尺寸 |
| `BUBBLE_PAD` | `(40,20,40,60)` | 气泡内边距 (左,上,右,下) |
| `BUBBLE_RADIUS` | `16` | 气泡圆角半径 |
| `LETTER_SPACING` | `3` | 字符间距 (px) |
| `LINE_GAP` | `30` | 行间距 (px) |
| `MAX_WIDTH` | `860` | 气泡最大宽度 |
| `FADE_SPAN` | `5` | 淡入窗口（最近 N 个字符同时渐变） |
| `VERTICAL_OFFSET` | `0` | 整体垂直偏移（正=上移） |

配色常量（RGBA 四元组）：

| 常量 | 说明 |
|---|---|
| `BG_COLOR` | 背景色 |
| `BUBBLE_COLOR_OTHER` | 对方气泡 |
| `BUBBLE_COLOR_SELF` | 自己气泡 |
| `TEXT_COLOR` | 文字颜色 |
| `NAME_COLOR` | 名字颜色 |
| `AVATAR_COLORS` | 自动头像底色列表 |
