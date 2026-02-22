# Apple Music 下载 Telegram 机器人

> **注意：** 本项目由 AI 生成，仓库主分支代码不稳定。稳定版代码请从 [Releases](../../releases) 页面下载。

基于 gamdl 的 Apple Music 下载 Telegram 机器人。

## 功能特性

- 支持下载 Apple Music 歌曲、专辑和播放列表
- 通过 [wrapper](https://github.com/WorldObservationLog/wrapper) 服务支持 ALAC（无损）和 Dolby Atmos 下载
- 可配置音频编码（ALAC、Atmos、AAC、AC3 等），不支持时自动回退至 AAC
- SQLite 数据库缓存，避免重复下载
- 白名单用户访问控制
- 并发下载限制(每用户 2 个，全局 5 个)
- 文件大小限制(默认 50MB)
- 临时文件自动清理
- 完整的元数据支持(封面、时长、艺术家等)

## 安装

### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 2. 安装系统依赖

#### macOS
```bash
brew install bento4 ffmpeg
```

#### Ubuntu/Debian
```bash
sudo apt-get update && sudo apt-get install bento4 ffmpeg
```

### 3.（可选）部署 Wrapper + amdecrypt 以支持 ALAC / Dolby Atmos

如需下载无损（ALAC）或杜比全景声（Atmos）格式，需要以下三个组件：

**1. wrapper** — 运行 [wrapper](https://github.com/WorldObservationLog/wrapper) 服务（处理账号认证）：

```bash
docker run -d \
  -p 10020:10020 -p 20020:20020 -p 30020:30020 \
  -v ./rootfs/data:/app/rootfs/data \
  -e args='-H 0.0.0.0' \
  wrapper
```

**2. amdecrypt** — 从 [glomatico/amdecrypt](https://github.com/glomatico/amdecrypt/releases) 下载对应平台的二进制文件并加入 PATH。gamdl 会直接调用此工具解密音轨。

**3. mp4decrypt** — 已通过上方 Bento4 安装，amdecrypt 内部会调用它。

完成后在 `config.yaml` 中设置 `use_wrapper: true` 并配置 `wrapper_url`。若 `use_wrapper` 为 `true` 但 wrapper 未运行，Bot 启动时将报错退出。

### 4. 获取 Apple Music Cookies

Bot 需要从 Apple Music 网站导出的 cookies 来进行认证。

#### 使用浏览器扩展(推荐)

1. 安装浏览器扩展:
   - Chrome: [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   - Firefox: [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

2. 访问 https://music.apple.com 并登录
3. 确认你的 Apple Music 订阅处于激活状态
4. 点击扩展图标，导出 cookies
5. 将文件保存为 `cookies.txt` 并放在项目根目录

#### 使用 yt-dlp

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt https://music.apple.com
```

**注意**:
- Cookies 通常 1-3 个月有效
- 过期后需重新导出
- 必须有激活的 Apple Music 订阅

### 5. 配置文件

编辑 `config.yaml`（完整选项参见 `exmaple-config.yaml`）:

```yaml
bot_token: "YOUR_BOT_TOKEN"  # 从 @BotFather 获取
cookies_path: "./cookies.txt"  # Cookies 文件路径

whitelist_users:  # 允许使用的 Telegram 用户 ID
  - 123456789
  - 987654321

max_concurrent_per_user: 2
max_concurrent_global: 5
max_file_size_mb: 50

database_path: "./data/cache.db"
temp_path: "./data/temp"

# 音频编码: atmos、alac、aac、aac-he、aac-legacy、ac3 等
# 若歌曲不支持所选编码，将自动回退至 aac
song_codec: "atmos"

# Wrapper 服务（ALAC / Dolby Atmos 支持，需先启动 wrapper）
use_wrapper: true
wrapper_url: "127.0.0.1:10020"
```

## 运行

```bash
python -m bot.main
```

## 使用方法

1. 启动 Bot 后，发送 `/start` 命令
2. 发送 Apple Music 链接，例如:
   - 单曲: `https://music.apple.com/us/album/.../1234567?i=1234568`
   - 专辑: `https://music.apple.com/us/album/.../1234567`
   - 播放列表: `https://music.apple.com/us/playlist/.../pl.xxx`

## 项目结构

```
bot/
├── models/         # 数据库模型
├── services/       # 业务逻辑服务
├── middleware/     # 中间件(白名单、并发控制)
├── handlers/       # 消息处理器
└── main.py         # 主程序入口
```

## 注意事项

1. 需要有效的 Apple Music 订阅
2. Cookies 定期(1-3个月)需要重新导出
3. 确保安装了 ffmpeg；若需 ALAC/Atmos，还需 amdecrypt 和 mp4decrypt（Bento4）
4. 确保有足够的磁盘空间用于临时文件
5. Telegram file_id 是永久的，可以重复使用
6. 文件超过 50MB 将被跳过
7. 下载后的临时文件会立即删除

## 常见问题

**Q: "media-user-token" cookie not found**
A: 确保从 https://music.apple.com 导出 cookies，并且已登录有订阅的账号

**Q: "Subscription is not active"**
A: 检查你的 Apple Music 订阅状态是否正常

**Q: Wrapper 服务不可用**
A: 启动 wrapper Docker 容器（见安装部分），或将 `use_wrapper` 设为 `false` 以仅使用 AAC 模式

**Q: Cookies 过期了怎么办？**
A: 重新从浏览器导出 cookies.txt 并重启 Bot

## 技术栈

- python-telegram-bot - Telegram Bot API
- aiosqlite - 异步 SQLite 数据库
- gamdl - Apple Music 下载核心库
- httpx - HTTP 客户端
- mutagen - 音频元数据处理
