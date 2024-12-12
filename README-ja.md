# zeronet-conservancy

[![Packaging status](https://repology.org/badge/vertical-allrepos/zeronet-conservancy.svg)](https://repology.org/project/zeronet-conservancy/versions)

(このファイルの翻訳は通常このファイルの後ろにあります)

[по-русски](README-ru.md) | [em português](README-ptbr.md) | [简体中文](README-zh-cn.md) | 日本語

`zeronet-conservancy`は[ZeroNet](https://github.com/HelloZeroNet/ZeroNet)プロジェクトのフォーク/継続です
（その作成者によって放棄された）、既存のp2pネットワークを維持し、開発することに専念しています
分散化と自由の価値観を持ちながら、徐々により良い設計のネットワークに移行していきます

## アクティブなメンテナーの警告なし

このフォークは@caryoscelusによって作成および維持されましたが、興味が薄れたため、
もう一人のプロジェクトを持つことを避けるために、開発は制限されています。

## なぜフォークするのか？

onion-v3スイッチの危機の間、私たちはonion-v3で動作し、1人または
2人の人々への信頼に依存しないフォークが必要でした。このフォークはその使命を果たすことから始まりました
誰でも簡単に監査できる[ZeroNet/py3](https://github.com/HelloZeroNet/ZeroNet/tree/py3)ブランチに最小限の変更を加えます。
フォークの初期リリースを使用してonion-v3を動作させることはまだできますが、このフォークの目標はそれ以来シフトしました
新しい、完全に透明で監査されたネットワークが準備が整い、このプロジェクトが休止できるまで、より多くの問題を解決し、ユーザーエクスペリエンスとセキュリティを全体的に改善することに専念しています

## なぜ0netなのか？

* 私たちは、オープンで自由で検閲されていないネットワークとコミュニケーションを信じています。
* 単一障害点がない：少なくとも1つのピアが
  それを提供しています。
* ホスティングコストなし：サイトは訪問者によって提供されます。
* シャットダウンすることは不可能です：どこにもないのでどこにでもあります。
* 高速でオフラインで動作します：インターネットが利用できない場合でもサイトにアクセスできます。

## 特徴
 * リアルタイムで更新されるサイト
 * ワンクリックでウェブサイトをクローン
 * プライベート/パブリックキーを使用したパスワードレス認証
 * P2Pデータ同期を備えた組み込みSQLサーバー：より簡単な動的サイト開発を可能にします
 * 匿名性：.onion隠しサービスを使用したTorネットワークのサポート（onion-v3サポートを含む）
 * TLS暗号化接続（クリーンネット経由）
 * 自動uPnPポート開放（オプトインした場合）
 * マルチユーザー（オープンプロキシ）サポート用のプラグイン
 * すべてのモダンブラウザ/OSで動作
 * オフラインで動作し、代替トランスポートを介して同期できます（または接続が戻ったとき）

## どのように機能しますか？

* `zeronet.py`を起動した後、zeronetサイトにアクセスできるようになります
  `http://127.0.0.1:43110/{zeronet_address}`（例：
  `http://127.0.0.1:43110/1MCoA8rQHhwu4LY2t2aabqcGSRqrL8uf2X/`）。
* 新しいzeronetサイトにアクセスすると、BitTorrentを使用してピアを見つけようとします
  ネットワークは、サイトファイル（html、css、js ...）をそれらからダウンロードできるようにします。
* 訪問した各サイトもあなたによって提供されます。
* すべてのサイトには、すべての他のファイルをsha512ハッシュで保持する`content.json`ファイルが含まれています
  およびサイトの秘密鍵を使用して生成された署名。
* サイト所有者（サイトアドレスの秘密鍵を持っている人）がサイトを変更した場合
  サイト、次に彼/彼女は新しい`content.json`に署名し、それをピアに公開します。
  その後、ピアは`content.json`の整合性を確認します（
  署名）、変更されたファイルをダウンロードし、新しいコンテンツを
  他のピア。

次のリンクは、元のZeroNetに関連しています。

- [ZeroNetの暗号化、サイトの更新、マルチユーザーサイトに関するスライドショー»](https://docs.google.com/presentation/d/1_2qK1IuOKJ51pgBvllZ9Yu7Au2l551t3XBgyTSvilew/pub?start=false&loop=false&delayms=3000)
- [よくある質問»](https://zeronet.io/docs/faq/)
- [ZeroNet開発者ドキュメント»](https://zeronet.io/docs/site_development/getting_started/)（古くなっています）

## 参加方法

### ディストリビューションリポジトリからインストール

- NixOS：[zeronet-conservancyパッケージ検索](https://search.nixos.org/packages?from=0&size=50&sort=relevance&type=packages&query=zeronet-conservancy)（以下を参照）
- ArchLinux：[最新リリース](https://aur.archlinux.org/packages/zeronet-conservancy)、[最新のgitバージョン](https://aur.archlinux.org/packages/zeronet-conservancy-git)

### Nixパッケージマネージャーからインストール（LinuxまたはMacOS）

 - nixパッケージマネージャーをインストールして構成します（必要に応じて）
 - `nix-env -iA nixpkgs.zeronet-conservancy`

または、NixOSを使用している場合は、システム構成に`zeronet-conservancy`を追加します

（パッケージの作成と維持を行ってくれた@fgazに感謝します）

### ソースからインストール

#### システム依存関係

##### 一般的なUnix系（mac os xを含む）

autoconfおよびその他の基本的な開発ツール、python3およびpipをインストールし、「ビルドpython依存関係」に進みます
（実行に失敗した場合は、欠落している依存関係を報告するか、依存関係リストを修正するためのプルリクエストを作成してください）

##### Aptベース（debian、ubuntuなど）
 - `sudo apt update`
 - `sudo apt install git pkg-config libffi-dev python3-pip python3-venv python3-dev build-essential libtool`

##### Red HatおよびFedoraベース
 - `yum install epel-release -y 2>/dev/null`
 - `yum install git python3 python3-wheel`

##### Fedoraベースのdandified
 - `sudo dnf install git python3-pip python3-wheel -y`

##### openSUSE
 - `sudo zypper install python3-pip python3-setuptools python3-wheel`

##### ArchおよびManjaroベース
 - `sudo pacman -S git python-pip -v --no-confirm`

##### Android/Termux
 - [Termux](https://termux.com/)をインストールします（Termuxでは、`pkg install <package-names>`を使用してパッケージをインストールできます）
 - `pkg update`
 - `pkg install python automake git binutils libtool`
 - （古いandroidバージョンでは、`pkg install openssl-tool libcrypt clang`もインストールする必要がある場合があります）
 - （上記のパッケージをインストールしても起動の問題が発生する場合は、報告してください）
 - （オプション）`pkg install tor`
 - （オプション）`tor --ControlPort 9051 --CookieAuthentication 1`コマンドを使用してtorを実行します（右にスワイプして新しいセッションを開くことができます）

#### python依存関係、venvのビルドと実行
 - このリポジトリをクローンします（注：Android/Termuxでは、仮想環境が`storage/`に存在できないため、Termuxの「ホーム」フォルダにクローンする必要があります）
 - `python3 -m venv venv`（python仮想環境を作成します。最後の`venv`は名前にすぎません。後のコマンドで置き換える必要がある場合は、別の名前を使用してください）
 - `source venv/bin/activate`（環境をアクティブ化）
 - `python3 -m pip install -r requirements.txt`（依存関係をインストール）
 - `python3 zeronet.py`（**zeronet-conservancyを実行！**）
 - ブラウザでランディングページを開き、http://127.0.0.1:43110/ に移動します
 - 新しいターミナルから再起動するには、リポジトリディレクトリに移動して次のコマンドを実行する必要があります：
 - `source venv/bin/activate`
 - `python3 zeronet.py`

#### （代替）NixOSで
- このリポジトリをクローン
- `nix-shell '<nixpkgs>' -A zeronet-conservancy`を実行して、依存関係がインストールされたシェルに入ります
- `./zeronet.py`

#### （代替）Dockerイメージのビルド
- 0netイメージをビルド：`docker build -t 0net-conservancy:latest . -f Dockerfile`
- 統合されたtorを使用して0netイメージをビルド：`docker build -t 0net-conservancy:latest . -f Dockerfile.integrated_tor`
- 実行：`docker run --rm -it -v </path/to/0n/data/directory>:/app/data -p 43110:43110 -p 26552:26552 0net-conservancy:latest`
- /path/to/0n/data/directory - すべてのデータが保存されるディレクトリ。秘密の証明書も含まれます。運用モードで実行する場合は、このフォルダを削除しないでください！
- または、docker-composeを使用して実行できます：`docker compose up -d 0net-conservancy`は、0netとtorの2つのコンテナを個別に起動します。
- または：`docker compose up -d 0net-tor`を実行して、1つのコンテナで0netとtorを実行します。
（これらの手順がまだ正確かどうかを確認してください）

#### 代替のワンライナー（@ssdifnskdjfnsdjkによる）（python依存関係をグローバルにインストール）

Githubリポジトリをクローンし、必要なPythonモジュールをインストールします。最初に
コマンドの先頭にあるzndirパスを、`zeronet-conservancy`を保存するパスに編集します：

`zndir="/home/user/myapps/zeronet" ; if [[ ! -d "$zndir" ]]; then git clone --recursive "https://github.com/zeronet-conservancy/zeronet-conservancy.git" "$zndir" && cd "$zndir"||exit; else cd "$zndir";git pull origin master; fi; cd "$zndir" && pip install -r requirements.txt|grep -v "already satisfied"; echo "Try to run: python3 $(pwd)/zeronet.py"`

（このコマンドは、`zeronet-conservancy`を最新の状態に保つためにも使用できます）

#### 代替スクリプト
 - 一般的な依存関係をインストールし、リポジトリをクローンした後（上記のように）、
   `start-venv.sh`を実行して仮想環境を作成し、
   pythonの要件をインストールします
 - 便利なスクリプトを近日追加予定

### （非公式）Windows OSビルド

.zipアーカイブをダウンロードして解凍します
[zeronet-conservancy-0.7.10-unofficial-win64.zip](https://github.com/zeronet-conservancy/zeronet-conservancy/releases/download/v0.7.10/zeronet-conservancy-0.7.10-unofficial-win64.zip)

### Windows OSでのビルド

（これらの手順は進行中の作業です。テストして改善するのに役立ててください！）

- https://www.python.org/downloads/ からpythonをインストールします
- pythonに適したWindowsコンパイラをインストールします。これが私にとって最も難しい部分でした（https://wiki.python.org/moin/WindowsCompilers を参照し、後でさらに参考資料をリンクします）
- [最新の開発バージョンを取得するためにオプション] https://git-scm.com/downloads からgitをインストールします
- [より良い接続性と匿名性のためにtorを使用するためにオプション] https://www.torproject.org/download/ からtorブラウザをインストールします
- git bashコンソールを開きます
- コマンドラインに`git clone https://github.com/zeronet-conservancy/zeronet-conservancy.git`を入力/コピーします
- gitが最新の開発バージョンをダウンロードするのを待ち、コンソールで続行します
- `cd zeronet-conservancy`
- `python -m venv venv`（仮想python環境を作成します）
- `venv\Scripts\activate`（これにより環境がアクティブになります）
- `pip install -r requirements.txt`（python依存関係をインストールします）（一部のユーザーは、このコマンドが依存関係を正常にインストールせず、依存関係を1つずつ手動でインストールする必要があると報告しています）
- （注：前のステップが失敗した場合、c/c++コンパイラが正常にインストールされていない可能性が高いです）
- [より良い接続性と匿名性のためにtorを使用するためにオプション] Torブラウザを起動します
- （注：Windowsは「セキュリティ上の理由から」インターネットへのアクセスをブロックしたというウィンドウを表示する場合があります。アクセスを許可する必要があります）
- `python zeronet.py --tor_proxy 127.0.0.1:9150 --tor_controller 127.0.0.1:9151`（zeronet-conservancyを起動！）
- [完全なtor匿名性のためにこれを起動] `python zeronet.py --tor_proxy 127.0.0.1:9150 --tor_controller 127.0.0.1:9151 --tor always`
- お気に入りのブラウザでhttp://127.0.0.1:43110 に移動します！

.exeをビルドするには

- 上記と同じ手順に従いますが、さらに
- `pip install pyinstaller`
- `pyinstaller -p src -p plugins --hidden-import merkletools --hidden-import lib.bencode_open --hidden-import Crypt.Crypt --hidden-import Db.DbQuery --hidden-import lib.subtl --hidden-import lib.subtl.subtl --hidden-import sockshandler --add-data "src;src" --add-data "plugins;plugins" --clean zeronet.py`
- dist/zeronetには動作するzeronet.exeが含まれているはずです！

## 現在の制限

* ファイルトランザクションは圧縮されません
* プライベートサイトなし
* DHTサポートなし
* I2Pサポートなし
* zeroidのような集中化された要素（これに取り組んでいます！）
* 信頼できるスパム保護なし（これにも取り組んでいます）
* ブラウザから直接動作しません（中期的な優先事項の1つ）
* データの透明性なし
* 再現可能なビルドなし
* オンディスク暗号化なし
* 再現可能なビルドなし（したがって、特定のGNU/Linuxディストリビューションを超えたビルドはありません）

## ZeroNetサイトを作成するにはどうすればよいですか？

 * [ダッシュボード](http://127.0.0.1:43110/191CazMVNaAcT9Y1zhkxd9ixMBPs59g2um/)の**⋮** > **「新しい空のサイトを作成」**メニュー項目をクリックします。
 * **リダイレクト**され、あなただけが変更できる完全に新しいサイトに移動します！
 * **data/[yoursiteaddress]**ディレクトリでサイトのコンテンツを見つけて変更できます
 * 変更後にサイトを開き、右上の「0」ボタンを左にドラッグしてから、下部の**署名して公開**ボタンを押します

次のステップ：[ZeroNet開発者ドキュメント](https://zeronet.io/docs/site_development/getting_started/)

## このプロジェクトを存続させるために支援する

### メンテナーになる

もっとメンテナーが必要です！今日1つになりましょう！コーディング方法を知る必要はありません、
他にもたくさんの仕事があります。

### プラットフォーム用のビルドを作成する

主要なプラットフォーム用の再現可能なスタンドアロンビルド、およびさまざまなFLOSSリポジトリへのプレゼンスが必要です。まだパッケージがないLinuxディストリビューションの1つを使用している場合は、パッケージを作成するか（方法がわからない場合は）今すぐメンテナーに依頼してみませんか？

### バグを修正し、機能を追加する

私たちは前進し、完璧なp2pウェブを作成することにしました。したがって、実装を支援するためにさらに多くの支援が必要です。

### サイトを作成する/コンテンツを持ち込む

ドキュメントが不足していることはわかっていますが、できる限りのサポートを提供しようとしています
移行したい人。遠慮なく質問してください。

### 使用して広める

なぜ0netとこのフォークを特に使用するのかを人々に必ず伝えてください！人々
彼らの選択肢を知る必要があります。

### メンテナーを財政的に支援する

このフォークは@caryoscelusによって作成および維持されました。あなたは
https://caryoscelus.github.io/donate/ で彼らに寄付する方法を確認してください（または
githubでこれを読んでいる場合は、他の方法についてはサイドバーを確認してください）。私たちのチームが成長するにつれて、私たちは
フレンドリーなクラウドファンディングプラットフォームにチームアカウントを作成します。

このプロジェクトへの寄付として寄付が認識されることを確認したい場合は、
専用のビットコインアドレスもあります：
1Kjuw3reZvxRVNs27Gen7jPJYCn6LY7Fg6。より匿名でプライベートにしたい場合は、Moneroウォレット：
4AiYUcqVRH4C2CVr9zbBdkhRnJnHiJoypHEsq4N7mQziGUoosPCpPeg8SPr87nvwypaRzDgMHEbWWDekKtq8hm9LBmgcMzC

別の方法で寄付したい場合は、メンテナーに連絡するか、
問題を作成する

# 抗議の下でGitHubを使用しています

このプロジェクトは現在GitHubでホストされています。これは理想的ではありません。 GitHubは
フリー/リブレおよびオープンソースソフトウェアではない独自のトレードシークレットシステム
（FLOSS）。 GitHubのような独自のシステムを使用してFLOSSプロジェクトを開発することについて深く懸念しています。私たちは
長期的にGitHubから移行するための[オープンイシュー](https://github.com/zeronet-conservancy/zeronet-conservancy/issues/89)があります。 [Give up GitHub](https://GiveUpGitHub.org)キャンペーンについて読むことをお勧めします
[ソフトウェアフリーダムコンセルバンシー](https://sfconservancy.org)から
GitHubがFOSSプロジェクトをホストするのに適していない理由のいくつかを理解するため。

すでにGitHubの使用を個人的にやめたコントリビューターの場合は、
[notabugのミラーからチェックアウト](https://notabug.org/caryoscelus/zeronet-conservancy)
して、そこで開発するか、gitパッチをプロジェクトメンテナーに直接送信します
[連絡先チャネル](https://caryoscelus.github.io/contacts/)を好む。

GitHub Copilotによるこのプロジェクトのコードの過去または現在の使用は、
私たちの許可なしに行われます。私たちは、Copilotでこのプロジェクトのコードを使用することに同意しません。

![GiveUpGitHubキャンペーンのロゴ](https://sfconservancy.org/img/GiveUpGitHub.png)
