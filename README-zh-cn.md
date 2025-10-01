# zeronet-conservancy

[![Packaging status](https://repology.org/badge/vertical-allrepos/zeronet-conservancy.svg)](https://repology.org/project/zeronet-conservancy/versions)

**(注意：本文档的翻译版本通常滞后于最新内容)**

[in English](README.md) | [em português](README-ptbr.md) | [по-русски](README-ru.md) | [日本語](README-ja.md)

`zeronet-conservancy` 是 [零网 ZeroNet](https://github.com/HelloZeroNet/ZeroNet) 项目的一个分支/延续（其创建者已放弃维护），致力于维持现有的p2p网络，进一步发扬去中心化与自由的价值观，并逐步得到一个设计得更好的网络。

## 本分支的状况

在onion-v3切换危机期间，我们需要一个能够支持onion-v3，且不仅仅依赖于个别开发者的可信的分支。本分支从实现这一任务开始，对 [ZeroNet/py3](https://github.com/HelloZeroNet/ZeroNet/tree/py3) 分支作了最少的改动，从而让任何人都可以轻松地审计这些改动。

目前，0net正陷入前所未有的危机，而本分支似乎是唯一存活下来的。我们的开发进展缓慢，但其中的部分工作正在幕后进行。如果你完全是个0net的新手，且没有人指导你，而且你也不是开发者的话，我们建议请等待v0.8版本发布。

## 为何选择0net？

* 我们相信开放、自由和不受审查的网络与通讯。
* 不受单点故障影响：只要至少有一个节点在提供服务，站点就能保持在线。
* 无需托管费用：站点由访问者们来共同托管。
* 无法被关停：因为节点无处不在。
* 快速并且支持离线访问：即使没有互联网，你也可以访问站点。

## 功能
* 实时更新站点
* 一键克隆已有的站点
* 使用私钥/公钥的免密码认证
* 内置SQL服务器，支持P2P数据同步，便于动态站点开发
* 匿名性：支持采用.onion匿踪服务的Tor网络（支持onion-v3）
* TLS加密连接（会经过明网）
* 自动开启uPnP端口（可选）
* 支持多用户插件（openproxy）
* 兼容任何现代浏览器/操作系统
* 离线站点可通过其他方式进行同步（或当连接恢复时同步）

## 它是如何工作的？

* 启动`zeronet.py`后，你可以通过以下方式访问zeronet站点： `http://127.0.0.1:43110/{零网站点地址}` （例如  `http://127.0.0.1:43110/1MCoA8rQHhwu4LY2t2aabqcGSRqrL8uf2X/`）
* 当你访问一个新站点时，它会通过BitTorrent网络来寻找可用节点，从这些节点下载站点所需的文件（如html, css, js...）。
* 每个你访问过的站点也由你提供托管服务。
* 每个站点包含一个`content.json`文件，其中包含着由本站所有文件生成的sha512哈希值以及由站点私钥生成的签名。
* 如果站点拥有者（即持有站点私钥的人）对站点内容进行了修改，则他/她会重新签署`content.json`文件并发布至其他节点。随后，其他节点会验证`content.json`的完整性（通过签名），并下载被修改的文件，随后将更新过的内容继续发布给其他节点。

以下链接来自原版ZeroNet：

- [关于ZeroNet加密、站点更新、多用户站点的演示文稿 »](https://docs.google.com/presentation/d/1_2qK1IuOKJ51pgBvllZ9Yu7Au2l551t3XBgyTSvilew/pub?start=false&loop=false&delayms=3000)
- [常见问题解答 »](https://zeronet.io/docs/faq/)
- [ZeroNet开发者文档 »](https://zeronet.io/docs/site_development/getting_started/)（已过时）

## 如何加入

### 从发行版仓库安装

- NixOS: [搜索zeronet-conservancy软件包](https://search.nixos.org/packages?from=0&size=50&sort=relevance&type=packages&query=zeronet-conservancy)（并参见下方）
- ArchLinux: [最新发行版](https://aur.archlinux.org/packages/zeronet-conservancy)，[最新git版](https://aur.archlinux.org/packages/zeronet-conservancy-git)

### 从Nix包管理器安装（Linux 或 MacOS）

- 安装并配置nix包管理器（如果需要的话）
- `nix-env -iA nixpkgs.zeronet-conservancy`

如果您使用的是NixOS系统，将`zeronet-conservancy`添加到系统配置中

（感谢 @fgaz 制作并维护此软件包）

### 从源代码安装

#### 系统依赖项

##### 通用的类Unix系统（包括MacOS X）

安装autoconf和其他基本开发工具，python3和pip，然后看“构建python依赖”

##### 基于Apt的系统（debian、ubuntu等）
 - `sudo apt update`
 - `sudo apt install git pkg-config libffi-dev python3-pip python3-venv python3-dev build-essential libtool`

##### 基于Red Hat和Fedora的系统
 - `yum install epel-release -y 2>/dev/null`
 - `yum install git python3 python3-wheel`

##### 基于Fedora系统的dandified包管理器
 - `sudo dnf install git python3-pip python3-wheel -y`

##### openSUSE
 - `sudo zypper install python3-pip python3-setuptools python3-wheel`

##### 基于Arch和Manjaro的系统
 - `sudo pacman -S git python-pip -v --no-confirm`

##### Android/Termux
 - 安装 [Termux](https://termux.com/)（在Termux中可以通过以下命令安装包`pkg install <package-names>`）
 - `pkg update`
 - `pkg install python automake git binutils libtool`
 - （在旧Android系统上可能还需安装这个）`pkg install openssl-tool libcrypt clang`
 - （若安装了上述包仍在启动时遇到问题，请告诉我们）
 - （可选）`pkg install tor`
 - （可选）通过以下命令运行Tor：`tor --ControlPort 9051 --CookieAuthentication 1`（你可以通过右滑来打开新会话）

#### 构建python依赖、虚拟环境、运行
 - 克隆此repo（注意：在Android/Termux上应将其克隆到Termux的“home”文件夹中，这是因为虚拟环境无法位于`storage/`）
 - `python3 -m venv venv`（创建python虚拟环境，命令末尾的`venv`只是个名称，若使用其他名称，需在后续命令中替换）
 - `source venv/bin/activate`（激活环境）
 - `python3 -m pip install -r requirements.txt`（安装依赖）
 - `python3 zeronet.py`（**运行zeronet-conservancy！**）
 - 在浏览器中打开登录页面：http://127.0.0.1:43110/
 - 需要在新的终端再次启动的话，进入repo目录并执行：
 - `source venv/bin/activate`
 - `python3 zeronet.py`

#### （可选用）在NixOS上

- 克隆此repo
- 进入已经安装过依赖的shell：`nix-shell '<nixpkgs>' -A zeronet-conservancy`
- `./zeronet.py`

#### （可选用）构建Docker镜像
- 构建0net镜像：`docker build -t 0net-conservancy:latest . -f Dockerfile`
- 或构建集成tor的0net镜像：`docker build -t 0net-conservancy:latest . -f Dockerfile.integrated_tor`
- 运行它：`docker run --rm -it -v </path/to/0n/data/directory>:/app/data -p 43110:43110 -p 26552:26552 0net-conservancy:latest`
- /path/to/0n/data/directory - 该目录保存所有数据，包括你的私钥证书。如果在生产模式下运行，请千万不要删除这个文件夹！
- 也可以通过docker-compose运行：`docker compose up -d 0net-conservancy` 来启动两个容器——0net和tor各自运行。
- 或者在同一个容器中运行0net和tor：`docker compose up -d 0net-tor` 。
（请检查上述说明是否仍然可行）

#### 可选用单行命令（提供者@ssdifnskdjfnsdjk）（全局安装Python依赖）

克隆Github仓库并安装所需的Python模块。首先编辑命令开头的zndir，将其改为你想要存储`zeronet-conservancy`的路径：

`zndir="/home/user/myapps/zeronet" ; if [[ ! -d "$zndir" ]]; then git clone --recursive "https://github.com/zeronet-conservancy/zeronet-conservancy.git" "$zndir" && cd "$zndir"||exit; else cd "$zndir";git pull origin master; fi; cd "$zndir" && pip install -r requirements.txt|grep -v "already satisfied"; echo "Try to run: python3 $(pwd)/zeronet.py"`

（此命令也可用于保持`zeronet-conservancy`是最新版本）

#### 可选用脚本
 - 安装通用依赖和克隆repo（如上所述）后，
   运行`start-venv.sh`，它将为你创建虚拟环境并安装Python依赖
 - 以后会添加更多便捷脚本

### （非官方的）Windows系统构建版本

下载并解压以下.zip压缩包
[zeronet-conservancy-0.7.10-unofficial-win64.zip](https://github.com/zeronet-conservancy/zeronet-conservancy/releases/download/v0.7.10/zeronet-conservancy-0.7.10-unofficial-win64.zip)

### 在Windows操作系统下构建

（这些说明正在测试当中，请帮助我们测试并改进它！）

- 安装Python： https://www.python.org/downloads/
- 安装在Windows下适用于Python的编译器，这对我这种非Windows用户来说是最难的一步（详见 https://wiki.python.org/moin/WindowsCompilers ，之后我会提供更多参考）
- [可选，如需获取最新开发版本]安装Git：https://git-scm.com/downloads
- [可选，如需为更好的连接性和匿名性来使用tor]安装tor浏览器：https://www.torproject.org/download/ 
- 打开git bash控制台
- 在命令行输入或粘贴`git clone https://github.com/zeronet-conservancy/zeronet-conservancy.git`
- 等待，直至git下载好最新的开发版本，然后继续在控制台操作
- `cd zeronet-conservancy`
- `python -m venv venv`（创建Python虚拟环境）
- `venv\Scripts\activate`（激活环境）
- `pip install -r requirements.txt`（安装Python依赖）（有些使用者反馈此命令未能成功安装所有依赖，需手动逐个安装依赖）
- （注意：如果上一步失败了，可能说明C/C++编译器未能成功安装）
- [可选，为更好的连接性和匿名性]启动Tor浏览器
- （注意：Windows可能会弹窗，提示出于“安全原因”阻止了网络访问—请选择允许访问）
- `python zeronet.py --tor_proxy 127.0.0.1:9150 --tor_controller 127.0.0.1:9151`（启动zeronet-conservancy！）
- [需要完全匿名，要用如下方式启动]`python zeronet.py --tor_proxy 127.0.0.1:9150 --tor_controller 127.0.0.1:9151 --tor always`
- 在浏览器中访问http://127.0.0.1:43110

构建.exe文件

- 按照上述步骤操作完成后，再执行
- `pip install pyinstaller`
- `pyinstaller -p src -p plugins --hidden-import merkletools --hidden-import lib.bencode_open --hidden-import Crypt.Crypt --hidden-import Db.DbQuery --hidden-import lib.subtl --hidden-import lib.subtl.subtl --hidden-import sockshandler --add-data "src;src" --add-data "plugins;plugins" --clean zeronet.py`
- dist/zeronet 路径下会包含可用的 zeronet.exe！

## 目前的局限性

* 文件传输未压缩
* 不支持私密站点
* 不支持DHT
* 不支持I2P
* 不支持中心化的模块，比如zeroid（我们正在改进！）
* 尚无可靠的垃圾信息保护措施（我们也在改进）
* 无法直接在浏览器中使用（中长期会优先解决此问题）
* 不支持数据透明
* 尚无可重现构建
* 不支持磁盘加密存储
* 尚无可重现构建（因此在部分GNU/Linux发行版之外无法构建）


## 我该如何创建一个ZeroNet站点？

 * 点击[仪表盘](http://127.0.0.1:43110/191CazMVNaAcT9Y1zhkxd9ixMBPs59g2um/)菜单中的 **⋮** > **"Create new, empty site"** 。
 * 你将被**重定向**到一个只有你可以修改的全新站点！
 * 你可以在 **data/[你的站点地址]** 目录中找到并修改你的站点内容。
 * 修改完成后，打开你的站点，向左拖动页面右上角的“0”按钮，然后点击底部的**sign and publish**按钮。

下一步请看：[ZeroNet开发者文档](https://zeronet.io/docs/site_development/getting_started/)

## 帮助此项目持续发展

### 成为维护者

我们需要更多的维护者！今天就加入吧！你不需要懂编程，这里还有很多其他工作要做。

### 为你的平台创建构建包

我们需要为各个主流操作系统平台提供独立构建的版本，并存入各种FLOSS仓库。如果你正在使用的Linux发行版还没有得到我们提供的相应构建包，为何不自己创建一个，或者（如果你不知道怎么做）去询问你的系统维护者呢？

### 修复bug & 添加功能

我们决心继续前进，打造一个完美的p2p网络，因此我们需要更多的帮助来实现它。

### 创建你的站点/带来你的内容

我们知道这份文档有所欠缺，但我们尽力支持任何希望迁移站点和内容的用户。请不要犹豫，随时联系我们。

### 使用并传播

告诉大家你为何选择使用0net及我们这个特别的分支！人们需要知道他们的替代方案。

### 资金支持我们

此分支由@caryoscelus创建并维护。你可以在 https://caryoscelus.github.io/donate/ 上查看捐赠方式（如果在github上阅读，也可查看侧边栏了解更多途径）。随着我们团队的不断壮大，我们也会在更友善的众筹平台上创建团队账户。

如果你想确保你的捐赠会被视作对本项目的支持，下面是一个专门的比特币地址：
1Kjuw3reZvxRVNs27Gen7jPJYCn6LY7Fg6。如需更匿名和私密的方式，以下是Monero钱包地址：
4AiYUcqVRH4C2CVr9zbBdkhRnJnHiJoypHEsq4N7mQziGUoosPCpPeg8SPr87nvwypaRzDgMHEbWWDekKtq8hm9LBmgcMzC

如果你希望通过其他方式捐赠，请随时联系维护者或创建一个issue。

# 我们在抗议的情况下使用GitHub

该项目当前托管在GitHub。但这并不理想；GitHub是一个专有的、有其商业秘密的系统，不是自由及开放源代码软件（FLOSS）。我们对使用像GitHub这样的专有系统来开发我们的FLOSS项目深感担忧。我们有一个[开放的议题页面](https://github.com/zeronet-conservancy/zeronet-conservancy/issues/89)来追踪从长远来看迁移出GitHub的进展。我们强烈建议你阅读[放弃 GitHub](https://GiveUpGitHub.org)运动以及[软件自由保护协会](https://sfconservancy.org)对其的阐述，以便了解为什么GitHub不适合托管FOSS项目。

如果你是已经停止使用GitHub的贡献者，欢迎[在notabug上查看我们的镜像](https://notabug.org/caryoscelus/zeronet-conservancy)，并在那里进行开发，或者通过[联系方式](https://caryoscelus.github.io/contacts/)直接向项目维护者发送git补丁。

无论过去还是现在，未经许可地通过GitHub Copilot使用本项目的代码的行为必须立即停止。我们不允许GitHub将本项目代码用于Copilot。

![GiveUpGitHub运动的标志](https://sfconservancy.org/img/GiveUpGitHub.png)
