# FGO 三服模拟器抓包 → Chaldea 导入文件

## 下载（普通用户）

到 [Releases](https://github.com/Ankler-wood/fgocapture/releases/latest) 下载 **FGOCapture.exe + readme.txt** 两个文件即可，
不需要 Python、不需要编译。想自己打包或改代码，看下面第二节。

### 国内网盘镜像（可选）

GitHub 在大陆访问慢，可以把同样的文件放一份到网盘，链接填到下面这张表（没有就写"暂无"）：

| 网盘 | 链接 | 提取码 | 文件 |
|---|---|---|---|
| 百度网盘 | [pan.baidu.com/s/1rEIz_a3GhG-50Ohspkxu2Q](https://pan.baidu.com/s/1rEIz_a3GhG-50Ohspkxu2Q?pwd=5y98) | `5y98` | 分享名「fgo一键抓包」：`FGOCapture-v1.0.5.zip`（内含 exe + readme.txt） |

网盘传的是 **zip**（避免平台对 .exe 的拦截）。解压后先核对：

- `FGOCapture-v1.0.5.zip` 的 SHA-256：`802dd2a920078224aa0c6ed435568a50b22e62fbe5ab359219ca6e2280e67418`
- 里面 `FGOCapture.exe` 的 SHA-256：`38e9b939eb24202f7b4fd67e922118184c2fe47edad1d2e31c63c4949239f442`
- 签名证书指纹：`2F68AC2B254BD0B848D6F654F9129E0AD5516FE4`

核对方法：解压后跑 `FGOCapture.exe --verify`，或 PowerShell 里
`Get-FileHash .\FGOCapture.exe -Algorithm SHA256`。

> 网盘分享的内容上传者可以随时替换，所以**每个版本都用新文件名**（带版本号），不要覆盖旧文件；
> 哈希对不上就别运行。

一台 PC、三个模拟器（华为渠道服 / 简中安卓B服 / 日服），跑一条命令：

- 自动认出每个模拟器装的是哪个服；
- 给每个模拟器装上抓包证书、单独分配代理端口（三台互不串包）；
- 你只要进游戏到「地球仪 / 公告页」，登录响应里的**账号全量数据**就会被原样存成
  **Chaldea 的导入文件**；
- 最后统一汇总到 `导入文件/` 目录，按服命名，你手动导入 Chaldea 就行。

> 已在 **雷电模拟器 9（Android 9）+ 三个实例** 上实测：B服的 `login.php`、
> 资源清单、`member.php` 都能正常解密落盘。

---

## 零、直接用 exe（推荐，零安装）

**发给别人的只需要两个文件：`FGOCapture.exe` + `readme.txt`。**

exe 是自包含单文件（约 33 MB），**不需要 Python、不需要装依赖**；教程和校验信息也都在里面：

```bat
FGOCapture.exe --tutorial   :: 打印使用说明（不用打开 txt 也能看）
FGOCapture.exe --verify     :: 自检：文件 SHA-256、内置数据校验、签名证书指纹
```

1. 把 `FGOCapture.exe` 拷到任意目录（比如桌面新建的 `FGO抓包` 文件夹）；
2. 打开三个模拟器后，**双击它**；
3. 按窗口提示进游戏 → 拿导入文件。

细节：

- **第一次运行**会先解包到 `%LOCALAPPDATA%\FGOCapture\app-<版本>`（2~3 秒），之后每次启动
  只加载不解包，很快；想改解包位置就设环境变量 `FGO_CAPTURE_HOME`。
- `conf\`（抓包证书）和 `out\`（抓包结果）会生成在**exe 旁边**，整个文件夹拷走就能带走历史记录。
- 支持参数：`FGOCapture.exe --list`、`--clean`、`--only jp`、`--duration 120` …（同下面第六节）。
  命令行里跑时窗口会保留输出，双击时抓包结束窗口会自动关掉（结果已落盘）。

> 想改代码 / 自己重新打包：`build_exe.bat` 一条龙（PyInstaller 文件夹版 → 压缩 → C# 启动器
> 塞进 exe），产物就是 `FGOCapture.exe`。源码用法见下面第二、三节。

---

## 一、前置条件

1. **模拟器必须能开 root**（系统证书要靠它装进去）
   - 雷电模拟器 9：`设置 → 其他设置 → root 权限` → 打开 → 重启模拟器
   - MuMu 12：`设置 → 其他 → 开启 root`
   - 夜神：`设置 → 通用设置 → 开启 root`
2. **模拟器重启后要重跑一次脚本**（证书是 bind mount 挂上去的，重启就没了，脚本每次
   启动会自动重挂）。
3. 用**模拟器自带的 adb**（雷电在安装目录里就有 `adb.exe`；脚本会自动找到）。
4. Python 3.9+（推荐 3.10–3.13）。

三个服的 `targetSdk` 分别是 30 / 33 / 36，都 ≥ 24，所以**用户证书无效，必须系统证书** ——
没有 root 就一定抓不到 HTTPS，`errors.log` 里会刷 `TLS 握手失败`。

---

## 二、安装

双击 `setup_env.bat`（首次要下载几十 MB）。它会在本目录建 `.venv` 并装好 mitmproxy。

下载慢就换成镜像：

```bat
.venv\Scripts\python.exe -m pip install mitmproxy -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 三、抓包（三步）

1. **打开三个模拟器**（分别装好华为渠道服 / 简中B服 / 日服）。
2. 双击 `run.bat`。窗口会先自检并打印识别结果：

```
序列号              机型        安卓    root   识别为        游戏包名
--------------------------------------------------------------------------------
emulator-5554      GM1900      9       已是   华为渠道服    com.bilibili.fgo.huawei
emulator-5556      DT1901A     9       已是   简中B服       com.bilibili.fatego
emulator-5558      DT1901A     9       已是   日服          com.aniplex.fategrandorder

抓包计划：
  华为渠道服   emulator-5554  端口 8081 -> ...\out\20261123-0010\华为渠道服
  简中B服      emulator-5556  端口 8082 -> ...\out\20261123-0010\简中B服
  日服         emulator-5558  端口 8083 -> ...\out\20261123-0010\日服
```

3. 依次进三个模拟器的 FGO，**登录到出现地球仪 / 公告页**。窗口里看到：

```
--- 00:12:40 ---
  简中B服      游戏接口 26   其他 12   资源 3    ★导入文件已生成 uid=100xxxx
  日服         游戏接口 8    其他 4    资源 0    尚未抓到登录
```

**每抓到一个服就会立刻复制进 `导入文件/`**（窗口里打印「★ xxx 已导出」），所以不用等三家
都完成，也不用担心"有一个没抓完，另外两个白抓了"——先完成的文件已经在磁盘上了。
三台都拿到后脚本会自动停；也可以随时按 `Ctrl+C`，它会还原代理、卸载证书。

> 注意：直接点窗口右上角 X 关掉，文件同样不会丢，但代理和证书不会自动还原，
> 下次运行会重新接管，或者手动跑一次 `--clean`。

> 建议先把三个服的游戏都更新完再抓：游戏更新会走代理，速度慢很多。

---

## 四、输出

每抓完一个服，文件就立刻出现在 `导入文件/`（不等收尾）。抓完**默认只保留导入文件**：每个服的 `game/`、`flows/`、`index.csv`、`auth.json` 等中间产物
会在收尾时自动删掉；没抓到导入文件的服则整份保留，方便重试排查。想全留就加 `--keep-all`。

```
out/20261123-1240/
└─ 导入文件/                      ← 你手动导入 Chaldea 的地方，只有这些
   ├─ 简中B服_安卓区_toplogin.json
   ├─ 华为渠道服_toplogin.json
   ├─ 日服_toplogin.json
   └─ README.txt
```

加了 `--keep-all` 才会额外保留（排查问题用）：

```
out/20261123-1240/<服名>/
   ├─ chaldea/toplogin_*.json          Chaldea 导入文件（原样，逐字节）
   ├─ chaldea/toplogin_*.decoded.json  仅供人看的解码版（简中服/繁中服是 base64）
   ├─ game/                             FGO 业务接口明细
   ├─ flows/                            其他请求（SDK、推送、CDN 等）
   ├─ index.csv                         索引
   ├─ summary.md                        汇总（含识别出的区服）
   └─ errors.log                        TLS 失败等
```

---

## 五、导入 Chaldea（手动）

Chaldea 要的就是**登录响应体本身**（官方文档：简中服/繁中服是 `ey` 开头的 base64，日服/美服是
明文 json）。具体是哪一条：

- 日服：`POST https://game.fate-go.jp/login/top`，约 **5~6 MB**，账号数据在
  `cache.replaced`（`userSvt`、`userItem` 等几百个字段）；
- 简中服/华为渠道服：`POST .../rgfate/60_XXXX/ac.php?_key=toplogin`，约 **10 MB**，base64。

所以导入文件 5~10 MB 是正常的，不要以为坏了。脚本靠“响应里有 `userSvt` / `userItem` 这类
字段 + 体积足够大”来认它。

1. 打开 Chaldea → 导入数据 / 抓包导入；
2. 选对应区服（简中服 Android / 简中服 iOS / 日服 …）；
3. 选 `导入文件/<服>_toplogin.json`，**原样导入**。

注意：

- **不要**用记事本打开再保存，也不要把 base64 转成别的编码；文件是逐字节原样拷贝的。
- 一个文件对应一个服的一个账号。换账号就重抓一次。
- `auth.json` 里的 authkey / uid 不是 Chaldea 要的东西，留作参考即可，**别外传**。

如果哪天只有旧的抓包记录、没有生成导入文件，可以用兜底脚本：

```bat
.venv\Scripts\python.exe make_import.py out\...\game\0xxxx_login.php.json
```

它会把那条 flow 的响应体重新存成 `chaldea/toplogin_*.json`。

---

## 六、参数

| 参数 | 作用 |
|---|---|
| `--list` | 只列出设备识别结果，不动任何设置 |
| `--dry-run` | 只打印抓包计划，不装证书、不改代理 |
| `--only jp` | 只抓指定服，逗号分隔：`--only jp,bilibili` |
| `--map emulator-5554=jp` | 包名判断不准（比如游戏还没装）时手动指定 |
| `--duration 120` | 抓 120 秒后自动停 |
| `--out D:\cap` | 指定输出根目录（默认 `out/<时间戳>`） |
| `--port-base 9081` | 起始代理端口（默认 8081） |
| `--launch` | 先用 `ldconsole` 把雷电实例都启动起来 |
| `--flow-dump` | 额外写 `traffic.flow`，可 `mitmweb -r` 打开逐条看 |
| `--keep-ca` | 退出时不卸载系统证书 |
| `--ignore "正则1,正则2"` | 覆盖「不做解密的域名」列表 |
| `--no-kill` | 不自动结束正在运行的 FGO（默认会结束，否则旧进程不认新证书） |
| `--keep-all` | 保留全部中间文件（默认抓完只留 `导入文件/`） |
| `--clean` | 只清理：还原代理、卸载证书 |
| `--adb <路径>` | 手动指定 adb.exe |

`run.bat` 后面直接跟参数，例如 `run.bat --list`、`run.bat --only jp --duration 120`。

---

## 七、三个服的差异（脚本已内置）

| | 华为渠道服 | 简中B服 | 日服 |
|---|---|---|---|
| 包名 | `com.bilibili.fgo.huawei` | `com.bilibili.fatego` | `com.aniplex.fategrandorder` |
| 游戏接口 | `line*-s1-uo-fate.biligame.net` | `le1-bili-fate.biligame.net` 等 | `game.fate-go.jp` |
| 登录响应 | base64（`ey…`） | base64（`ey…`） | json |
| 证书绑定 | 无 | 无 | 有，但 2.80.5+ 官方包在「系统证书」下可抓 |

### 它是怎么认出「哪个版本」的

两层判断，互相补位：

1. **客户端看包名**（抓包前就能定）：

   | 包名 | 判定 |
   |---|---|
   | `com.aniplex.fategrandorder` | 日服 |
   | `com.aniplex.fategrandorder.en` | 美服 |
   | `com.bilibili.fatego` | 简中服客户端 |
   | `com.bilibili.fgo.huawei` / `.xiaomi` / `.oppo` / `.vivo` / `.yyb` … | 对应渠道服 |
   | `com.komoe.fategrandch` / `*fgetw*` | 繁中服 |
   | 其他带 `fgo`/`fate` 的包 | 「未识别FGO」——照样抓，只是名字不知道 |

2. **区服看接口域名**（抓包时确定，同一个安卓包可能是不同区）：

   | 域名特征 | 区服 |
   |---|---|
   | `*-bili-fate.biligame.net` | 简中服-安卓区 |
   | `*-ios-fate.biligame.net` | 简中服-iOS区 |
   | `*-uo-fate.biligame.net` | 简中服-渠道服 |
   | `game.fate-go.jp` / `.us` / `.com.tw` | 日服 / 美服 / 繁中服 |

   所以「简中 apple 服」这种**同一个安卓包、账号在 iOS 区**的情况也能区分出来——
   导入文件名会写成 `简中B服_安卓区_toplogin.json` / `简中B服_iOS区_toplogin.json`，
   导入 Chaldea 时照着选区服就不会错。

---

## 八、其他模拟器 / 分享给别人
| 模拟器 | 状态 | 注意 |
|---|---|---|
| 雷电模拟器 9 | ✅ 实测通过（Android 9） | 开 root 即可 |
| MuMu 12 | 原理上可用 | 必须开 root；adb 端口 16384 起，脚本会自动握手 |
| 夜神 / MEmu | 原理上可用 | 开 root；端口 62001 / 21503 |
| BlueStacks 5 | ❌ 不推荐 | 系统设置被阉割、root 难开 |

要求就三条：**Android 7+、能开 root、adb 能连上**。脚本已经自动探测上面这些端口；
万一没探测到，用 `--adb <模拟器目录>\adb.exe` 指定，或先手动 `adb connect 127.0.0.1:<端口>`。

给别人用时，对方只需要：

1. Windows 电脑 + 上面这种模拟器；
2. 模拟器里装好对应服的 FGO（**华为渠道服还要装 HMS Core 并登录华为账号**）；
3. 拿到 `FGOCapture.exe` 双击运行 —— **不需要 Python、不需要 Chaldea、不需要 Drony**。

不要把自己的 `auth.json` / `toplogin_*.json` 一起发出去，那里面是账号数据。

### 分享时怎么防「别人往里塞病毒」

先说清楚一个事实：**加密不能防止别人改文件**（他们可以直接解开、改了再打包）。真正能防的是
「改了就一定能被发现」，所以做的是**三层校验**：

| 层 | 作用 | 怎么用 |
|---|---|---|
| ① 内嵌载荷自校验 | 启动器把自己包里 `app.zip` 的 SHA-256 和构建时写死的常量比对，被换过 payload 就**拒绝启动** | 自动，无需操作 |
| ② 文件哈希对得上 readme.txt | 文件只要有 1 比特改动，SHA-256 就变 | `FGOCapture.exe --verify` 打印的「文件 SHA-256」，或自己算 `Get-FileHash` |
| ③ Authenticode 签名 | 改动后签名状态会变成 `HashMismatch` | 右键 exe → 属性 → 数字签名；`--verify` 也会打印签名指纹 |

**分享时只发两个文件**（不需要额外的 .sha256 / .cer / bat）：

```
FGOCapture.exe      程序（自带自检 + 自带教程）
readme.txt         教程 + 本版本的 SHA-256 + 证书指纹
```

对方拿到后：

- 想看怎么用：双击运行，或 `FGOCapture.exe --tutorial`；
- 想确认没被改过：`FGOCapture.exe --verify` —— 会打印文件哈希、内置数据自校验、签名指纹，
  **和 readme.txt 里写的值对一下**，任何一项不对就别运行。
- Windows 仍会显示「未知发布者」——自签名证书做不到免警告，这不影响使用。

几点局限（别被「签名」两个字误导）：

- 证书是**自签名**的，Windows 仍会提示「未知发布者」。它的价值是：别人改了 exe，签名立刻
  失效；对方拿 `--verify` 打出来的指纹和 readme.txt 里的写值一对，就知道是不是原版。
- 想彻底杜绝「别人另做一个能用的带毒版本冒充你」，只能买**受信任 CA 的代码签名证书**（几百到
  几千元/年），或用平台分发（GitHub Release + 公开哈希）。
- 指纹：`2F68AC2B254BD0B848D6F654F9129E0AD5516FE4`（重新签名会变，以 `FGOCapture.exe --verify` 打印的为准）。

自己重新打包后要重新签名：右键 `tools\sign_exe.ps1` → 使用 PowerShell 运行（证书只在你本机
用户证书库，5 年有效，可随时删）。

## 九、原理

```
模拟器内 FGO（Unity / libcurl）
   │ HTTPS，信任系统证书里的 mitmproxy CA
   ▼
127.0.0.1:808X        ← adb reverse tcp:808X tcp:808X，每台模拟器独立端口
   ▼
PC 上 mitmdump -p 808X -s fgo_addon.py      ← 一台模拟器一个进程，互不干扰
   │ 解 TLS → 判断是不是 FGO 接口 → 找含 `userSvt` / `userItem` 的账号全量响应
   ▼
out/<时间>/<服>/chaldea/toplogin_*.json + game/*.json + index.csv
```

两个关键点：

1. **系统证书用 bind mount，不用 adb remount。**
   雷电 9 的 `/`、`/system` 是只读 ext4，`adb remount` 直接 `Permission denied`。
   脚本把 `/data/local/tmp/fgo_cacerts`（可写，先 `cp -a` 了一份原厂证书）挂到
   `/system/etc/security/cacerts` 上；实测 `ls` 与系统证书目录同 inode，App 立刻可见。
   代价：**模拟器重启后挂载消失**，重跑脚本即可；退出时脚本会自动卸载。

2. **Java 系 SDK 的域名不做解密（`ignore_hosts` 盲转发）。**
   实测华为 HMS、bilibili SDK、bugly 这些 Java/OkHttp 组件大多带证书绑定，强行解密只会
   让它们 `TLS 握手失败`；而 FGO 本体是 Unity + libcurl，会读系统证书，能正常解密。
   所以默认把这些域名排除在中间人之外（纯 CONNECT 隧道，客户端看到的是真证书）。
   需要抓它们时用 `--ignore ""` 关掉。

---

## 十、常见问题

**1. 一直「尚未抓到登录」/ 游戏连不上**
- 先看 `errors.log`：一堆 `TLS 握手失败` = 证书没被信任，检查 root 是否真开了
  （`run.bat --list` 的 root 列）、`adb shell ls /system/etc/security/cacerts/*.0`；
- 游戏停在更新界面也会一直没登录，等它更完或先更完再抓；
- 有些 App 完全无视系统代理，那就得用 Reqable（小黄鸟）的 VPN 模式；
  本脚本装好的系统证书可以直接复用。

**2. `adb remount` 报 Permission denied**
正常，雷电的系统分区只读。脚本用的是 bind mount，不需要 remount。

**3. 华为渠道服一直抓不到 / 报 `-104 登录失败`**
两个已知原因，脚本都已处理：

- **HMS 的域名被解密了**：华为登录要走 `*.huawei.com`、`*.dbankcloud.cn` 等，这些域名
  带证书绑定，必须放过（不做中间人）。脚本默认已经把华为全家桶放进 `ignore_hosts`，
  配置写在 `conf/config.yaml` 里（注意不能用命令行 `--set ignore_hosts=a,b,c`，mitmproxy
  会把它当**一个**正则，等于全不生效）。
- **游戏进程是抓包前就在跑的**：Android 的证书信任在进程启动时就定死了，旧进程不认新装的
  证书，所有请求都会 TLS 失败。脚本现在会检测到游戏在跑就 `am force-stop` 掉，**重开游戏**
  即可。

如果按上面做了还是 -104，就按视频评论区 Q3 的办法开 **Drony**：把 Drony 的手动代理指到
脚本打印的端口（如 `127.0.0.1:8081`），再用脚本抓。**注意抓包时只留一个代理链路**，
先关掉 Drony 试一次，不行再开。

**4. 日服抓不到**
日服有证书绑定，必须用**系统证书**（脚本已做）。另外确认模拟器是 Android 7+。

**5. 忘了 Ctrl+C / 脚本被关掉，游戏连不上网**
```bat
run.bat --clean
```
手工版：`adb shell settings put global http_proxy :0` + `adb shell umount /system/etc/security/cacerts`

**5.5 双击后窗口一闪就没了**
- 现在退出前会停住并显示退出码/原因（按任意键关闭）；
- 想自己看细节：`FGOCapture.exe --pause --list`（`--pause` 让窗口停住），
  完整输出也会写进 exe 旁边的 `logs\run-*.log`；
- 最常见原因：**没开模拟器**（检测不到设备就直接结束）、被杀软拦截、
  或解包目录没权限（`%LOCALAPPDATA%` 被限制时设 `FGO_CAPTURE_HOME` 换个位置）。

**5.6 提示「没找到 adb.exe」**
程序会按这个顺序找：`--adb` 参数 → 程序旁边的 `adb.exe` → PATH → 已知安装位置 →
**正在运行的模拟器进程** → 卸载表里的安装目录 → 各盘按目录名扫一遍。
如果还是没找到（比如装在 `D:\安装程序\雷电模拟器9\` 这种自定义路径、且模拟器没开）：

1. 把模拟器目录里的 `adb.exe` 复制到 `FGOCapture.exe` 旁边，再运行（最省事）；
2. 或者 `FGOCapture.exe --adb "D:\安装程序\雷电模拟器9\adb.exe"`；
3. 或者先把模拟器启动起来，程序会从运行中的进程推断路径。

**6. 端口被占用**
`--port-base 9081`。

**7. 目录里有个 `tmp` / `.tmp` / `dist` / `_MEI*`**
打包和安装过程的临时残留，直接删掉即可，不影响使用（本机可能因为权限删不掉，重启后再删）。

---

## 十一、安全与合规

- 只抓**你自己设备、你自己账号**的流量。
- `chaldea/toplogin_*.json` 和 `auth.json` 里是账号数据/会话凭据，**等同于账号**：
  不要发群、发贴吧、贴 issue、传网盘。
- 抓包会改变网络路径，偶发断线正常；抓完让脚本还原代理即可。
- 本工具只做「看自己的数据」，不含自动抽卡、自动刷本等自动化逻辑。

## 十二、许可与第三方

- 本项目代码采用 **MIT**（见 `LICENSE`）。你可以自由使用、修改、再分发，保留版权声明即可；
  软件按"现状"提供，不附带担保。
- exe 里打包了 mitmproxy（MIT）、Python（PSF）、PyInstaller 引导程序（GPL 例外条款）等开源组件，
  完整清单和许可见 `THIRD-PARTY-NOTICES.md`。分发 exe 时请带上这个文件。
- 本项目在 **AI 辅助**下开发（代码由 AI 生成，经人工设计流程、真机验证与反复修正）。
  如对 AI 生成内容的著作权归属有疑问，可把它当作"无担保、可自由使用"的代码。