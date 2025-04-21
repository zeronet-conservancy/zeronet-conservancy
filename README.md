# zeronet-conservancy

[![Packaging status](https://repology.org/badge/vertical-allrepos/zeronet-conservancy.svg)](https://repology.org/project/zeronet-conservancy/versions)

(NOTE THAT TRANSLATIONS ARE USUALLY BEHIND THIS FILE)

[по-русски](README-ru.md) | [em português](README-ptbr.md) | [简体中文](README-zh-cn.md) | [日本語](README-ja.md)

`zeronet-conservancy` is a modern client of
[ZeroNet](https://github.com/HelloZeroNet/ZeroNet) network, aimed at
creating peer-to-peer distributed web for people.

## v0.8 status

For a few years `zeronet-conservancy` was maintained as mainly status
quo fork of original client. With v0.8 that is changing — here's
overview of new stuff (some already implemented, some in development):

- user limits/spam protection are handled on per-node basis. i.e. part
  of network may propagate some content and another consider it spam
  and keep it out
- interactive content without ZeroID registration
- apps are switching to using user data in user-controlled location
- DHT allows using even less hard-coded servers (in particular in the
  best scenario it should be possible to only have to initialize once
  using particular server)
- switch to new UI, control panel/start page
- local full-text and p2p search
- more native builds and browser bundle option

When to expect v0.8 release? We don't know, when it's ready.

## What is this?

- decentralized
- locally hosted
- censorship-resistant
- real-time updated web
- that gives you control over your data
- without blockchain

### Install from your distribution repository

- NixOS: [zeronet-conservancy packages search](https://search.nixos.org/packages?from=0&size=50&sort=relevance&type=packages&query=zeronet-conservancy) (and see below)
- ArchLinux: [latest release](https://aur.archlinux.org/packages/zeronet-conservancy), [fresh git version](https://aur.archlinux.org/packages/zeronet-conservancy-git)

### Install from Nix package manager (Linux or MacOS)

 - install & configure nix package manager (if needed)
 - `nix-env -iA nixpkgs.zeronet-conservancy`

or add `zeronet-conservancy` to your system configuration if you're on NixOS

(thanks @fgaz for making & maintaining the package)

### Install from source

#### System dependencies

##### Generic unix-like (including mac os x)

Install autoconf and other basic development tools, python3 and pip, then proceed to "building python dependencies"
(if running fails due to missing dependency, please report it/make pull request to fix dependency list)

##### Apt-based (debian, ubuntu, etc)
 - `sudo apt update`
 - `sudo apt install git pkg-config libffi-dev python3-pip python3-venv python3-dev build-essential libtool`

##### Red Hat and Fedora based
 - `yum install epel-release -y 2>/dev/null`
 - `yum install git python3 python3-wheel`

##### Fedora based dandified
 - `sudo dnf install git python3-pip python3-wheel -y`

##### openSUSE
 - `sudo zypper install python3-pip python3-setuptools python3-wheel`

##### Arch and Manjaro based
 - `sudo pacman -S git python-pip -v --no-confirm`

##### Android/Termux
 - install [Termux](https://termux.com/) (in Termux you can install packages via `pkg install <package-names>`)
 - `pkg update`
 - `pkg install python automake git binutils libtool`
 - (on an older android versions you may also need to install) `pkg install openssl-tool libcrypt clang`
 - (if you've installed the above packages and still run into launch issues, please report)
 - (optional) `pkg install tor`
 - (optional) run tor via `tor --ControlPort 9051 --CookieAuthentication 1` command (you can then open new session by swiping to the right)

#### Building python dependencies, venv & running
 - clone this repo (NOTE: on Android/Termux you should clone it into "home" folder of Termux, because virtual environment cannot live in `storage/`)
 - `python3 -m venv venv` (make python virtual environment, the last `venv` is just a name, if you use different you should replace it in later commands)
 - `source venv/bin/activate` (activate environment)
 - `python3 -m pip install -r requirements.txt` (install dependencies)
 - `python3 zeronet.py` (**run zeronet-conservancy!**)
 - open the landing page in your browser by navigating to: http://127.0.0.1:43110/
 - to start it again from fresh terminal, you need to navigate to repo directory and:
 - `source venv/bin/activate`
 - `python3 zeronet.py`

#### (alternatively) On NixOS
- clone this repo
- `nix-shell '<nixpkgs>' -A zeronet-conservancy` to enter shell with installed dependencies
- `./zeronet.py`

#### (alternatively) Build Docker image
- build 0net image: `docker build -t 0net-conservancy:latest . -f Dockerfile`
- or build 0net image with integrated tor: `docker build -t 0net-conservancy:latest . -f Dockerfile.integrated_tor`
- and run it: `docker run --rm -it -v </path/to/0n/data/directory>:/app/data -p 43110:43110 -p 26552:26552 0net-conservancy:latest`
- /path/to/0n/data/directory - directory, where all data will be saved, including your secret certificates. If you run it with production mode, do not remove this folder!
- or you can run it with docker-compose: `docker compose up -d 0net-conservancy` up two containers - 0net and tor separately.
- or: `docker compose up -d 0net-tor` for run 0net and tor in one container.
(please check if these instructions are still accurate)

#### Alternative one-liner (by @ssdifnskdjfnsdjk) (installing python dependencies globally)

Clone Github repository and install required Python modules. First
edit zndir path at the begining of the command, to be the path where
you want to store `zeronet-conservancy`:

`zndir="/home/user/myapps/zeronet" ; if [[ ! -d "$zndir" ]]; then git clone --recursive "https://github.com/zeronet-conservancy/zeronet-conservancy.git" "$zndir" && cd "$zndir"||exit; else cd "$zndir";git pull origin master; fi; cd "$zndir" && pip install -r requirements.txt|grep -v "already satisfied"; echo "Try to run: python3 $(pwd)/zeronet.py"`

(This command can also be used to keep `zeronet-conservancy` up to date)

#### Alternative script
 - after installing general dependencies and cloning repo (as above),
   run `start-venv.sh` which will create a virtual env for you and
   install python requirements
 - more convenience scripts to be added soon

### (unofficial) Windows OS build

Download and extract .zip archive
[zeronet-conservancy-0.7.10-unofficial-win64.zip](https://github.com/zeronet-conservancy/zeronet-conservancy/releases/download/v0.7.10/zeronet-conservancy-0.7.10-unofficial-win64.zip)

### Building under Windows OS

(These instructions are work-in-progress, please help us test it and improve it!)

- install python from https://www.python.org/downloads/
- install some windows compiler suitable for python , this proved to be the most difficult part for me as non-windows user (see here https://wiki.python.org/moin/WindowsCompilers and i'll link more references later)
- [optionally to get latest dev version] install git from https://git-scm.com/downloads
- [optionally to use tor for better connectivity and anonymization] install tor browser from https://www.torproject.org/download/
- open git bash console
- type/copypaste `git clone https://github.com/zeronet-conservancy/zeronet-conservancy.git` into command line
- wait till git downloads latest dev version and continue in console
- `cd zeronet-conservancy`
- `python -m venv venv` (create virtual python environment)
- `venv\Scripts\activate` (this activates the environment)
- `pip install -r requirements.txt` (install python dependencies) (some users reported that this command doesn't successfully install requirements and only manual installation of dependencies one by one works)
- (NOTE: if previous step fails, it most likely means you haven't installed c/c++ compiler successfully)
- [optional for tor for better connectivity and anonymity] launch Tor Browser
- (NOTE: windows might show a window saying it blocked access to internet for "security reasons" — you should allow the access)
- `python zeronet.py --tor_proxy 127.0.0.1:9150 --tor_controller 127.0.0.1:9151` (launch zeronet-conservancy!)
- [for full tor anonymity launch this instead] `python zeronet.py --tor_proxy 127.0.0.1:9150 --tor_controller 127.0.0.1:9151 --tor always`
- navigate to http://127.0.0.1:43110 in your favourite browser!

To build .exe

- follow the same steps as above, but additionally
- `pip install pyinstaller`
- `pyinstaller -p src -p plugins --hidden-import merkletools --hidden-import lib.bencode_open --hidden-import Crypt.Crypt --hidden-import Db.DbQuery --hidden-import lib.subtl --hidden-import lib.subtl.subtl --hidden-import sockshandler --add-data "src;src" --add-data "plugins;plugins" --clean zeronet.py`
- dist/zeronet should contain working zeronet.exe!

## Current limitations

* File transactions are not compressed
* No private sites
* No DHT support
* No I2P support
* Centralized elements like zeroid (we're working on this!)
* No reliable spam protection (and on this too)
* Doesn't work directly from browser (one of the top priorities for mid-future)
* No data transparency
* No reproducible builds
* No on-disk encryption
* No reproducible builds (hence no builds beyond certain GNU/Linux distributions)


## How can I create a ZeroNet site?

 * Click on **⋮** > **"Create new, empty site"** menu item on the [dashboard](http://127.0.0.1:43110/191CazMVNaAcT9Y1zhkxd9ixMBPs59g2um/).
 * You will be **redirected** to a completely new site that is only modifiable by you!
 * You can find and modify your site's content in **data/[yoursiteaddress]** directory
 * After the modifications open your site, drag the topright "0" button to the left, then press **sign and publish** button on the bottom

Next steps: [ZeroNet Developer Documentation](https://zeronet.io/docs/site_development/getting_started/)

## Help this project stay alive

### Become a maintainer

We need more maintainers! Become one today! You don't need to know how to code,
there's a lot of other work to do.

### Make builds for your platforms

We need reproducible stand-alone builds for major platforms, as well as presense in various FLOSS
repositories. If you're using one of Linux distributions which don't have packages yet, why not make
a package for it or (if you don't know how) ask a maintainer now?

### Fix bugs & add features

We've decided to go ahead and make a perfect p2p web, so we need more help
implementing it.

### Make your site/bring your content

We know the documentation is lacking, but we try our best to support anyone
who wants to migrate. Don't hesitate to ask.

### Use it and spread the word

Make sure to tell people why do you use 0net and this fork in particular! People
need to know their alternatives.

### Financially support maintainers

This fork was created and maintained by @caryoscelus. You can
see ways to donate to them on https://caryoscelus.github.io/donate/ (or check
sidebar if you're reading this on github for more ways). As our team grows, we
will create team accounts on friendly crowdfunding platforms as well.

If you want to make sure your donation is recognized as donation for this
project, there is a dedicated bitcoin address for that, too:
1Kjuw3reZvxRVNs27Gen7jPJYCn6LY7Fg6. And if you want to stay more anonymous and
private, a Monero wallet:
4AiYUcqVRH4C2CVr9zbBdkhRnJnHiJoypHEsq4N7mQziGUoosPCpPeg8SPr87nvwypaRzDgMHEbWWDekKtq8hm9LBmgcMzC

If you want to donate in a different way, feel free to contact maintainer or
create an issue

# We're using GitHub under protest

This project is currently hosted on GitHub. This is not ideal; GitHub is a
proprietary, trade-secret system that is not Free/Libre and Open Souce Software
(FLOSS). We are deeply concerned about using a proprietary system like GitHub
to develop our FLOSS project. We have an
[open issue](https://github.com/zeronet-conservancy/zeronet-conservancy/issues/89)
to track moving away from GitHub in the long term.  We urge you to read about the
[Give up GitHub](https://GiveUpGitHub.org) campaign from
[the Software Freedom Conservancy](https://sfconservancy.org) to understand
some of the reasons why GitHub is not a good place to host FOSS projects.

If you are a contributor who personally has already quit using GitHub, feel
free to [check out from our mirror on notabug](https://notabug.org/caryoscelus/zeronet-conservancy)
and develop there or send git patches directly to project maintainer via
preffered [contact channel](https://caryoscelus.github.io/contacts/).

Any use of this project's code by GitHub Copilot, past or present, is done
without our permission. We do not consent to GitHub's use of this project's
code in Copilot.

![Logo of the GiveUpGitHub campaign](https://sfconservancy.org/img/GiveUpGitHub.png)
